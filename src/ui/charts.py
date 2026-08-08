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


def _empty(msg: str = "No data") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False)
    return fig


def _bar(df: pd.DataFrame, color: str, title: str) -> go.Figure:
    if df.empty:
        return _empty()
    return labeled_bar(df, "category", "amount", color, title)


def labeled_bar(df: pd.DataFrame, label_col: str, value_col: str, color: str, title: str) -> go.Figure:
    """Generic single-hue horizontal bar — one series, many categories,
    identity carried by the (always-visible) row label rather than color."""
    if df.empty:
        return _empty()
    df = df.sort_values(value_col, ascending=True)
    fig = px.bar(
        df,
        x=value_col,
        y=label_col,
        orientation="h",
        text=df[value_col].map(lambda v: f"₹{v:,.0f}"),
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
        return _empty()
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


def assets_vs_liabilities_bar(total_assets: float, total_liabilities: float) -> go.Figure:
    net = total_assets - total_liabilities
    fig = go.Figure(
        go.Bar(
            x=["Assets", "Liabilities", "Net Worth"],
            y=[total_assets, -total_liabilities, net],
            marker_color=[BLUE, ORANGE, AQUA],
            text=[f"₹{total_assets:,.0f}", f"-₹{total_liabilities:,.0f}", f"₹{net:,.0f}"],
            textposition="outside",
        )
    )
    fig.update_layout(
        template=TEMPLATE,
        title="Assets vs. liabilities",
        yaxis_title="Amount (₹)",
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False,
    )
    return fig


def emi_schedule_chart(schedule: pd.DataFrame) -> go.Figure:
    """Stacked bar: interest vs. principal per installment, over time."""
    if schedule.empty:
        return _empty()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=schedule["date"], y=schedule["interest"], name="Interest", marker_color=ORANGE))
    fig.add_trace(go.Bar(x=schedule["date"], y=schedule["principal"], name="Principal", marker_color=BLUE))
    fig.update_layout(
        barmode="stack",
        template=TEMPLATE,
        title="Loan EMI schedule — interest vs. principal",
        xaxis_title="",
        yaxis_title="Amount (₹)",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def budget_vs_actual_bar(compare: pd.DataFrame) -> go.Figure:
    """Grouped horizontal bar: planned (budget) vs. actual, per category."""
    if compare.empty:
        return _empty()
    compare = compare.sort_values("planned", ascending=True)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=compare["category"], x=compare["planned"], name="Planned (sheet)", orientation="h", marker_color=BLUE))
    fig.add_trace(go.Bar(y=compare["category"], x=compare["actual"], name="Actual (bank statements)", orientation="h", marker_color=ORANGE))
    fig.update_layout(
        barmode="group",
        template=TEMPLATE,
        title="Budget vs. actual, monthly average",
        xaxis_title="Amount (₹)",
        height=max(320, 40 * len(compare)),
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def balance_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty or "balance" not in df:
        return _empty()
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
