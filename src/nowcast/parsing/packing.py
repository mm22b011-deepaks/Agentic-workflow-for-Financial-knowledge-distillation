"""Interim document packer: keep the head and the windows around key phrases.

The extraction prompt is capped at `max_doc_chars`. Cutting at that length keeps the
dateline and the first paragraphs and drops the guidance section of a long release — on
the measured corpus, the only guidance text in four documents sat past the cut. Until R2's
context packer exists, the cheapest honest fix is to keep the head *and* the passages a
reader would look for, joined in original order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WINDOW_CHARS = 1200
OMISSION = '\n[... omitted ...]\n'


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


def pack(text: str, limit: int, phrases: tuple[str, ...], head: int | None = None) -> Packed:
    """Return at most `limit` characters: the head, then windows around `phrases`.

    Regions are collected, merged when they overlap, and joined in original order with an
    omission marker between non-adjacent regions. `head` defaults to a third of `limit`:
    enough for the dateline and the highlights list, leaving the rest for the windows.
    """
    if limit <= 0 or len(text) <= limit:
        return Packed(text=text[: max(limit, 0)], chars_total=len(text), windows_used=0)
    if not phrases:
        # Nothing worth searching for: the old behaviour, a plain head cut.
        return Packed(text=text[:limit], chars_total=len(text), windows_used=0)
    head_chars = min(limit, head if head is not None else limit // 3)
    spans: list[tuple[int, int]] = [(0, head_chars)] if head_chars else []
    half = WINDOW_CHARS // 2
    for phrase in phrases:
        for match in re.finditer(re.escape(phrase), text, re.IGNORECASE):
            spans.append((max(0, match.start() - half), min(len(text), match.end() + half)))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    pieces: list[str] = []
    used = 0
    windows = 0
    for start, end in merged:
        if used >= limit:
            break
        room = limit - used
        chunk = text[start:end][:room]
        if not chunk.strip():
            continue
        if pieces:
            pieces.append(OMISSION)
            used += len(OMISSION)
            room = limit - used
            chunk = chunk[:room]
        pieces.append(chunk)
        used += len(chunk)
        windows += 1
    return Packed(text=''.join(pieces), chars_total=len(text), windows_used=max(0, windows - 1))
