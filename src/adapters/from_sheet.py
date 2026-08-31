"""InvestmentItem (personal finance sheet, Investments tab) -> UnifiedRecord.

Section names come straight from src/sources/personal_sheet.py's
SECTION_HEADERS — if you rename or add a section there, add it to the
mapping below too, otherwise new items fall into OTHER rather than
erroring (matching that module's general "degrade gracefully, never
crash on an unexpected sheet layout" posture).
"""
from __future__ import annotations

from ..core.unified import AssetClass, SourceSystem, UnifiedRecord, make_record_id
from ..sources.personal_sheet import InvestmentItem

ACCOUNT_NAME = "Personal Sheet"

_SECTION_TO_ASSET_CLASS: dict[str, AssetClass] = {
    "Mutual Funds": AssetClass.MUTUAL_FUND,
    "Fixed Deposits": AssetClass.FIXED_DEPOSIT,
    "Recurring Deposits": AssetClass.FIXED_DEPOSIT,
    "Savings": AssetClass.BANK_CASH,
    "Provident Fund": AssetClass.PROVIDENT_FUND,
    "Fixed Assets": AssetClass.OTHER,
    "Liabilities": AssetClass.LIABILITY,
    "Others": AssetClass.OTHER,
    "Other Income": AssetClass.OTHER,
}


def from_investment_items(items: list[InvestmentItem]) -> list[UnifiedRecord]:
    out: list[UnifiedRecord] = []
    for item in items:
        value = item.current_value if item.current_value is not None else item.amount
        if value is None:
            continue  # nothing to show a value for — skip rather than fabricate a zero

        asset_class = _SECTION_TO_ASSET_CLASS.get(item.section, AssetClass.OTHER)
        # `details` carries folio numbers / free-text notes where the sheet
        # has them; fall back to the item's own name when it doesn't, same
        # as investment_items_to_frame() already treats these columns.
        identifier = item.details or item.name

        out.append(
            UnifiedRecord(
                record_id=make_record_id(SourceSystem.PERSONAL_SHEET, ACCOUNT_NAME, f"{item.section}|{item.name}", asset_class),
                asset_class=asset_class,
                source_system=SourceSystem.PERSONAL_SHEET,
                identifier=identifier,
                identifier_type="folio" if item.details else "name",
                name=item.name,
                current_value=float(value),
                account_name=ACCOUNT_NAME,
                extra={"section": item.section, "subsection": item.subsection},
            )
        )
    return out
