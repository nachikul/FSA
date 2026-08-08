"""Structured extraction for statements where the PDF actually has tagged
table structure (pdfplumber can find real cell boundaries). This is the
higher-confidence path when it applies — no reconciliation guesswork needed
since debit/credit/balance are already in separate cells."""
from __future__ import annotations

from datetime import date as Date
from typing import Optional

import pdfplumber

from ..models import Statement, Transaction
from .profiles import BankProfile
from .utils import clean_amount, try_parse_date


def _match_header(cell: Optional[str], words: list[str]) -> bool:
    if not cell:
        return False
    low = cell.strip().lower()
    return any(w in low for w in words)


def _find_header_row(table: list[list[Optional[str]]], profile: BankProfile) -> Optional[dict[str, int]]:
    for row in table[:3]:
        mapping: dict[str, int] = {}
        for role, words in profile.header_words.items():
            for i, cell in enumerate(row):
                if _match_header(cell, words):
                    mapping[role] = i
                    break
        if "date" in mapping and "balance" in mapping and ("debit" in mapping or "credit" in mapping):
            return mapping
    return None


def parse_tables(pdf: pdfplumber.PDF, profile: BankProfile, source_file: str) -> Optional[Statement]:
    all_rows: list[list[Optional[str]]] = []
    header_map: Optional[dict[str, int]] = None

    for page in pdf.pages:
        for table in page.extract_tables():
            if not table:
                continue
            if header_map is None:
                header_map = _find_header_row(table, profile)
                if header_map is None:
                    continue
            all_rows.extend(table)

    if header_map is None:
        return None

    stmt = Statement(bank=profile.name, source_file=source_file, parser_used="table_engine")
    running_balance: Optional[float] = None
    date_col = header_map["date"]
    narr_col = header_map.get("narration")
    debit_col = header_map.get("debit")
    credit_col = header_map.get("credit")
    bal_col = header_map.get("balance")
    ref_col = header_map.get("ref")

    for row in all_rows:
        if date_col >= len(row):
            continue
        d = try_parse_date((row[date_col] or "").strip(), profile.date_formats)
        if d is None:
            continue

        narration = (row[narr_col] or "").strip() if narr_col is not None and narr_col < len(row) else ""
        debit = clean_amount(row[debit_col]) if debit_col is not None and debit_col < len(row) else None
        credit = clean_amount(row[credit_col]) if credit_col is not None and credit_col < len(row) else None
        balance = clean_amount(row[bal_col]) if bal_col is not None and bal_col < len(row) else None
        ref = (row[ref_col] or "").strip() if ref_col is not None and ref_col < len(row) else None

        if debit is None and credit is None:
            continue

        if stmt.opening_balance is None and balance is not None:
            stmt.opening_balance = round(balance - (credit or 0) + (debit or 0), 2)
            running_balance = stmt.opening_balance

        if running_balance is not None:
            running_balance += (credit or 0) - (debit or 0)

        stmt.transactions.append(
            Transaction(
                date=d,
                narration=narration,
                debit=abs(debit) if debit else None,
                credit=abs(credit) if credit else None,
                balance=balance if balance is not None else running_balance,
                ref_no=ref,
                confidence=1.0,
            )
        )
        if balance is not None:
            stmt.closing_balance = balance

    return stmt if stmt.transactions else None
