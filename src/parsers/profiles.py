"""Per-bank tuning knobs for the parsing engines.

None of this is load-bearing on its own — the line engine's balance-delta
reconciliation (see line_engine.py) works the same regardless of a bank's
column order, which is what makes it possible to support banks we don't
have sample statements for. A profile just improves the odds of a clean
first-pass parse: extra phrases that mark the opening balance, header words
a bank uses for its columns, and date formats to try first.

HDFC and ICICI profiles were tuned against real statements; KOTAK/SBI/DBS
are best-effort defaults based on each bank's commonly documented statement
format — expect to refine them once you run a real statement through and
check the reconciliation warning. See README.md > Adding or improving a
bank parser.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BankProfile:
    name: str
    # Regex fragments (joined with '|') that mark a running-balance opening line.
    opening_balance_markers: list[str] = field(
        default_factory=lambda: [r"b/?f\b", r"opening balance", r"balance forward"]
    )
    # Column header words this bank uses, for the table engine's fuzzy header match.
    header_words: dict[str, list[str]] = field(
        default_factory=lambda: {
            "date": ["date", "txn date", "value date"],
            "narration": ["narration", "particulars", "description", "details", "transaction remarks"],
            "debit": ["withdrawal", "debit", "withdrawal amt"],
            "credit": ["deposit", "credit", "deposit amt"],
            "balance": ["balance", "closing balance", "balance amt"],
            "ref": ["chq", "ref", "cheque", "reference"],
        }
    )
    # Date formats to try first (others are tried after, as a fallback).
    date_formats: list[str] = field(
        default_factory=lambda: ["%d/%m/%y", "%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y", "%d-%b-%Y", "%d-%b-%y"]
    )
    # Narration-line prefixes that mark the START of a new transaction's text
    # when it wraps onto the line before its date — used to reattach
    # mis-ordered continuation lines to the right transaction.
    narration_start_prefixes: list[str] = field(
        default_factory=lambda: [
            "UPI/", "UPI-", "UPL/", "NEFT", "RTGS", "IMPS", "MMT/", "ACH/", "BIL/",
            "CHQ", "CLG/", "CMS/", "TRF", "INTEREST", "NWD-", "ATM", "POS ",
            "OPENING", "CLOSURE", "REV SWEEP",
        ]
    )
    # Extra boilerplate phrases (beyond the frequency-based auto-detection)
    # known to appear as page headers/footers for this bank.
    extra_boilerplate_contains: list[str] = field(default_factory=list)


PROFILES: dict[str, BankProfile] = {
    "HDFC": BankProfile(
        name="HDFC",
        opening_balance_markers=[r"b/?f\b", r"opening balance"],
        extra_boilerplate_contains=["HDFC BANK LIMITED", "Statement of account", "RTGS/NEFT IFSC"],
    ),
    "ICICI": BankProfile(
        name="ICICI",
        opening_balance_markers=[r"b/?f\b"],
        extra_boilerplate_contains=["ICICI Bank", "Statement of Transactions"],
    ),
    "KOTAK": BankProfile(
        name="KOTAK",
        extra_boilerplate_contains=["Kotak Mahindra Bank"],
    ),
    "SBI": BankProfile(
        name="SBI",
        header_words={
            "date": ["txn date", "date", "value date"],
            "narration": ["description", "narration", "particulars"],
            "debit": ["debit", "withdrawal"],
            "credit": ["credit", "deposit"],
            "balance": ["balance"],
            "ref": ["ref no./cheque no.", "ref no", "cheque no"],
        },
        extra_boilerplate_contains=["State Bank of India"],
    ),
    "DBS": BankProfile(
        name="DBS",
        extra_boilerplate_contains=["DBS Bank India"],
    ),
    "GENERIC": BankProfile(name="GENERIC"),
}


def get_profile(bank: str) -> BankProfile:
    return PROFILES.get(bank, PROFILES["GENERIC"])
