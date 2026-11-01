"""Interim document packer: a priority budget over the passages that carry the facts.

The extraction prompt is capped at `max_doc_chars`. Cutting at that length keeps the
dateline and the first paragraphs and drops the guidance section of a long release — on
the measured corpus, the only guidance text in four documents sat past the cut. Until R2's
context packer exists, the fix is to give the budget to the passages a reader would look
for: the head, then guidance/outlook, then per-share, then revenue. Priority decides what
is kept; document order decides how it is written, so the model still reads a release.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WINDOW_CHARS = 1200
OMISSION = '\n[... omitted ...]\n'
# Phrases are matched in priority order, so a guidance phrase outranks a revenue phrase.
DEFAULT_PRIORITY = ('guidance', 'outlook', 'per share', 'revenue')


@dataclass(frozen=True)
class Packed:
    """Packed prompt text and how it was built."""

    text: str
    chars_total: int
    windows_used: int

    @property
    def truncated(self) -> bool:
        """Return True when any source text was left out."""
        return len(self.text) < self.chars_total


def _windows(text: str, phrases: tuple[str, ...], taken: list[tuple[int, int, int]]) -> int:
    """Append merged phrase windows to `taken`, in priority order, and return how many.

    Each phrase contributes its best few matches rather than every occurrence: a release
    that says "revenue" sixty times would otherwise exhaust the budget on one word.
    """
    added = 0
    half = WINDOW_CHARS // 2
    for rank, phrase in enumerate(phrases):
        matches = list(re.finditer(re.escape(phrase), text, re.IGNORECASE))
        for match in matches[:3]:
            start = max(0, match.start() - half)
            end = min(len(text), match.end() + half)
            if any(
                start <= existing_end and end >= existing_start
                for existing_start, existing_end, _rank in taken
            ):
                continue
            taken.append((start, end, rank))
            added += 1
    return added


def pack(
    text: str,
    limit: int,
    phrases: tuple[str, ...] = (),
    priority: tuple[str, ...] = DEFAULT_PRIORITY,
) -> Packed:
    """Return at most `limit` characters, chosen by priority and written in order.

    Regions are collected strongest-first (head, then each priority phrase), merged when
    they overlap, and only then joined in original order. Budget is never taken by a
    region that would not fit: an earlier version sliced with a negative length and
    dropped regions silently.
    """
    if limit <= 0:
        return Packed(text='', chars_total=len(text), windows_used=0)
    if len(text) <= limit:
        return Packed(text=text, chars_total=len(text), windows_used=0)
    if not phrases:
        # No configured phrases: the old behaviour, a plain head cut.
        return Packed(text=text[:limit], chars_total=len(text), windows_used=0)
    head_chars = min(len(text), limit // 3)
    spans: list[tuple[int, int, int]] = [(0, head_chars, -1)] if head_chars else []
    pool = tuple(phrases)
    ordered = tuple(p for p in priority if p in pool) + tuple(p for p in pool if p not in priority)
    windows = _windows(text, ordered, spans)
    ranked = sorted(spans, key=lambda item: (item[2], item[0]))
    merged: list[tuple[int, int, int]] = []
    for start, end, rank in ranked:
        for index, (existing_start, existing_end, existing_rank) in enumerate(merged):
            if start <= existing_end and end >= existing_start:
                merged[index] = (
                    min(start, existing_start),
                    max(end, existing_end),
                    min(rank, existing_rank),
                )
                break
        else:
            merged.append((start, end, rank))
    # Choose by priority: the budget goes to the most important regions first, and only
    # then are the survivors written back in document order.
    merged.sort(key=lambda item: (item[2], item[0]))
    chosen: list[tuple[int, int, int]] = []
    used = 0
    for item in merged:
        start, end, _rank = item
        separator = len(OMISSION) if chosen else 0
        room = limit - used - separator
        if room <= 0:
            break
        if end - start > room:
            # A region that does not fit is trimmed, never allowed to overrun; the
            # scanning break above is what keeps the total inside the limit.
            end = start + room
        if text[start:end].strip():
            chosen.append((start, end, item[2]))
            used += (len(OMISSION) if len(chosen) > 1 else 0) + (end - start)
    chosen.sort(key=lambda item: item[0])

    parts: list[str] = []
    for start, end, _rank in chosen:
        marker = OMISSION if parts else ''
        parts.append(marker + text[start:end])
    packed = ''.join(parts)[:limit]
    return Packed(
        text=packed,
        chars_total=len(text),
        windows_used=max(0, min(windows, len(chosen) - 1)),
    )
