"""Cross-source normalized view of everything the app knows about.

This does NOT replace Statement/Transaction, PersonalFinanceData, or
IndmoneyPortfolio — those stay exactly as they are and keep feeding their
own tabs (Dashboard, Parsing Details, Budget vs Actual, Investments & SIPs).
UnifiedRecord is an additional, additive projection built FROM those
objects (see src/adapters/) so that net worth / allocation views can work
*across* sources for the first time, and so re-uploads can be diffed
against what's already been accepted instead of silently replacing it
(see src/reconciliation/).

A plain dataclass to match the rest of the codebase's style — Transaction,
Statement, InvestmentItem are all dataclasses, and there's no Pydantic in
requirements.txt. Introducing a second modeling paradigm for one layer
isn't worth the inconsistency.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date as Date, datetime
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    BANK_CASH = "bank_cash"
    MUTUAL_FUND = "mutual_fund"
    EQUITY = "equity"
    RSU = "rsu"
    GOLD = "gold"
    FIXED_DEPOSIT = "fixed_deposit"
    PROVIDENT_FUND = "provident_fund"
    LIABILITY = "liability"
    OTHER = "other"


class SourceSystem(str, Enum):
    BANK_STATEMENT = "bank_statement"
    PERSONAL_SHEET = "personal_sheet"
    INDMONEY = "indmoney"
    # Not wired up to a parser yet — reserved for the direct-document
    # ingestion sources described in the architecture proposal (MF
    # statements, brokerage holdings, RSU vesting reports, gold
    # statements). Kept here now so record_id hashing and UI code that
    # switches on SourceSystem doesn't need to change again when those
    # land.
    MF_STATEMENT = "mf_statement"
    BROKER_HOLDINGS = "broker_holdings"
    RSU_STATEMENT = "rsu_statement"
    GOLD_STATEMENT = "gold_statement"
    FD_CERTIFICATE = "fd_certificate"


def make_record_id(source_system: SourceSystem, account_name: str, identifier: str, asset_class: AssetClass) -> str:
    """Deterministic id used for exact-match reconciliation (see
    reconciliation/identity.py). Same inputs always produce the same id,
    so re-parsing the same statement/snapshot twice in one session yields
    matching records rather than duplicates."""
    parts = [source_system.value, account_name, identifier, asset_class.value]
    raw = "|".join(p.strip().lower() for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class UnifiedRecord:
    record_id: str
    asset_class: AssetClass
    source_system: SourceSystem   # provenance — Net Worth already keeps INDmoney and the
                                   # personal sheet in separate panels to avoid double-counting
                                   # a fund tracked in both; this is what lets that behavior
                                   # survive once everything flows through one schema.
    identifier: str               # ticker / ISIN / folio no. / FD cert no. / account no. / name
    identifier_type: str          # "ticker" | "isin" | "folio" | "account_no" | "cert_no" | "name"
    name: str

    quantity: float = 1.0         # units; 1.0 for FD/cash/liability-type records
    unit_cost: Optional[float] = None
    cost_basis: Optional[float] = None
    current_price: Optional[float] = None
    current_value: float = 0.0
    currency: str = "INR"

    sector: Optional[str] = None
    industry: Optional[str] = None

    account_name: str = ""
    as_of_date: Optional[Date] = None
    ingested_at: datetime = field(default_factory=datetime.utcnow)

    # Set only by an explicit user action ("these are the same holding") —
    # never inferred automatically. See reconciliation/identity.py for why
    # fuzzy name matching alone isn't trusted to merge two records outright.
    link_group: Optional[str] = None

    # Asset-specific overflow: FD maturity/interest rate, RSU vest
    # schedule, gold purity, INDmoney's raw asset_type string, etc. Keeps
    # the core fields uniform across asset classes instead of accumulating
    # mostly-null columns as new sources are added.
    extra: dict = field(default_factory=dict)
