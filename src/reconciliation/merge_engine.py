"""Applies user-accepted deltas onto the canonical UnifiedRecord list.
Nothing here runs automatically — app.py only calls apply() once a person
has checked which deltas to accept in the Portfolio tab's review step, so
a re-upload can never silently change what the dashboard shows.
"""
from __future__ import annotations

from ..core.unified import UnifiedRecord
from .delta import CHANGED, NEW, POSSIBLY_STALE, Delta


def apply(
    accepted: list[Delta],
    staged_by_id: dict[str, UnifiedRecord],
    canonical: list[UnifiedRecord],
) -> list[UnifiedRecord]:
    """Returns a NEW canonical list — does not mutate the one passed in,
    so a caller holding a reference to the old list (e.g. for an "undo"
    in a future revision) still sees the pre-merge state."""
    by_id = {r.record_id: r for r in canonical}

    for d in accepted:
        if d.status == NEW:
            rec = staged_by_id.get(d.record_id)
            if rec is not None:
                by_id[rec.record_id] = rec
        elif d.status == CHANGED:
            canon = by_id.get(d.record_id)
            staged = staged_by_id.get(d.record_id)
            if canon is not None and staged is not None:
                setattr(canon, d.field, getattr(staged, d.field))
        elif d.status == POSSIBLY_STALE:
            # Accepting a POSSIBLY_STALE delta means "yes, this is
            # actually gone" — remove it. Rejecting it (the default,
            # since a partial upload shouldn't imply removal) leaves it
            # untouched.
            by_id.pop(d.record_id, None)

    return list(by_id.values())
