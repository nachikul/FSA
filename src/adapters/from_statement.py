"""Statement -> UnifiedRecord.

One record per statement (per account), representing that account's
closing cash balance — not one record per transaction. For net-worth and
allocation purposes "how much cash is in this account" is the useful
unit; individual transactions stay exactly as they are today (Dashboard,
Raw Data, and Parsing Details all keep reading Statement/Transaction
directly, unchanged by this module).
"""
from __future__ import annotations

from ..core.unified import AssetClass, SourceSystem, UnifiedRecord, make_record_id
from ..models import Statement


def from_statement(stmt: Statement) -> list[UnifiedRecord]:
    if stmt.closing_balance is None:
        # No printed closing balance to anchor a value on — rather than
        # guess from the last transaction's running balance (which may
        # itself be a low-confidence parse), skip; the Dashboard/Raw Data
        # tabs still show this statement's transactions untouched.
        return []

    account = stmt.account_number or stmt.source_file
    identifier = stmt.account_number or stmt.source_file

    return [
        UnifiedRecord(
            record_id=make_record_id(SourceSystem.BANK_STATEMENT, account, identifier, AssetClass.BANK_CASH),
            asset_class=AssetClass.BANK_CASH,
            source_system=SourceSystem.BANK_STATEMENT,
            identifier=identifier,
            identifier_type="account_no" if stmt.account_number else "source_file",
            name=f"{stmt.bank} — {account}",
            quantity=1.0,
            current_value=stmt.closing_balance,
            account_name=account,
            as_of_date=stmt.period_end,
            extra={"bank": stmt.bank, "source_file": stmt.source_file},
        )
    ]
