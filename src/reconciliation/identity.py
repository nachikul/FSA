"""Matches staged UnifiedRecords (from a fresh upload) against the
canonical set already accepted this session. Exact match on record_id
covers anything with a stable identifier (folio number, FD certificate,
ISIN, ticker). The fuzzy fallback exists for the same reason bank
statement reference numbers aren't trusted across periods (see
line_engine.py's balance-reconciliation approach) — some sources don't
carry a stable id from one upload to the next, so records have to be
matched on name instead.

Deliberately conservative: a fuzzy match below the threshold is treated
as "no match" (i.e. the staged record is NEW), never guessed into a
match. A missed match just means an extra "new record" row to review —
annoying but safe. A wrong match would silently overwrite a different
holding's value, which isn't an acceptable trade either way.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from ..core.unified import UnifiedRecord

FUZZY_MATCH_THRESHOLD = 0.82


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def match(staged: list[UnifiedRecord], canonical: list[UnifiedRecord]) -> dict[str, Optional[str]]:
    """Returns {staged_record_id: matched_canonical_record_id_or_None}."""
    canonical_ids = {r.record_id for r in canonical}
    result: dict[str, Optional[str]] = {}

    for rec in staged:
        if rec.record_id in canonical_ids:
            result[rec.record_id] = rec.record_id
            continue

        best_id: Optional[str] = None
        best_score = 0.0
        for canon in canonical:
            # Only compare within the same source/account/asset class —
            # a name match across sources is exactly the "same fund
            # tracked twice" case that link_group (a manual, user-driven
            # action) handles, not something to auto-collapse here.
            if canon.source_system != rec.source_system:
                continue
            if canon.asset_class != rec.asset_class:
                continue
            if canon.account_name != rec.account_name:
                continue
            score = _name_similarity(canon.name, rec.name)
            if score > best_score:
                best_id, best_score = canon.record_id, score

        result[rec.record_id] = best_id if best_score >= FUZZY_MATCH_THRESHOLD else None

    return result
