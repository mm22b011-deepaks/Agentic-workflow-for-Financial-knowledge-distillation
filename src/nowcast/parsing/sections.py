"""Regex-based section splitting with exact character offsets."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    """One named span of a document."""

    name: str
    start: int
    end: int


def split_sections(text: str, patterns: dict[str, str]) -> list[Section]:
    """Split text on the first match of each pattern, returning ordered spans."""
    if not patterns:
        return [Section(name='full', start=0, end=len(text))]
    hits: list[tuple[int, str]] = []
    for name, pattern in patterns.items():
        match = re.search(pattern, text)
        if match is not None:
            hits.append((match.start(), name))
    if not hits:
        return [Section(name='full', start=0, end=len(text))]
    hits.sort()
    sections: list[Section] = []
    for index, (start, name) in enumerate(hits):
        end = hits[index + 1][0] if index + 1 < len(hits) else len(text)
        sections.append(Section(name=name, start=start, end=end))
    return sections


def pick_sections(text: str, patterns: dict[str, str], names: list[str]) -> str:
    """Join the text of the named sections in document order, falling back to the full text."""
    if not patterns or not names:
        return text
    selected = [section for section in split_sections(text, patterns) if section.name in names]
    if not selected:
        return text
    return '\n'.join(text[section.start : section.end] for section in selected)
