"""Financial Statement Analyser — Streamlit entry point.

Three optional, independent data sources:
- bank statement PDFs (password-protected or not) — parsed and categorized
- a personal finance-tracking spreadsheet exported as .xlsx
- an INDmoney portfolio snapshot (JSON export — see README for how to
  generate one; this is a periodic manual refresh, not a live API call)

Any subset of the three can be loaded; each dashboard section says plainly
when the source it needs isn't there yet, rather than hiding or erroring.
"""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.analysis import (
    INTERNAL_TRANSFER,
    category_summary,
    detect_self_transfers,
    headline_stats,
    monthly_summary,
)
from src.bank_detect import SUPPORTED_BANKS
from src.budget_compare import build_budget_vs_actual
from src.categorize import categorize_dataframe, load_default_rules, parse_rules, validate_rules_yaml
from src.llm.chat import LLMError, build_client
from src.llm.context import AppContext
from src.models import transactions_to_dataframe
from src.parsers import parse_statement
from src.pdf_utils import (
    PasswordRequiredError,
    PdfParseError,
    WrongPasswordError,
    full_text,
    open_pdf,
)
from src.sources.indmoney import load_indmoney_snapshot
from src.sources.personal_sheet import (
    PersonalFinanceData,
    investment_items_to_frame,
    load_personal_sheet,
    section_totals,
)
from src.ui.charts import (
    assets_vs_liabilities_bar,
    balance_chart,
    budget_vs_actual_bar,
    emi_schedule_chart,
    expense_bar,
    income_bar,
    labeled_bar,
    monthly_trend_chart,
)

st.set_page_config(page_title="Financial Statement Analyser", page_icon="🏦", layout="wide")

# ----------------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------------
defaults = {
    "statements": [],
    "parse_errors": [],
    "rules_yaml": load_default_rules(),
    "chat_history": [],
    "detect_transfers": True,
    "sheet_data": None,
    "sheet_error": None,
    "portfolio": None,
    "portfolio_error": None,
}
for key, val in defaults.items():
    st.session_state.setdefault(key, val)

# ----------------------------------------------------------------------------
# Sidebar — 1. Bank statements
# ----------------------------------------------------------------------------
st.sidebar.header("1 · Bank statements")
uploaded_files = st.sidebar.file_uploader(
    "Bank statement PDFs — password-protected is fine",
    type=["pdf"],
    accept_multiple_files=True,
)

file_configs: dict[str, dict] = {}
if uploaded_files:
    for f in uploaded_files:
        with st.sidebar.expander(f.name, expanded=False):
            bank_choice = st.selectbox(
                "Bank", ["Auto-detect"] + SUPPORTED_BANKS, key=f"bank_{f.name}"
            )
            pwd = st.text_input("Password (blank if none)", type="password", key=f"pwd_{f.name}")
        file_configs[f.name] = {
            "file": f,
            "bank": None if bank_choice == "Auto-detect" else bank_choice,
            "password": pwd or None,
        }

st.session_state.detect_transfers = st.sidebar.checkbox(
    "Detect transfers between my own accounts",
    value=st.session_state.detect_transfers,
    help=(
        "When statements from 2+ accounts are loaded, flags matching debit/credit pairs "
        "(same amount, within a few days, different accounts) as internal transfers so "
        "they aren't double-counted as income and spend."
    ),
)

parse_clicked = st.sidebar.button("Parse statements", type="primary", disabled=not uploaded_files)

