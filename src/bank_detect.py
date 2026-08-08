"""Best-effort bank identification from statement text, used to route to the
right parser. Falls back to "GENERIC" (handled by the generic table parser)
for anything unrecognized — you can always override the guess in the UI."""
from __future__ import annotations

SUPPORTED_BANKS = ["HDFC", "ICICI", "KOTAK", "SBI", "DBS"]

_SIGNATURES: dict[str, list[str]] = {
    "HDFC": ["hdfc bank", "hdfc0"],
    "ICICI": ["icici bank", "icic0"],
    "KOTAK": ["kotak mahindra bank", "kkbk0"],
    "SBI": ["state bank of india", "sbin0"],
    "DBS": ["dbs bank", "dbss0"],
}


def detect_bank(text: str) -> str:
    lower = text.lower()
    scores = {bank: sum(lower.count(sig) for sig in sigs) for bank, sigs in _SIGNATURES.items()}
    best_bank, best_score = max(scores.items(), key=lambda kv: kv[1])
    return best_bank if best_score > 0 else "GENERIC"
