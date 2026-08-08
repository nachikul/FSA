"""Plotly figure builders. One hue per single-series chart (income OR
expense), the shared categorical order for multi-series charts — kept
consistent everywhere so the same account/series always gets the same
color."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
VIOLET = "#4a3aa7"
CATEGORICAL = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, VIOLET]

TEMPLATE = "plotly_white"


def _bar(df: pd.DataFrame, color: str, title: str) -> go.Figure:
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig
    df = df.sort_values("amount", ascending=True)
    fig = px.bar(
        df,
        x="amount",
        y="category",
        orientation="h",
        text=df["amount"].map(lambda v: f"₹{v:,.0f}"),
        template=TEMPLATE,
        title=title,
    )
    fig.update_traces(marker_color=color, textposition="outside", cliponaxis=False)
    fig.update_layout(
        xaxis_title="Amount (₹)",
        yaxis_title="",
        height=max(320, 34 * len(df)),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


def income_bar(summary: pd.DataFrame) -> go.Figure:
    return _bar(summary, BLUE, "Income by source")


def expense_bar(summary: pd.DataFrame) -> go.Figure:
    return _bar(summary, ORANGE, "Spend by category")


def monthly_trend_chart(monthly: pd.DataFrame) -> go.Figure:
    if monthly.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=monthly["month"], y=monthly["income"], name="Income", line=dict(color=BLUE, width=2), mode="lines+markers"))
    fig.add_trace(go.Scatter(x=monthly["month"], y=monthly["expense"], name="Expense", line=dict(color=ORANGE, width=2), mode="lines+markers"))
    fig.update_layout(
        template=TEMPLATE,
        title="Income vs. expense by month",
        xaxis_title="",
        yaxis_title="Amount (₹)",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def balance_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty or "balance" not in df:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig
    fig = go.Figure()
    accounts = sorted(df["account"].dropna().unique().tolist()) or ["(all)"]
    for i, acct in enumerate(accounts):
        sub = df[df["account"] == acct].sort_values("date") if acct != "(all)" else df.sort_values("date")
        color = CATEGORICAL[i % len(CATEGORICAL)]
        fig.add_trace(
            go.Scatter(x=sub["date"], y=sub["balance"], name=acct or "Account", line=dict(color=color, width=2))
        )
    fig.update_layout(
        template=TEMPLATE,
        title="Balance over time",
        xaxis_title="",
        yaxis_title="Balance (₹)",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig
