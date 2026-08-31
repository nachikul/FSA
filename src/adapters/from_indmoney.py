"""IndmoneyPortfolio.holdings -> UnifiedRecord.

Row-level holdings come from raw INDmoney API responses (see
src/sources/indmoney.py's module docstring) with no fixed column schema
documented anywhere in this repo — app.py's existing Investments & SIPs
tab already leans on "investment" / "market_value" being present
(`hd.nlargest(15, "market_value")[["investment", "market_value"]]`), so
this adapter reads those plus a few common variants, and skips any row it
can't map rather than guessing. Treat this the way profiles.py treats the
untuned KOTAK/SBI/DBS bank profiles: a best-effort default to verify (and
extend the column-name lists below) once you run it against a real
snapshot or live-connect fetch.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..core.unified import AssetClass, SourceSystem, UnifiedRecord, make_record_id
from ..sources.indmoney import IndmoneyPortfolio

ACCOUNT_NAME = "INDmoney"

# Keyed by the asset_type string INDmoney's holdings dict is keyed by
# (see README > "3 · INDmoney portfolio" and app.py's asset_type selector:
# MF, IND_STOCK, US_STOCK, EPF, PPF, FD, RE are the ones known to occur).
_ASSET_TYPE_TO_CLASS: dict[str, AssetClass] = {
    "MF": AssetClass.MUTUAL_FUND,
    "IND_STOCK": AssetClass.EQUITY,
    "US_STOCK": AssetClass.EQUITY,
    "EPF": AssetClass.PROVIDENT_FUND,
    "PPF": AssetClass.PROVIDENT_FUND,
    "FD": AssetClass.FIXED_DEPOSIT,
    "RE": AssetClass.OTHER,
    "GOLD": AssetClass.GOLD,
    "SGB": AssetClass.GOLD,  # Sovereign Gold Bonds, if INDmoney surfaces them separately
}

_NAME_COLUMNS = ["investment", "name", "fund_name", "scheme_name", "symbol"]
_VALUE_COLUMNS = ["market_value", "current_value", "currentValueVal"]
_COST_COLUMNS = ["invested_amount", "invested_value", "investedAmountVal"]
_QTY_COLUMNS = ["units", "quantity", "qty"]
_ISIN_COLUMNS = ["isin", "ISIN"]


def _first_present(row: "pd.Series", candidates: list[str]) -> Optional[object]:
    for c in candidates:
        if c in row.index and pd.notna(row[c]):
            return row[c]
    return None


def from_indmoney(portfolio: IndmoneyPortfolio) -> list[UnifiedRecord]:
    out: list[UnifiedRecord] = []

    for asset_type, df in portfolio.holdings.items():
        if df is None or df.empty:
            continue
        asset_class = _ASSET_TYPE_TO_CLASS.get(asset_type.upper(), AssetClass.OTHER)

        for _, row in df.iterrows():
            name = _first_present(row, _NAME_COLUMNS)
            value = _first_present(row, _VALUE_COLUMNS)
            if name is None or value is None:
                continue  # can't build a usable record from this row — see module docstring

            isin = _first_present(row, _ISIN_COLUMNS)
            identifier = str(isin) if isin is not None else str(name)
            qty = _first_present(row, _QTY_COLUMNS)
            cost = _first_present(row, _COST_COLUMNS)

            out.append(
                UnifiedRecord(
                    record_id=make_record_id(SourceSystem.INDMONEY, ACCOUNT_NAME, identifier, asset_class),
                    asset_class=asset_class,
                    source_system=SourceSystem.INDMONEY,
                    identifier=identifier,
                    identifier_type="isin" if isin is not None else "name",
                    name=str(name),
                    quantity=float(qty) if qty is not None else 1.0,
                    cost_basis=float(cost) if cost is not None else None,
                    current_value=float(value),
                    account_name=ACCOUNT_NAME,
                    extra={"asset_type": asset_type},
                )
            )
    return out
