"""Bank-agnostic fallback parser for statements that are print-formatted
(no real PDF table structure) — this is most Indian bank statements.

The key trick, instead of trying to learn each bank's column order: a
transaction's balance is (almost) always the last amount printed on its
row, and it's *cumulative* — so given the opening balance, the direction
(debit vs credit) and amount of every later row can be derived purely from
how much the running balance moved, without ever needing to know which
column was "withdrawal" and which was "deposit". This is what lets one
engine cover HDFC, ICICI, Kotak, SBI and DBS without five different
hand-tuned column parsers.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date as Date
from typing import Optional

from ..models import Statement, Transaction
from .profiles import BankProfile
from .utils import clean_amount, extract_amounts, find_leading_date, try_parse_date

SAVINGS_ACCOUNT_RE = re.compile(r"savings[^0-9]{0,60}?(\d{6,20})", re.IGNORECASE)
# Digits-only capture is deliberate: an earlier version captured [A-Z0-9]
# under re.IGNORECASE, which (IGNORECASE affects the whole pattern, not
# just literal text) matched ordinary words like "Branch" or "Balance" as
# if they were account numbers whenever they followed "Account " in the
# statement header. Real account numbers here are always numeric.
ACCOUNT_NO_RE = re.compile(r"(?:account|a/c)\.?\s*(?:no\.?|number)?\s*[:\-]?\s*(\d{6,20})", re.IGNORECASE)
HOLDER_RE = re.compile(r"(?:MR\.?|MRS\.?|MS\.?)\s+([A-Z][A-Z .]{3,40})")


def _extract_account_number(text: str) -> Optional[str]:
    # Prefer a number near the word "Savings" — statements with multiple
    # linked accounts (PPF, FDs, ...) list those first, and a plain
    # "Account No" search would otherwise grab the wrong one.
    m = SAVINGS_ACCOUNT_RE.search(text)
    if m:
        return m.group(1)
    m = ACCOUNT_NO_RE.search(text)
    return m.group(1) if m else None


def _strip_boilerplate(lines: list[str], profile: BankProfile, num_pages: int = 1) -> list[str]:
    counts = Counter(l.strip() for l in lines if l.strip() and len(l.strip()) > 3)
    # A line repeated on nearly every page is almost always a page
    # header/footer rather than transaction content — true boilerplate
    # (address block, bank name, column headers) repeats on ~100% of pages.
    # The threshold has to sit high: a recurring *transaction* phrase (the
    # same employer's NEFT suffix showing up on a dozen salary credits
    # across a year) can also repeat often enough to look like boilerplate
    # at a looser threshold, which would silently eat real narration text.
    repeat_threshold = max(3, int(num_pages * 0.6))
    boilerplate = {l for l, c in counts.items() if c >= repeat_threshold}

    out = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s in boilerplate:
            continue
        if any(marker.lower() in s.lower() for marker in profile.extra_boilerplate_contains):
            continue
        if re.match(r"^page\s+\d+\s+of\s+\d+$", s, re.IGNORECASE):
            continue
        out.append(line)
    return out


def _find_opening_balance(lines: list[str], profile: BankProfile) -> Optional[float]:
    pattern = re.compile("|".join(profile.opening_balance_markers), re.IGNORECASE)
    for line in lines[:60]:
        if pattern.search(line):
            amounts = extract_amounts(line)
            if amounts:
                val = clean_amount(amounts[-1][1])
                if val is not None:
                    return val
    return None


def _reattach_preambles(lines: list[str], date_positions: list[int], profile: BankProfile) -> dict[int, list[int]]:
    """For non-date lines sitting between two date-lines, decide whether they
    belong to the transaction that follows (they start a new narration, e.g.
    "UPI/...") or trail the transaction before them (continuation text)."""
    prefixes = tuple(p.lower() for p in profile.narration_start_prefixes)
    reassigned: dict[int, list[int]] = {}
    for k, di in enumerate(date_positions):
        prev_di = date_positions[k - 1] if k > 0 else -1
        gap = list(range(prev_di + 1, di))
        if not gap:
            continue
        split_at = None
        for g in gap:
            if lines[g].strip().lower().startswith(prefixes):
                split_at = g
                break
        if split_at is not None:
            reassigned[di] = gap[gap.index(split_at):]
    return reassigned


def parse_lines(
    full_text: str,
    profile: BankProfile,
    source_file: str,
    manual_opening_balance: Optional[float] = None,
    num_pages: int = 1,
) -> Statement:
    stmt = Statement(bank=profile.name, source_file=source_file, parser_used="line_engine")

    raw_lines = full_text.split("\n")

    stmt.account_number = _extract_account_number(full_text)
    m = HOLDER_RE.search(full_text)
    if m:
        stmt.account_holder = m.group(1).strip().title()

    lines = _strip_boilerplate(raw_lines, profile, num_pages)
    if not lines:
        return stmt

    date_positions = [i for i, l in enumerate(lines) if find_leading_date(l, profile.date_formats)]
    if not date_positions:
        stmt.parse_warnings.append("Couldn't find any dated transaction rows in this document.")
        return stmt

    reassigned = _reattach_preambles(lines, date_positions, profile)
    consumed: set[int] = {g for lst in reassigned.values() for g in lst}

    opening = manual_opening_balance if manual_opening_balance is not None else _find_opening_balance(lines, profile)

    # Build one block of (date, [amount tokens], narration_text) per date-line.
    blocks: list[dict] = []
    for k, di in enumerate(date_positions):
        d, rest = find_leading_date(lines[di], profile.date_formats)
        amounts: list[str] = []
        narration_parts: list[str] = []

        if di in reassigned:
            for g in reassigned[di]:
                amounts.extend(v for _, v in extract_amounts(lines[g]))
                text = re.sub(r"\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?", "", lines[g]).strip()
                if text:
                    narration_parts.append(text)

        amounts.extend(v for _, v in extract_amounts(rest))
        text = re.sub(r"\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?", "", rest).strip()
        if text:
            narration_parts.append(text)

        # Trailing continuation lines up to (but not including) the next date-line
        # or the next block's reassigned leading lines.
        next_di = date_positions[k + 1] if k + 1 < len(date_positions) else len(lines)
        next_reassigned_start = None
        if k + 1 < len(date_positions) and date_positions[k + 1] in reassigned:
            first_leading = reassigned[date_positions[k + 1]][0]
            next_reassigned_start = first_leading
        trailing_end = next_reassigned_start if next_reassigned_start is not None else next_di

        for j in range(di + 1, trailing_end):
            if j in consumed:
                continue
            amounts.extend(v for _, v in extract_amounts(lines[j]))
            text = re.sub(r"\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?", "", lines[j]).strip()
            if text:
                narration_parts.append(text)

        blocks.append({"date": d, "amounts": amounts, "narration": " ".join(narration_parts)})

    # Multi-ledger statements (e.g. a linked PPF or FD sub-account ledger
    # printed in the same PDF as the main savings account) repeat a fresh
    # "B/F" opening-balance line per ledger. Split on those and keep only
    # the largest segment — the main account's transaction history — so a
    # small linked ledger doesn't get silently merged into it (which would
    # both corrupt the running-balance reconciliation at the boundary and,
    # since both ledgers share the same statement-level "Account No" text,
    # let a handful of stray rows overwrite the real closing balance).
    segments: list[list[dict]] = []
    current: list[dict] = []
    for blk in blocks:
        if blk["narration"].strip().upper().startswith("B/F") and current:
            segments.append(current)
            current = []
        current.append(blk)
    if current:
        segments.append(current)
    if len(segments) > 1:
        blocks = max(segments, key=len)
        stmt.parse_warnings.append(
            f"This document contains {len(segments)} separate account ledgers (e.g. a linked PPF or "
            f"FD sub-account) — used the largest one ({len(blocks)} transactions) and ignored the rest."
        )

    if opening is None and blocks:
        # No explicit opening-balance line found — seed from the first row's
        # own balance instead (last amount on that row), which still lets
        # every *subsequent* row's direction be derived from the delta.
        first_amounts = [clean_amount(a) for a in blocks[0]["amounts"]]
        first_amounts = [a for a in first_amounts if a is not None]
        if len(first_amounts) >= 2:
            opening = first_amounts[-1] - first_amounts[-2]
        stmt.parse_warnings.append(
            "No explicit opening balance found — inferred one from the first transaction. "
            "If totals look off, provide the opening balance manually."
        )

    running = opening
    stmt.opening_balance = opening

    for blk in blocks:
        amts = [clean_amount(a) for a in blk["amounts"]]
        amts = [a for a in amts if a is not None]
        if not amts:
            continue
        balance = amts[-1]
        others = [abs(a) for a in amts[:-1]]

        if running is None:
            # Nothing to reconcile against yet; take the first non-balance
            # amount at face value and start tracking from here.
            txn_amt = others[0] if others else 0.0
            direction_credit = True
            confidence = 0.5
        elif not others:
            txn_amt = abs(round(balance - running, 2))
            direction_credit = balance >= running
            confidence = 1.0
        else:
            delta = balance - running
            best = min(others, key=lambda v: abs(abs(delta) - v))
            txn_amt = best
            direction_credit = delta >= 0
            confidence = 1.0 if abs(abs(delta) - best) < 0.02 else 0.6

        stmt.transactions.append(
            Transaction(
                date=blk["date"],
                narration=blk["narration"],
                credit=txn_amt if direction_credit else None,
                debit=None if direction_credit else txn_amt,
                balance=balance,
                confidence=confidence,
            )
        )
        running = balance

    if stmt.transactions:
        stmt.closing_balance = stmt.transactions[-1].balance
        stmt.period_start = stmt.transactions[0].date
        stmt.period_end = stmt.transactions[-1].date

    low_conf = sum(1 for t in stmt.transactions if t.confidence < 0.9)
    if low_conf:
        stmt.parse_warnings.append(
            f"{low_conf} of {len(stmt.transactions)} rows had an ambiguous amount and were assigned "
            "by best fit — filter by confidence in the data table to review them."
        )

    return stmt