if parse_clicked:
    statements, errors = [], []
    with st.spinner("Reading statements…"):
        for name, cfg in file_configs.items():
            file_bytes = cfg["file"].getvalue()
            try:
                with open_pdf(file_bytes, cfg["password"]) as pdf:
                    text = full_text(pdf)
                    stmt = parse_statement(pdf, text, source_file=name, bank_hint=cfg["bank"])
                statements.append(stmt)
            except PasswordRequiredError:
                errors.append(f"**{name}** — this file is password-protected. Enter its password and re-parse.")
            except WrongPasswordError:
                errors.append(f"**{name}** — that password didn't work. Double-check it and re-parse.")
            except PdfParseError as exc:
                errors.append(f"**{name}** — {exc}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"**{name}** — unexpected error: {exc}")
    st.session_state.statements = statements
    st.session_state.parse_errors = errors

for err in st.session_state.parse_errors:
    st.sidebar.error(err)

# ----------------------------------------------------------------------------
# Sidebar — 2. Personal finance sheet (optional)
# ----------------------------------------------------------------------------
st.sidebar.header("2 · Personal finance sheet")
sheet_file = st.sidebar.file_uploader(
    "Investments.xlsx export (optional)",
    type=["xlsx"],
    help=(
        "Download your personal tracking sheet from Google Drive as .xlsx and upload it here. "
        "'Trading Schemes' and 'Savings_Schemes' tabs are never read. See README.md for details."
    ),
)
if sheet_file is not None:
    try:
        st.session_state.sheet_data = load_personal_sheet(sheet_file.getvalue())
        st.session_state.sheet_error = None
    except Exception as exc:  # noqa: BLE001
        st.session_state.sheet_data = None
        st.session_state.sheet_error = f"Couldn't parse this sheet: {exc}"
if st.session_state.sheet_error:
    st.sidebar.error(st.session_state.sheet_error)
elif st.session_state.sheet_data is not None:
    sd: PersonalFinanceData = st.session_state.sheet_data
    st.sidebar.caption(f"Loaded {len(sd.sheets_found)} tabs, skipped: {', '.join(sd.skipped_sheets) or 'none'}")

# ----------------------------------------------------------------------------
# Sidebar — 3. INDmoney portfolio (optional)
# ----------------------------------------------------------------------------
st.sidebar.header("3 · INDmoney portfolio")
indmoney_file = st.sidebar.file_uploader(
    "Portfolio snapshot JSON (optional)",
    type=["json"],
    help="See README.md > 'INDmoney portfolio' for the export prompt that generates this file.",
)
if indmoney_file is not None:
    try:
        st.session_state.portfolio = load_indmoney_snapshot(indmoney_file.getvalue())
        st.session_state.portfolio_error = None
    except Exception as exc:  # noqa: BLE001
        st.session_state.portfolio = None
        st.session_state.portfolio_error = f"Couldn't parse this snapshot: {exc}"
if st.session_state.portfolio_error:
    st.sidebar.error(st.session_state.portfolio_error)
elif st.session_state.portfolio is not None:
    st.sidebar.caption(f"Snapshot from {st.session_state.portfolio.exported_at or 'unknown time'}")

# ----------------------------------------------------------------------------
# Sidebar — 4. Categorization rules
# ----------------------------------------------------------------------------
st.sidebar.header("4 · Categorization rules")
with st.sidebar.expander("Edit rules (YAML)"):
    st.caption(
        "First matching rule wins, top to bottom. Add merchants, family members, or "
        "categories here — no code changes needed."
    )
    edited_rules = st.text_area(
        "rules_yaml", value=st.session_state.rules_yaml, height=280, label_visibility="collapsed"
    )
    c1, c2 = st.columns(2)
    if c1.button("Apply rules"):
        err = validate_rules_yaml(edited_rules)
        if err:
            st.error(err)
        else:
            st.session_state.rules_yaml = edited_rules
            st.rerun()
    if c2.button("Reset to default"):
        st.session_state.rules_yaml = load_default_rules()
        st.rerun()

# ----------------------------------------------------------------------------
# Sidebar — 5. LLM (optional)
# ----------------------------------------------------------------------------
st.sidebar.header("5 · Ask AI (optional)")
provider = st.sidebar.radio("Model", ["None", "Claude API", "Local model"], index=0)

llm_client = None
llm_config_error = None
if provider == "Claude API":
    api_key = st.sidebar.text_input(
        "Anthropic API key", type="password", value=os.environ.get("ANTHROPIC_API_KEY", "")
    )
    model = st.sidebar.text_input(
        "Model", value=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        help="See README.md for how to find the current model name for your API access.",
    )
    if api_key and model:
        try:
            llm_client = build_client("claude", api_key=api_key, model=model)
        except LLMError as exc:
            llm_config_error = str(exc)

elif provider == "Local model":
    base_url = st.sidebar.text_input(
        "Base URL", value=os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"),
        help="Ollama: http://localhost:11434/v1 · LM Studio: http://localhost:1234/v1",
    )
    model = st.sidebar.text_input("Model name", value=os.environ.get("LOCAL_LLM_MODEL", "llama3.1"))
    if base_url and model:
        try:
            llm_client = build_client("local", base_url=base_url, model=model)
        except LLMError as exc:
            llm_config_error = str(exc)

if llm_config_error:
    st.sidebar.error(llm_config_error)

# ----------------------------------------------------------------------------
# Build combined state
# ----------------------------------------------------------------------------
df = transactions_to_dataframe(st.session_state.statements)
if not df.empty:
    rules = parse_rules(st.session_state.rules_yaml)
    df = categorize_dataframe(df, rules)
    if st.session_state.detect_transfers:
        df = detect_self_transfers(df)

sheet: PersonalFinanceData | None = st.session_state.sheet_data
portfolio = st.session_state.portfolio
ctx = AppContext(transactions=df, sheet=sheet, portfolio=portfolio)

# ----------------------------------------------------------------------------
# Main area
# ----------------------------------------------------------------------------
st.title("🏦 Financial Statement Analyser")

if df.empty and sheet is None and portfolio is None:
    st.info(
        "Upload at least one data source in the sidebar to get started: bank statement PDFs "
        "(HDFC, ICICI, Kotak, SBI, DBS, or similar), your personal finance sheet, or an "
        "INDmoney portfolio snapshot."
    )
    st.stop()

tab_dash, tab_networth, tab_invest, tab_budget, tab_data, tab_chat, tab_debug = st.tabs(
    ["📊 Dashboard", "🏠 Net Worth", "📈 Investments & SIPs", "🎯 Budget vs Actual", "📄 Raw Data", "💬 Ask AI", "🔍 Parsing Details"]
)

# ---- Dashboard (bank statements) -------------------------------------------
with tab_dash:
    if df.empty:
        st.info("Upload and parse bank statements (sidebar, section 1) to see this dashboard.")
    else:
        stats = headline_stats(df)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Income", f"₹{stats['income']:,.0f}")
        c2.metric("Total Expense", f"₹{stats['expense']:,.0f}")
        c3.metric("Net", f"₹{stats['net']:,.0f}")
        c4.metric("Savings Rate", f"{stats['savings_rate']:.1f}%")

        internal = df[df["category"] == INTERNAL_TRANSFER]
        if not internal.empty:
            st.caption(
                f"Excludes {len(internal)} transactions (₹{internal['amount'].abs().sum():,.0f}) "
                "flagged as transfers between your own accounts. See Raw Data to review them."
            )

        col1, col2 = st.columns(2)
        with col1:
            st.plotly_chart(income_bar(category_summary(df, "credit")), use_container_width=True)
        with col2:
            st.plotly_chart(expense_bar(category_summary(df, "debit")), use_container_width=True)

        st.plotly_chart(monthly_trend_chart(monthly_summary(df)), use_container_width=True)
        st.plotly_chart(balance_chart(df), use_container_width=True)

# ---- Net Worth ---------------------------------------------------------
with tab_networth:
    if portfolio is None and sheet is None and df.empty:
        st.info("Load an INDmoney snapshot, a personal finance sheet, or bank statements (sidebar) to see net worth.")
    else:
        if portfolio is not None:
            st.subheader("INDmoney portfolio")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Invested", f"₹{portfolio.total_invested:,.0f}")
            c2.metric("Current Value", f"₹{portfolio.total_current_value:,.0f}")
            c3.metric("Net Worth", f"₹{portfolio.total_networth:,.0f}")
            c4.metric("Liabilities", f"₹{portfolio.liabilities_total:,.0f}")
            st.caption(f"Snapshot from {portfolio.exported_at or 'unknown time'} — see README to refresh.")

            st.plotly_chart(
                assets_vs_liabilities_bar(portfolio.total_current_value, portfolio.liabilities_total),
                use_container_width=True,
            )

            col1, col2 = st.columns(2)
            with col1:
                if not portfolio.by_asset_class.empty:
                    d = portfolio.by_asset_class.rename(columns={"assetclass_l2": "label", "current_value": "value"})
                    st.plotly_chart(labeled_bar(d, "label", "value", "#1baf7a", "By asset class"), use_container_width=True)
            with col2:
                if not portfolio.by_market_cap.empty:
                    d = portfolio.by_market_cap.rename(columns={"market_cap": "label", "current_value": "value"})
                    st.plotly_chart(labeled_bar(d, "label", "value", "#e87ba4", "By market cap"), use_container_width=True)

            if not portfolio.by_sector.empty:
                d = portfolio.by_sector.rename(columns={"sector": "label", "current_value": "value"}).nlargest(12, "value")
                st.plotly_chart(labeled_bar(d, "label", "value", "#4a3aa7", "By sector (top 12)"), use_container_width=True)

            if not portfolio.loans.empty:
                st.markdown("**Loans**")
                st.dataframe(portfolio.loans, use_container_width=True, hide_index=True)
            if not portfolio.credit_cards.empty:
                st.markdown("**Credit cards**")
                st.dataframe(portfolio.credit_cards, use_container_width=True, hide_index=True)
        else:
            st.info("No INDmoney snapshot loaded — upload one (sidebar, section 3) for a full net worth view.")

        if sheet is not None and sheet.investments:
            st.divider()
            st.subheader("Personal finance sheet — manually tracked")
            st.caption(
                "From your tracking sheet, not INDmoney — may overlap with the portfolio above "
                "for anything you also link there (e.g. mutual funds)."
            )
            totals = section_totals(sheet.investments)
            c1, c2, c3 = st.columns(3)
            surplus = sheet.savings_summary.get("total_surplus")
            c1.metric("Sheet's own 'Total Surplus'", f"₹{surplus:,.0f}" if surplus is not None else "—")
            assets_sections = {"Mutual Funds", "Fixed Deposits", "Recurring Deposits", "Savings", "Others", "Provident Fund", "Fixed Assets"}
            sheet_assets = totals[totals["section"].isin(assets_sections)]["total"].sum()
            sheet_liabilities = totals[totals["section"] == "Liabilities"]["total"].sum()
            c2.metric("Sheet assets total", f"₹{sheet_assets:,.0f}")
            c3.metric("Sheet liabilities total", f"₹{sheet_liabilities:,.0f}")

            st.plotly_chart(
                labeled_bar(totals.rename(columns={"section": "label", "total": "value"}), "label", "value", "#eda100", "By section"),
                use_container_width=True,
            )

            devika = sheet.savings_summary.get("devika_equity") or {}
            if devika:
                st.markdown("**Devika's equity share (from sheet)**")
                st.dataframe(pd.DataFrame(list(devika.items()), columns=["Property", "Amount"]), use_container_width=True, hide_index=True)

            with st.expander("Full item-level detail"):
                st.dataframe(investment_items_to_frame(sheet.investments), use_container_width=True, hide_index=True)

        if not df.empty:
            st.divider()
            st.subheader("Cash — latest balance per bank account")
            latest = df.sort_values("date").groupby("account").tail(1)[["bank", "account", "balance", "date"]]
            st.dataframe(latest, use_container_width=True, hide_index=True)

# ---- Investments & SIPs -----------------------------------------------
with tab_invest:
    if portfolio is None:
        st.info("Upload an INDmoney portfolio snapshot (sidebar, section 3) to see this tab.")
    else:
        if not portfolio.mf_sips.empty:
            st.subheader("Active SIPs")
            st.metric("Total monthly SIP commitment", f"₹{portfolio.total_mf_sip_monthly:,.0f}")
            st.dataframe(
                portfolio.mf_sips[["fund_name", "category", "sip_amount", "sip_frequency", "sip_start_date", "is_step_up", "current_value", "gain_pct"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No active SIPs in this snapshot.")

        st.divider()
        st.subheader("Holdings by asset type")
        asset_types = sorted(portfolio.holdings.keys())
        if not asset_types:
            st.caption("No row-level holdings in this snapshot.")
        else:
            chosen = st.selectbox("Asset type", asset_types)
            hd = portfolio.holdings[chosen]
            if "market_value" in hd.columns and "investment" in hd.columns:
                top = hd.nlargest(15, "market_value")[["investment", "market_value"]].rename(columns={"investment": "label", "market_value": "value"})
                st.plotly_chart(labeled_bar(top, "label", "value", "#2a78d6", f"{chosen} — top holdings by value"), use_container_width=True)
            st.dataframe(hd, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Returns by asset type")
        if not portfolio.by_asset_type.empty:
            st.dataframe(
                portfolio.by_asset_type[["asset_type", "invested_value", "current_value", "return", "return_percentage"]].round(2),
                use_container_width=True,
                hide_index=True,
            )

# ---- Budget vs Actual ---------------------------------------------------
with tab_budget:
    if sheet is None or sheet.budget.empty:
        st.info("Upload a personal finance sheet with a budget tab (sidebar, section 2) to see this.")
    elif df.empty:
        st.info("Also upload and parse bank statements (sidebar, section 1) to compare against actual spend.")
    else:
        compare = build_budget_vs_actual(sheet.budget, df)
        if compare.empty:
            st.caption("No budget categories matched a bank-statement category — check BUDGET_TO_SPEND_CATEGORY in src/budget_compare.py.")
        else:
            st.plotly_chart(budget_vs_actual_bar(compare), use_container_width=True)
            compare["diff"] = compare["actual"] - compare["planned"]
            st.dataframe(compare.round(2), use_container_width=True, hide_index=True)

        with st.expander("Full monthly budget (from sheet)"):
            st.dataframe(sheet.budget, use_container_width=True, hide_index=True)

    if sheet is not None and not sheet.nirman_schedule.empty:
        st.divider()
        st.subheader("Property loan EMI schedule")
        st.plotly_chart(emi_schedule_chart(sheet.nirman_schedule), use_container_width=True)
        if sheet.nirman_summary:
            cols = st.columns(len(sheet.nirman_summary))
            for col, (k, v) in zip(cols, sheet.nirman_summary.items()):
                col.metric(k, f"₹{v:,.0f}")

# ---- Raw Data -----------------------------------------------------------
with tab_data:
    if df.empty:
        st.info("Upload and parse bank statements (sidebar, section 1) to see this table.")
    else:
        st.subheader("All transactions")
        f1, f2, f3, f4 = st.columns(4)
        banks = sorted(df["bank"].dropna().unique())
        bank_filter = f1.multiselect("Bank", banks, default=banks)
        cats = sorted(df["category"].dropna().unique())
        cat_filter = f2.multiselect("Category", cats, default=cats)
        dir_filter = f3.multiselect("Direction", ["credit", "debit"], default=["credit", "debit"])
        search = f4.text_input("Search narration")

        filtered = df[
            df["bank"].isin(bank_filter) & df["category"].isin(cat_filter) & df["direction"].isin(dir_filter)
        ]
        if search:
            filtered = filtered[filtered["narration"].str.contains(search, case=False, na=False)]

        low_conf_only = st.checkbox("Show only low-confidence rows (worth a manual check)", value=False)
        if low_conf_only:
            filtered = filtered[filtered["confidence"] < 0.9]

        st.dataframe(
            filtered[
                ["date", "narration", "category", "direction", "debit", "credit", "balance", "bank", "account", "confidence"]
            ],
            use_container_width=True,
            height=520,
        )
        st.download_button(
            "Download filtered data as CSV",
            filtered.to_csv(index=False).encode("utf-8"),
            "transactions.csv",
            "text/csv",
        )

# ---- Ask AI ---------------------------------------------------------------
with tab_chat:
    st.subheader("Ask questions about your finances")
    if llm_client is None:
        st.warning(
            "Configure an LLM in the sidebar (Claude API or a local model) to enable this. "
            "See README.md for setup instructions."
        )
    else:
        loaded = []
        if not df.empty:
            loaded.append("bank statements")
        if sheet is not None:
            loaded.append("personal sheet")
        if portfolio is not None:
            loaded.append("INDmoney portfolio")
        st.caption(f"Loaded: {', '.join(loaded) or 'nothing yet'}")

        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        question = st.chat_input("e.g. How much did I spend on food delivery last month?")
        if question:
            st.session_state.chat_history.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    try:
                        answer = llm_client.ask(question, ctx, st.session_state.chat_history[:-1])
                    except LLMError as exc:
                        answer = f"⚠️ {exc}"
                st.markdown(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})

        if st.session_state.chat_history and st.button("Clear conversation"):
            st.session_state.chat_history = []
            st.rerun()

# ---- Parsing Details ------------------------------------------------------
with tab_debug:
    st.subheader("Bank statement parsing details")
    st.caption(
        "Every statement's running balance is reconciled against its own printed closing "
        "balance. A clean reconciliation is a strong signal the parse is trustworthy; a "
        "drift means some rows were assigned by best-fit guessing — check them below."
    )
    if not st.session_state.statements:
        st.info("No statements parsed yet.")
    for stmt in st.session_state.statements:
        st.markdown(
            f"**{stmt.source_file}** — {stmt.bank}"
            + (f", account `{stmt.account_number}`" if stmt.account_number else "")
            + f" · parser: `{stmt.parser_used}` · {len(stmt.transactions)} transactions"
        )
        if stmt.parse_warnings:
            for w in stmt.parse_warnings:
                st.warning(w)
        else:
            st.success("Parsed cleanly — running balance reconciles with the statement.")
        cols = st.columns(3)
        cols[0].metric("Opening balance", f"₹{stmt.opening_balance:,.2f}" if stmt.opening_balance is not None else "—")
        cols[1].metric("Closing balance", f"₹{stmt.closing_balance:,.2f}" if stmt.closing_balance is not None else "—")
        err = stmt.reconciliation_error
        cols[2].metric("Reconciliation drift", f"₹{err:,.2f}" if err is not None else "—")
        st.divider()

    if st.session_state.sheet_data is not None:
        st.subheader("Personal sheet parsing details")
        sd = st.session_state.sheet_data
        st.caption(f"Tabs found: {', '.join(sd.sheets_found)}")
        st.caption(f"Tabs skipped (never opened): {', '.join(sd.skipped_sheets) or 'none'}")
        st.caption(f"Investment line items parsed: {len(sd.investments)} · Budget rows: {len(sd.budget)} · Nirman EMI rows: {len(sd.nirman_schedule)}")

st.caption(
    "Parsing and categorization happen entirely on this machine. If you use Claude API in "
    "the Ask AI tab, the tool-call *results* (category totals, matching transaction rows, "
    "portfolio/sheet figures) are sent to Anthropic's API to generate the answer — never the "
    "raw PDF, sheet, or JSON files themselves. Use a local model instead if you'd rather "
    "nothing leaves this machine. The INDmoney snapshot and personal sheet are periodic "
    "manual exports, not live connections — see README.md to refresh them."
)
