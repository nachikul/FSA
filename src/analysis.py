"""Aggregations built on top of the categorized transaction DataFrame —
category/monthly summaries, headline stats, and a heuristic to flag likely
transfers between the user's own accounts (so multi-statement totals don't
double-count money just moving from one of their own accounts to another)."""
from __future__ import annotations

import pandas as pd

INTERNAL_TRANSFER = "Internal Transfer (own accounts)"


def headline_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"income": 0.0, "expense": 0.0, "net": 0.0, "savings_rate": 0.0, "n_txns": 0}
    spend_mask = df["category"] != INTERNAL_TRANSFER
    income = df.loc[spend_mask, "credit"].sum()
    expense = df.loc[spend_mask, "debit"].sum()
    net = income - expense
    savings_rate = (net / income * 100) if income else 0.0
    return {
        "income": float(income),
        "expense": float(expense),
        "net": float(net),
        "savings_rate": float(savings_rate),
        "n_txns": int(len(df)),
    }


def category_summary(df: pd.DataFrame, direction: str) -> pd.DataFrame:
    """direction: 'credit' or 'debit'. Excludes internal transfers."""
    if df.empty:
        return pd.DataFrame(columns=["category", "amount", "count"])
    sub = df[(df["direction"] == direction) & (df["category"] != INTERNAL_TRANSFER)]
    amount_col = "credit" if direction == "credit" else "debit"
    out = (
        sub.groupby("category")[amount_col]
        .agg(amount="sum", count="count")
        .reset_index()
        .sort_values("amount", ascending=False)
    )
    total = out["amount"].sum()
    out["pct"] = (out["amount"] / total * 100) if total else 0.0
    return out


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["month", "income", "expense", "net"])
    sub = df[df["category"] != INTERNAL_TRANSFER]
    out = sub.groupby("month").agg(income=("credit", "sum"), expense=("debit", "sum")).reset_index()
    out["net"] = out["income"] - out["expense"]
    return out.sort_values("month")


def detect_self_transfers(df: pd.DataFrame, amount_tolerance: float = 1.0, day_window: int = 3) -> pd.DataFrame:
    """Heuristic: a debit in one account and a credit in a *different*
    account/bank, for the same amount, within a few days of each other, is
    almost certainly the user moving their own money — not income or spend.
    Only applies across >=2 distinct (bank, account) pairs in the data."""
    if df.empty or df["account"].nunique() < 2:
        return df

    df = df.copy().reset_index(drop=True)
    debits = df[(df["direction"] == "debit") & (df["debit"] > 0)]
    credits = df[(df["direction"] == "credit") & (df["credit"] > 0)]

    matched_idx: set[int] = set()
    for d_idx, d_row in debits.iterrows():
        candidates = credits[
            (credits["account"] != d_row["account"])
            & (~credits.index.isin(matched_idx))
            & ((credits["credit"] - d_row["debit"]).abs() <= amount_tolerance)
            & ((credits["date"] - d_row["date"]).abs() <= pd.Timedelta(days=day_window))
        ]
        if not candidates.empty:
            c_idx = candidates.index[0]
            matched_idx.add(d_idx)
            matched_idx.add(c_idx)

    df.loc[list(matched_idx), "category"] = INTERNAL_TRANSFER
    return df
