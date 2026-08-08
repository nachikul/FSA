"""Tool (function-calling) definitions the LLM can use to query the parsed
transaction data, plus the executor that actually runs them against the
pandas DataFrame. Grounding the model in real query results — instead of
just pasting the whole statement into the prompt — is what keeps its
answers accurate on datasets too large to fit in context and stops it from
guessing numbers.

Schemas are written once in Anthropic's tool format and adapted to the
OpenAI function-calling shape in openai_compatible.py, since the two are a
one-line transform of each other.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import pandas as pd

from ..analysis import INTERNAL_TRANSFER, category_summary, headline_stats, monthly_summary

TOOLS: list[dict] = [
    {
        "name": "get_summary",
        "description": (
            "Get headline numbers for the whole loaded dataset: total income, total expense, "
            "net (income minus expense), savings rate, transaction count, date range, and which "
            "banks/accounts are included. Call this first for any broad question."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_category_breakdown",
        "description": "Get spending or income broken down by category, sorted by amount descending.",
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
        "description": "Get income, expense and net for each calendar month present in the data.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_transactions",
        "description": (
            "Search individual transactions with optional filters. Always returns the TOTAL count "
            "and TOTAL amount across all matches (not just the sample rows), so you can answer "
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
        "description": "List every distinct category name currently in the data, so you can pick exact names to pass to other tools.",
        "input_schema": {"type": "object", "properties": {}},
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


def execute_tool(name: str, tool_input: dict[str, Any], df: pd.DataFrame) -> str:
    """Run a tool call and return a JSON string result (what gets sent back
    to the model as the tool result)."""
    if df.empty:
        return json.dumps({"error": "No transactions loaded yet."})

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
        summary = category_summary(df, direction)
        result = summary.round(2).to_dict(orient="records")

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

    else:
        result = {"error": f"Unknown tool '{name}'"}

    return json.dumps(result, default=str)
