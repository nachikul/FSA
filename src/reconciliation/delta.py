"""Computes the reviewable diff between a staged upload and the canonical
UnifiedRecord set. Mirrors the "flag, don't decide" posture
analysis.detect_self_transfers already uses for uncertain matches —
nothing here changes canonical state; it only produces Delta objects for
app.py's review UI to show, and merge_engine.apply() is the only thing
that actually applies them once a person accepts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..core.unified import UnifiedRecord

NEW = "NEW"
CHANGED = "CHANGED"
POSSIBLY_STALE = "POSSIBLY_STALE"

# Fields worth surfacing as an individual delta line when they change.
# Identity-ish fields (name, sector, account_name) aren't tracked here —
# a name spelling change from a source isn't a portfolio change worth a
# review prompt the way a value or quantity move is.
TRACKED_FIELDS = ["quantity", "unit_cost", "cost_basis", "current_price", "current_value"]


@dataclass
class Delta:
    record_id: str
    name: str
    asset_class: str
    field: str      # one of TRACKED_FIELDS, or "*" for a NEW/POSSIBLY_STALE record-level delta
    old_value: Any
    new_value: Any
    status: str      # NEW | CHANGED | POSSIBLY_STALE


def _field_deltas(canonical: UnifiedRecord, staged: UnifiedRecord) -> list[Delta]:
    out = []
    for f in TRACKED_FIELDS:
        old, new = getattr(canonical, f), getattr(staged, f)
        if old != new and not (old is None and new is None):
            out.append(Delta(staged.record_id, staged.name, staged.asset_class.value, f, old, new, CHANGED))
    return out


def compute_deltas(
    staged: list[UnifiedRecord],
    canonical: list[UnifiedRecord],
    matches: dict[str, Optional[str]],
) -> list[Delta]:
    """`matches` is identity.match()'s output: staged.record_id -> matched
    canonical.record_id, or None for no match."""
    canonical_by_id = {r.record_id: r for r in canonical}
    deltas: list[Delta] = []
    matched_canonical_ids: set[str] = set()

    for rec in staged:
        matched_id = matches.get(rec.record_id)
        if matched_id is None:
            deltas.append(Delta(rec.record_id, rec.name, rec.asset_class.value, "*", None, "new record", NEW))
            continue
        matched_canonical_ids.add(matched_id)
        canon = canonical_by_id.get(matched_id)
        if canon is None:
            continue
        deltas.extend(_field_deltas(canon, rec))

    # Canonical records in the SAME account+source scope as this upload,
    # but not present in it — e.g. a holding that dropped out of a
    # re-uploaded statement. Flagged, never auto-removed: a partial
    # upload (one account's file) shouldn't be read as "everything else
    # disappeared." Scoped to (source_system, account_name) so uploading
    # one bank statement doesn't flag every other source's records as
    # missing.
    staged_scopes = {(r.source_system, r.account_name) for r in staged}
    for canon in canonical:
        if canon.record_id in matched_canonical_ids:
            continue
        if (canon.source_system, canon.account_name) in staged_scopes:
            deltas.append(
                Delta(
                    canon.record_id, canon.name, canon.asset_class.value, "*",
                    "present", "missing from this upload", POSSIBLY_STALE,
                )
            )

    return deltas
