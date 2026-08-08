"""Bank Statement Analyzer — Streamlit entry point.

Upload one or more bank statement PDFs (password-protected or not), get a
categorized income/spend dashboard, a filterable raw transaction table, and
an optional chat panel backed by Claude's API or a local model.
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
from src.categorize import categorize_dataframe, load_default_rules, parse_rules, validate_rules_yaml
from src.llm.chat import LLMError, build_client
from src.models import transactions_to_dataframe
from src.parsers import parse_statement
from src.pdf_utils import (
    PasswordRequiredError,
    PdfParseError,
    WrongPasswordError,
    full_text,
    open_pdf,
)
from src.ui.charts import balance_chart, expense_bar, income_bar, monthly_trend_chart

st.set_page_config(page_title="Bank Statement Analyzer", page_icon="🏦", layout="wide")

# ----------------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------------
defaults = {
    "statements": [],
    "parse_errors": [],
    "rules_yaml": load_default_rules(),
    "chat_history": [],
    "detect_transfers": True,
}
for key, val in defaults.items():
    st.session_state.setdefault(key, val)

# ----------------------------------------------------------------------------
# Sidebar — 1. Upload
# ----------------------------------------------------------------------------
st.sidebar.header("1 · Upload statements")
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
# Sidebar — 2. Categorization rules
# ----------------------------------------------------------------------------
st.sidebar.header("2 · Categorization rules")
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
# Sidebar — 3. LLM (optional)
# ----------------------------------------------------------------------------
st.sidebar.header("3 · Ask AI (optional)")
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
# Build the combined, categorized dataframe
# ----------------------------------------------------------------------------
df = transactions_to_dataframe(st.session_state.statements)
if not df.empty:
    rules = parse_rules(st.session_state.rules_yaml)
    df = categorize_dataframe(df, rules)
    if st.session_state.detect_transfers:
        df = detect_self_transfers(df)

# ----------------------------------------------------------------------------
# Main area
# ----------------------------------------------------------------------------
st.title("🏦 Bank Statement Analyzer")

if df.empty:
    st.info(
        "Upload one or more statement PDFs in the sidebar (HDFC, ICICI, Kotak, SBI, DBS, or "
        "anything with a similar layout) and click **Parse statements** to get started."
    )
    st.stop()

tab_dash, tab_data, tab_chat, tab_debug = st.tabs(
    ["📊 Dashboard", "📄 Raw Data", "💬 Ask AI", "🔍 Parsing Details"]
)

with tab_dash:
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

with tab_data:
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

with tab_chat:
    st.subheader("Ask questions about your finances")
    if llm_client is None:
        st.warning(
            "Configure an LLM in the sidebar (Claude API or a local model) to enable this. "
            "See README.md for setup instructions."
        )
    else:
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
                        answer = llm_client.ask(question, df, st.session_state.chat_history[:-1])
                    except LLMError as exc:
                        answer = f"⚠️ {exc}"
                st.markdown(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})

        if st.session_state.chat_history and st.button("Clear conversation"):
            st.session_state.chat_history = []
            st.rerun()

with tab_debug:
    st.subheader("Parsing details")
    st.caption(
        "Every statement's running balance is reconciled against its own printed closing "
        "balance. A clean reconciliation is a strong signal the parse is trustworthy; a "
        "drift means some rows were assigned by best-fit guessing — check them below."
    )
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

st.caption(
    "Parsing and categorization happen entirely on this machine. If you use Claude API in "
    "the Ask AI tab, the tool-call *results* (category totals, matching transaction rows) "
    "are sent to Anthropic's API to generate the answer — never the raw PDF. Use a local "
    "model instead if you'd rather nothing leaves this machine."
)
