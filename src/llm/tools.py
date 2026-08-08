"""Tool (function-calling) definitions the LLM can use to query the loaded
data, plus the executor that actually runs them. Grounding the model in
real query results — instead of just pasting everything into the prompt —
is what keeps its answers accurate on datasets too large to fit in context
and stops it from guessing numbers.

Covers three data sources, each optional and independently loaded:
- bank statement transactions (always available once parsed)
- the personal finance-tracking sheet (Investments / budget / Nirman EMI /
  savings-summary tabs)
- an INDmoney portfolio snapshot

Schemas are written once in Anthropic's tool format and adapted to the
OpenAI function-calling shape in openai_compatible.py, since the two are a
one-line transform of each other.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from ..analysis import INTERNAL_TRANSFER, category_summary, headline_stats, monthly_summary
from ..budget_compare import build_budget_vs_actual
from ..sources.personal_sheet import investment_items_to_frame, section_totals
from .context import AppContext

TOOLS: list[dict] = [
    {
        "name": "get_summary",
        "description": (
            "Get headline numbers for the loaded bank statement data: total income, total expense, "
            "net (income minus expense), savings rate, transaction count, date range, and which "
            "banks/accounts are included. Call this first for any broad bank-statement question."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_category_breakdown",
        "description": "Get bank-statement spending or income broken down by category, sorted by amount descending.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["credit", "debit"],
                    "description": "'credit' for income sources, 'debit' for spend categories.",
                }
            },
            "required": ["direction"],
        },
    },
    {
        "name": "get_monthly_trend",
        "description": "Get income, expense and net for each calendar month present in the bank statement data.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_transactions",
        "description": (
            "Search individual bank transactions with optional filters. Always returns the TOTAL "
            "count and TOTAL amount across all matches (not just the sample rows), so you can answer "
            "'how much' questions even if only a sample of rows is shown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Substring to search for in the transaction narration, case-insensitive."},
                "category": {"type": "string", "description": "Exact category name to filter by."},
                "direction": {"type": "string", "enum": ["credit", "debit"]},
                "bank": {"type": "string", "description": "Filter to one bank, e.g. HDFC, ICICI, KOTAK, SBI, DBS."},
                "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD, inclusive."},
                "end_date": {"type": "string", "description": "ISO date YYYY-MM-DD, inclusive."},
                "min_amount": {"type": "number"},
                "max_amount": {"type": "number"},
                "limit": {"type": "integer", "description": "Max sample rows to return (default 20, max 100)."},
            },
        },
    },
    {
        "name": "list_categories",
        "description": "List every distinct bank-statement category name currently in the data, so you can pick exact names to pass to other tools.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_networth_summary",
        "description": (
            "Get overall net worth: total invested, total current value, and total net worth from "
            "the INDmoney portfolio snapshot (if loaded), broken down by asset type, asset class, "
            "sector and market cap, plus loans and credit card dues. If a personal finance sheet is "
            "also loaded, includes its own section totals (mutual funds, FDs, savings, fixed assets, "
            "liabilities) as a supplementary manually-tracked view. Call this for any 'net worth', "
            "'total wealth', or 'what do I own vs owe' question."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_portfolio_holdings",
        "description": (
            "Get row-level INDmoney holdings for one asset type — fund/stock name, units, current "
            "value, invested amount, P&L, broker. Use for 'my mutual funds', 'my stocks', 'my EPF' "
            "type questions. Call list_categories-equivalent first if unsure which asset types are "
            "available: common ones are MF, IND_STOCK, US_STOCK, EPF, PPF, FD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"asset_type": {"type": "string", "description": "e.g. MF, IND_STOCK, US_STOCK, EPF, PPF, FD, RE"}},
            "required": ["asset_type"],
        },
    },
    {
        "name": "get_sip_summary",
        "description": "Get the user's active mutual fund SIPs from the INDmoney snapshot — fund name, monthly SIP amount, start date, step-ups — plus the total monthly SIP commitment across all funds.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_budget_vs_actual",
        "description": (
            "Compare the user's planned monthly budget (from their personal finance sheet) against "
            "their actual average monthly spend in each matched category (from categorized bank "
            "transactions). Use for 'am I overspending on X', 'how does my spending compare to my "
            "budget' type questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_sheet_section_detail",
        "description": (
            "Get the personal finance sheet's line items for one section of the Investments tab — "
            "e.g. every mutual fund, every fixed deposit, every loan, with amounts and details. Use "
            "when a net-worth question needs sheet-level itemized detail rather than just totals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "One of: Mutual Funds, Fixed Deposits, Recurring Deposits, Savings, Others, Provident Fund, Other Income, Fixed Assets, Liabilities.",
                }
            },
            "required": ["section"],
        },
    },
]


def _df_slice(df: pd.DataFrame, **filters) -> pd.DataFrame:
    out = df
    if filters.get("keyword"):
        out = out[out["narration"].str.contains(filters["keyword"], case=False, na=False)]
    if filters.get("category"):
        out = out[out["category"].str.lower() == filters["category"].lower()]
    if filters.get("direction"):
        out = out[out["direction"] == filters["direction"]]
    if filters.get("bank"):
        out = out[out["bank"].str.lower() == filters["bank"].lower()]
    if filters.get("start_date"):
        out = out[out["date"] >= pd.to_datetime(filters["start_date"])]
    if filters.get("end_date"):
        out = out[out["date"] <= pd.to_datetime(filters["end_date"])]
    if filters.get("min_amount") is not None:
        out = out[out["amount"].abs() >= filters["min_amount"]]
    if filters.get("max_amount") is not None:
        out = out[out["amount"].abs() <= filters["max_amount"]]
    return out


def execute_tool(name: str, tool_input: dict[str, Any], ctx: AppContext) -> str:
    """Run a tool call and return a JSON string result (what gets sent back
    to the model as the tool result)."""
    df = ctx.transactions

    bank_tools = {"get_summary", "get_category_breakdown", "get_monthly_trend", "search_transactions", "list_categories"}
    if name in bank_tools and (df is None or df.empty):
        return json.dumps({"error": "No bank statements loaded yet."})

    if name == "get_summary":
        stats = headline_stats(df)
        result = {
            **stats,
            "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
            "banks": sorted(df["bank"].dropna().unique().tolist()),
            "accounts": sorted(df["account"].dropna().unique().tolist()),
        }

    elif name == "get_category_breakdown":
        direction = tool_input.get("direction", "debit")
        result = category_summary(df, direction).round(2).to_dict(orient="records")

    elif name == "get_monthly_trend":
        result = monthly_summary(df).round(2).to_dict(orient="records")

    elif name == "list_categories":
        result = sorted(df["category"].dropna().unique().tolist())

    elif name == "search_transactions":
        filtered = _df_slice(df, **tool_input)
        limit = min(int(tool_input.get("limit", 20) or 20), 100)
        sample = filtered.sort_values("date", ascending=False).head(limit)
        result = {
            "total_matches": int(len(filtered)),
            "total_amount": round(float(filtered["amount"].sum()), 2),
            "total_debit": round(float(filtered["debit"].sum()), 2),
            "total_credit": round(float(filtered["credit"].sum()), 2),
            "sample_rows": [
                {
                    "date": str(r["date"].date()),
                    "narration": r["narration"][:140],
                    "amount": round(float(r["amount"]), 2),
                    "category": r["category"],
                    "bank": r["bank"],
                }
                for _, r in sample.iterrows()
            ],
        }

    elif name == "get_networth_summary":
        result: dict[str, Any] = {}
        p = ctx.portfolio
        if p is not None:
            result["indmoney"] = {
                "total_invested": round(p.total_invested, 2),
                "total_current_value": round(p.total_current_value, 2),
                "total_networth": round(p.total_networth, 2),
                "by_asset_type": p.by_asset_type.round(2).to_dict(orient="records") if not p.by_asset_type.empty else [],
                "by_sector": p.by_sector.round(2).to_dict(orient="records") if not p.by_sector.empty else [],
                "by_market_cap": p.by_market_cap.round(2).to_dict(orient="records") if not p.by_market_cap.empty else [],
                "liabilities_total": round(p.liabilities_total, 2),
                "loans": p.loans.to_dict(orient="records") if not p.loans.empty else [],
                "credit_cards": p.credit_cards.to_dict(orient="records") if not p.credit_cards.empty else [],
                "exported_at": p.exported_at,
            }
        else:
            result["indmoney"] = "No INDmoney snapshot loaded."
        s = ctx.sheet
        if s is not None and s.investments:
            result["personal_sheet"] = {
                "section_totals": section_totals(s.investments).round(2).to_dict(orient="records"),
                "total_surplus": s.savings_summary.get("total_surplus"),
                "devika_equity": s.savings_summary.get("devika_equity"),
            }
        else:
            result["personal_sheet"] = "No personal finance sheet loaded."
        if p is None and s is None:
            result["error"] = "Neither an INDmoney snapshot nor a personal finance sheet is loaded — net worth isn't available, only bank account balances (use search_transactions or ask about balance)."

    elif name == "get_portfolio_holdings":
        p = ctx.portfolio
        if p is None:
            result = {"error": "No INDmoney snapshot loaded."}
        else:
            asset_type = tool_input.get("asset_type", "")
            holdings = p.holdings.get(asset_type.upper())
            if holdings is None or holdings.empty:
                result = {"error": f"No holdings found for asset_type '{asset_type}'.", "available_types": list(p.holdings.keys())}
            else:
                result = holdings.round(2).to_dict(orient="records")

    elif name == "get_sip_summary":
        p = ctx.portfolio
        if p is None or p.mf_sips.empty:
            result = {"error": "No SIP data loaded (requires an INDmoney snapshot)."}
        else:
            result = {
                "total_monthly_sip": round(p.total_mf_sip_monthly, 2),
                "sips": p.mf_sips.round(2).to_dict(orient="records"),
            }

    elif name == "get_budget_vs_actual":
        s = ctx.sheet
        if s is None or s.budget.empty:
            result = {"error": "No personal finance sheet loaded, or it has no budget tab."}
        elif df is None or df.empty:
            result = {"error": "No bank statements loaded to compare actuals against."}
        else:
            result = build_budget_vs_actual(s.budget, df).round(2).to_dict(orient="records")

    elif name == "get_sheet_section_detail":
        s = ctx.sheet
        if s is None or not s.investments:
            result = {"error": "No personal finance sheet loaded."}
        else:
            section = tool_input.get("section", "")
            items = investment_items_to_frame(s.investments)
            matched = items[items["section"].str.lower() == section.lower()]
            if matched.empty:
                result = {"error": f"No section named '{section}'.", "available_sections": sorted(items["section"].unique().tolist())}
            else:
                result = json.loads(matched.to_json(orient="records"))  # NaN -> null, unlike .to_dict()

    else:
        result = {"error": f"Unknown tool '{name}'"}

    return json.dumps(result, default=str)
