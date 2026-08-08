"""Parser for an INDmoney portfolio snapshot.

This is a periodic manual export, not a live API integration — the
INDmoney MCP connector this data comes from is only available inside a
Claude conversation, not to this standalone app. See README.md >
"INDmoney portfolio" for the exact prompt to regenerate a snapshot file
when you want fresher numbers; upload the resulting JSON the same way you
upload a bank statement.

Expected JSON shape (what that export prompt produces):

    {
      "exported_at": "<ISO8601 timestamp>",
      "networth_snapshot": { ...raw result of the networth_snapshot tool... },
      "holdings": { "<ASSET_TYPE>": [ ...raw rows from networth_holdings... ], ... },
      "sips": { "mf": [...raw rows from mf_sips...], "stocks": [...] }
    }

Any of these top-level keys may be absent (e.g. no SIPs) — everything
downstream degrades to an empty DataFrame rather than erroring.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class IndmoneyPortfolio:
    exported_at: Optional[str] = None
    total_invested: float = 0.0
    total_current_value: float = 0.0
    total_networth: float = 0.0
    by_asset_type: pd.DataFrame = field(default_factory=pd.DataFrame)   # networth_snapshot["investments"]
    by_asset_class: pd.DataFrame = field(default_factory=pd.DataFrame)  # networth_snapshot["assets"]
    by_sector: pd.DataFrame = field(default_factory=pd.DataFrame)
    by_market_cap: pd.DataFrame = field(default_factory=pd.DataFrame)
    liabilities_total: float = 0.0
    loans: pd.DataFrame = field(default_factory=pd.DataFrame)
    credit_cards: pd.DataFrame = field(default_factory=pd.DataFrame)
    holdings: dict[str, pd.DataFrame] = field(default_factory=dict)  # row-level, keyed by asset type
    mf_sips: pd.DataFrame = field(default_factory=pd.DataFrame)
    stock_sips: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def total_mf_sip_monthly(self) -> float:
        if self.mf_sips.empty or "sip_amount" not in self.mf_sips:
            return 0.0
        monthly = self.mf_sips[self.mf_sips["sip_frequency"].fillna("MONTHLY") == "MONTHLY"]
        return float(monthly["sip_amount"].sum())


def _flatten_mf_sips(mf_sips_raw: list[dict]) -> pd.DataFrame:
    """Each fund can carry several active_sips entries (different folios,
    step-ups over time, etc.) — flatten to one row per SIP installment so
    the total monthly SIP commitment is a simple column sum."""
    rows = []
    for fund in mf_sips_raw:
        sips = fund.get("active_sips") or [{}]
        for sip in sips:
            rows.append(
                {
                    "fund_name": fund.get("name"),
                    "category": fund.get("category"),
                    "risk": fund.get("risk"),
                    "current_value": fund.get("currentValueVal"),
                    "invested_amount": fund.get("investedAmountVal"),
                    "gain_pct": fund.get("gainPercentageVal"),
                    "sip_amount": sip.get("amount", 0) or 0,
                    "sip_frequency": sip.get("sip_frequency"),
                    "sip_start_date": sip.get("sip_start_date"),
                    "is_step_up": sip.get("is_step_up_sip", False),
                    "step_up_by": sip.get("step_up_by"),
                }
            )
    return pd.DataFrame(rows)


def load_indmoney_snapshot(file_bytes: bytes) -> IndmoneyPortfolio:
    data = json.loads(file_bytes)
    snap = data.get("networth_snapshot", {})

    p = IndmoneyPortfolio(
        exported_at=data.get("exported_at"),
        total_invested=snap.get("total_invested", 0.0),
        total_current_value=snap.get("total_current_value", 0.0),
        total_networth=snap.get("total_networth", 0.0),
    )
    p.by_asset_type = pd.DataFrame(snap.get("investments", []))
    p.by_asset_class = pd.DataFrame(snap.get("assets", []))
    p.by_sector = pd.DataFrame(snap.get("sector", []))
    p.by_market_cap = pd.DataFrame(snap.get("market_cap", []))

    liab = snap.get("liabilities", {})
    p.liabilities_total = liab.get("total", 0.0)
    p.loans = pd.DataFrame(liab.get("loans", []))
    p.credit_cards = pd.DataFrame(liab.get("credit_cards", []))

    for asset_type, rows in (data.get("holdings") or {}).items():
        if rows:
            p.holdings[asset_type] = pd.DataFrame(rows)

    sips = data.get("sips", {})
    p.mf_sips = _flatten_mf_sips(sips.get("mf", []))
    p.stock_sips = pd.DataFrame(sips.get("stocks", []))

    return p


def all_holdings_frame(portfolio: IndmoneyPortfolio) -> pd.DataFrame:
    """Every row-level holding across all asset types in one table, tagged
    with which asset-type key it came from (the raw `asset_type` field
    inside a row is sometimes a slightly different label, e.g. 'STOCK'
    for rows fetched under the 'IND_STOCK' query key)."""
    frames = []
    for asset_type, df in portfolio.holdings.items():
        if df.empty:
            continue
        d = df.copy()
        d["asset_type_key"] = asset_type
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)
