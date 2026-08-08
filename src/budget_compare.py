"""Compares the personal sheet's monthly budget against actual spend
categorized from bank statements.

The mapping between the sheet's free-text budget line items and this app's
keyword-rule spend categories (see rules_default.yaml) is necessarily
approximate — the sheet uses personal shorthand ("House Fund", "ICICI Pru
Smart") that doesn't line up one-to-one with transaction-derived buckets.
Treat this as a starting point: edit BUDGET_TO_SPEND_CATEGORY to match your
own sheet's line items and your own category rules.
"""
from __future__ import annotations

import pandas as pd

from .analysis import INTERNAL_TRANSFER

BUDGET_TO_SPEND_CATEGORY: dict[str, str] = {
    "Mutual Funds": "Investments - Stocks / MF / SIP",
    "PPF": "Investments - Stocks / MF / SIP",
    "ICICI Pru Smart": "Insurance Premium",
    "House EMI": "Home Loan / Mortgage",
    "Other EMIs": "EMI / Loan Repayment",
    "Vehicle Maintenance": "Fuel",
    "Medical+Health": "Medical",
    "Travel Trips": "Travel",
    "Maids": "Utilities & Bills",
    "Car Wash": "Fuel",
    "Milk": "Groceries & Food Delivery",
    "Petrol": "Fuel",
    "Internet": "Utilities & Bills",
    "Netflix": "Subscriptions",
    "Zee5": "Subscriptions",
    "SonyLiv": "Subscriptions",
    "Prime": "Subscriptions",
    "Hotstar": "Subscriptions",
    "YouTube": "Subscriptions",
    "Spotify": "Subscriptions",
}


def build_budget_vs_actual(budget: pd.DataFrame, txn_df: pd.DataFrame) -> pd.DataFrame:
    """Returns a DataFrame with one row per mapped spend category:
    planned (monthly, from the sheet) vs. actual (average monthly spend,
    from categorized bank transactions over however many months of
    statement data are loaded)."""
    if budget.empty or txn_df.empty:
        return pd.DataFrame(columns=["category", "planned", "actual"])

    mapped = budget[budget["category"].isin(BUDGET_TO_SPEND_CATEGORY)].copy()
    if mapped.empty:
        return pd.DataFrame(columns=["category", "planned", "actual"])
    mapped["spend_category"] = mapped["category"].map(BUDGET_TO_SPEND_CATEGORY)
    planned = mapped.groupby("spend_category")["monthly_amount"].sum()

    spend = txn_df[(txn_df["direction"] == "debit") & (txn_df["category"] != INTERNAL_TRANSFER)]
    n_months = max(spend["month"].nunique(), 1) if not spend.empty else 1
    actual = spend.groupby("category")["debit"].sum() / n_months

    categories = sorted(set(planned.index) | set(actual.index))
    rows = [
        {"category": c, "planned": round(float(planned.get(c, 0.0)), 2), "actual": round(float(actual.get(c, 0.0)), 2)}
        for c in categories
    ]
    return pd.DataFrame(rows)
