"""Small, dependency-free helpers shared by the table and line parsing engines."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

# The decimal part is mandatory and deliberate: Indian bank statements always
# print amounts with two decimal places (2,500.00), and requiring it is what
# stops this from matching stray digit runs inside reference numbers, IFSC
# codes, or dates (e.g. the "509" in "IMPS-509115808626"). Don't loosen this
# without re-testing against a real statement — see line_engine.py's
# reconciliation warning if you do and it goes wrong.
AMOUNT_RE = re.compile(r"(\(-\)\s*)?(\d{1,3}(?:,\d{2,3})*\.\d{2})")
# Matches "USD10031.82@84.33"-style FX conversion snippets so we don't mistake
# the USD amount or exchange rate for a rupee transaction amount.
FX_SNIPPET_RE = re.compile(r"[A-Z]{3}[\d,]+\.\d+@\d+\.\d+")

_DATE_FORMATS_DEFAULT = [
    "%d/%m/%y", "%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %B %Y",
    "%Y-%m-%d", "%Y/%m/%d",
]


def clean_amount(raw: str) -> Optional[float]:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    negative = "(-)" in s or s.strip().startswith("-") or s.strip().upper().endswith("DR")
    s = re.sub(r"[(),]", "", s)
    s = re.sub(r"[A-Za-z]", "", s)
    s = s.strip().rstrip(".")
    if not s or not re.match(r"^\d+(\.\d+)?$", s):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if negative else val


def try_parse_date(raw: str, formats: Optional[list[str]] = None) -> Optional[date]:
    s = raw.strip()
    candidates = (formats or []) + _DATE_FORMATS_DEFAULT
    for fmt in candidates:
        try:
            d = datetime.strptime(s, fmt)
        except ValueError:
            continue
        # 2-digit years: pypdf-era statements are all post-2000.
        if d.year < 100:
            d = d.replace(year=d.year + 2000)
        return d.date()
    return None


DATE_AT_START_RE = re.compile(
    r"^\s*(\d{1,2}[/-][A-Za-z0-9]{2,4}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"
)


def find_leading_date(line: str, formats: Optional[list[str]] = None) -> Optional[tuple[date, str]]:
    """If `line` starts with a recognizable date, return (date, rest_of_line)."""
    m = DATE_AT_START_RE.match(line)
    if not m:
        return None
    d = try_parse_date(m.group(1), formats)
    if d is None:
        return None
    return d, line[m.end():]


def strip_fx_amounts(line: str) -> tuple[str, list[tuple[int, int]]]:
    """Return the line unchanged plus a list of (start, end) spans that are
    FX conversion snippets — the amount extractor should ignore matches
    inside these spans."""
    spans = [(m.start(), m.end()) for m in FX_SNIPPET_RE.finditer(line)]
    return line, spans


def extract_amounts(line: str) -> list[tuple[int, str]]:
    """All amount-like tokens in `line` with their character position,
    excluding anything that's part of an FX conversion snippet."""
    _, fx_spans = strip_fx_amounts(line)

    def in_fx(pos: int) -> bool:
        return any(s <= pos < e for s, e in fx_spans)

    out = []
    for m in AMOUNT_RE.finditer(line):
        if in_fx(m.start()):
            continue
        val = m.group(2)
        if m.group(1):
            val = "-" + val
        out.append((m.start(), val))
    return out


def normalize_for_matching(text: str) -> str:
    """Uppercase, whitespace-stripped form used for keyword/category matching.

    Some banks' PDF fonts render with stray inter-letter spaces (a font/glyph
    artifact, not a typo in the statement) — stripping whitespace before
    matching keywords makes narration matching robust to that regardless of
    which bank produced the PDF.
    """
    return re.sub(r"[^A-Z0-9./@_-]", "", text.upper())
