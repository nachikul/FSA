"""Core data structures shared across parsers, categorization, analysis and the UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from typing import Optional

import pandas as pd


@dataclass
class Transaction:
    date: Date
    narration: str
    debit: Optional[float] = None      # money out (withdrawal)
    credit: Optional[float] = None     # money in (deposit)
    balance: Optional[float] = None
    ref_no: Optional[str] = None
    category: Optional[str] = None
    source_bank: str = ""
    source_account: str = ""
    source_file: str = ""
    # 1.0 = clean parse reconciled against the running balance; lower values
    # flag rows the parser is less sure about (surfaced in the UI as a filter).
    confidence: float = 1.0

    @property
    def amount(self) -> float:
        """Signed amount: positive for credit, negative for debit."""
        if self.credit:
            return self.credit
        if self.debit:
            return -self.debit
        return 0.0

    @property
    def direction(self) -> str:
        return "credit" if self.credit else "debit"


@dataclass
class Statement:
    bank: str
    account_number: str = ""
    account_holder: str = ""
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    period_start: Optional[Date] = None
    period_end: Optional[Date] = None
    transactions: list[Transaction] = field(default_factory=list)
    source_file: str = ""
    parser_used: str = ""
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def reconciliation_error(self) -> Optional[float]:
        """Difference between the parser's own running balance and the
        statement's printed closing balance — near zero means a clean parse."""
        if self.opening_balance is None or self.closing_balance is None:
            return None
        computed = self.opening_balance
        for t in self.transactions:
            computed += t.amount
        return round(computed - self.closing_balance, 2)


def transactions_to_dataframe(statements: list[Statement]) -> pd.DataFrame:
    """Flatten one or more parsed statements into a single tidy DataFrame."""
    rows = []
    for stmt in statements:
        for t in stmt.transactions:
            rows.append(
                {
                    "date": t.date,
                    "narration": t.narration,
                    "debit": t.debit or 0.0,
                    "credit": t.credit or 0.0,
                    "amount": t.amount,
                    "balance": t.balance,
                    "direction": t.direction,
                    "category": t.category or "Uncategorized",
                    "bank": t.source_bank,
                    "account": t.source_account,
                    "source_file": t.source_file,
                    "confidence": t.confidence,
                }
            )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df["month"] = df["date"].dt.to_period("M").astype(str)
    return df
