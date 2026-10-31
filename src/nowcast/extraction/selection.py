"""Choose which indexed documents to extract, representatively.

The index is sorted by report date and document id, so `documents[:10]` is the ten oldest
filings from a handful of companies — a sample of nothing. A run that should describe the
index takes one document per company first, then spreads the rest across seasons.
"""

from __future__ import annotations

import random
from collections import defaultdict

from nowcast.extraction.runner import Document

SEASON_MONTHS = 3


def season_of_date(report_date: str) -> str:
    """Return the calendar season (`2025Q1`) a filing date falls in."""
    year = report_date[:4]
    month = int(report_date[5:7] or 1)
    return f'{year}Q{((month - 1) // SEASON_MONTHS) + 1}'


def stratified_sample(documents: list[Document], count: int, seed: int) -> list[Document]:
    """Return up to `count` documents: one per company first, then spread by season.

    Deterministic for a given seed and input order. Within a season, each company is
    visited once before any company is visited twice, so a small sample covers companies
    rather than three quarters of one filer; the seasons then take turns, so it covers
    more than one period.
    """
    if count <= 0 or count >= len(documents):
        return list(documents)
    rng = random.Random(seed)
    per_company: dict[str, list[Document]] = defaultdict(list)
    for document in documents:
        per_company[document.cik].append(document)
    companies = sorted(per_company)
    rng.shuffle(companies)
    # Each company's own documents in season order, rotated by its position so the first
    # round does not take everybody's earliest filing.
    for index, cik in enumerate(companies):
        ordered = sorted(
            per_company[cik], key=lambda item: (season_of_date(item.report_date), item.document_id)
        )
        shift = index % len(ordered)
        per_company[cik] = ordered[shift:] + ordered[:shift]

    # Round robin over companies: round k takes each company's k-th document, so every
    # company is represented before any company is represented twice.
    chosen: list[Document] = []
    round_index = 0
    while len(chosen) < count:
        progressed = False
        for cik in companies:
            picks = per_company[cik]
            if round_index < len(picks):
                chosen.append(picks[round_index])
                progressed = True
                if len(chosen) >= count:
                    break
        if not progressed:
            break
        round_index += 1
    return chosen


def describe(documents: list[Document]) -> dict[str, object]:
    """Return the sample's shape, for the run log and summary."""
    return {
        'documents': len(documents),
        'companies': len({document.cik for document in documents}),
        'seasons': sorted({season_of_date(document.report_date) for document in documents}),
        'per_company': dict(sorted(_counts(documents).items())),
    }


def _counts(documents: list[Document]) -> dict[str, int]:
    """Return how many documents each company contributes."""
    counts: dict[str, int] = defaultdict(int)
    for document in documents:
        counts[document.cik] += 1
    return counts
