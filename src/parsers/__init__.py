"""Parsing entry point: `parse_statement()` is the one function the rest of
the app calls. It detects the bank, tries a structured table extraction
first, and falls back to a bank-agnostic line/regex engine (reconciled
against the printed running balance) when the PDF has no real table
structure — which is the common case for Indian bank statements that are
print-formatted rather than tagged as tables."""
from __future__ import annotations

from typing import Optional

import pdfplumber

from ..bank_detect import detect_bank
from ..models import Statement
from .profiles import get_profile
from .table_engine import parse_tables
from .line_engine import parse_lines


def parse_statement(
    pdf: pdfplumber.PDF,
    full_text: str,
    source_file: str,
    bank_hint: Optional[str] = None,
    manual_opening_balance: Optional[float] = None,
) -> Statement:
    if bank_hint:
        bank = bank_hint
    else:
        # Detect from the first page only: it's dominated by the issuing
        # bank's own letterhead/branch/IFSC block. Scanning the *whole*
        # document is unreliable — a year of transactions routinely mentions
        # other banks (transfers, IFSC codes in narrations) more often than
        # the statement's own letterhead repeats, which can outvote the
        # correct answer.
        try:
            header_text = pdf.pages[0].extract_text(x_tolerance=1) or ""
        except Exception:
            header_text = ""
        bank = detect_bank(header_text)
        if bank == "GENERIC":
            bank = detect_bank(full_text)
    profile = get_profile(bank)

    stmt: Optional[Statement] = None

    # 1) Try pdfplumber's structured table extraction — most reliable when it works.
    try:
        stmt = parse_tables(pdf, profile, source_file)
    except Exception as exc:  # noqa: BLE001 - we want to fall back, not crash
        stmt = None
        table_error = str(exc)
    else:
        table_error = None

    if stmt is None or len(stmt.transactions) < 3:
        # 2) Fall back to the line-based engine on the layout-preserving text.
        line_stmt = parse_lines(
            full_text, profile, source_file, manual_opening_balance, num_pages=len(pdf.pages)
        )
        if stmt is None:
            stmt = line_stmt
        elif len(line_stmt.transactions) > len(stmt.transactions):
            stmt = line_stmt
        if table_error:
            stmt.parse_warnings.append(f"Table extraction failed ({table_error}); used text-based parsing instead.")

    stmt.bank = bank
    stmt.parser_used = stmt.parser_used or "unknown"
    stmt.source_file = source_file

    err = stmt.reconciliation_error
    if err is not None and abs(err) > 1.0:
        stmt.parse_warnings.append(
            f"Running balance drifts by ₹{abs(err):,.2f} from the statement's printed closing "
            "balance — some rows may be mis-parsed. Check the raw table below before trusting totals."
        )

    account_label = stmt.account_number or source_file
    for t in stmt.transactions:
        t.source_bank = bank
        t.source_account = account_label
        t.source_file = source_file

    return stmt
