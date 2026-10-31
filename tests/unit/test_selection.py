"""F9: a capped extraction run samples companies and seasons, not the oldest ten files."""

from __future__ import annotations

from pathlib import Path

from nowcast.extraction.runner import Document
from nowcast.extraction.selection import season_of_date, stratified_sample


def _index_documents() -> list[Document]:
    """Six companies across three seasons, index order oldest first."""
    documents: list[Document] = []
    seasons = ('2025-01-30', '2025-04-24', '2025-07-25')
    for season_index, report_date in enumerate(seasons):
        for company in range(6):
            documents.append(
                Document(
                    document_id=f'{season_index}-{company}',
                    cik=f'{company:010d}',
                    report_date=report_date,
                    document_type='EX-99.1',
                    raw_path=Path('x.htm'),
                    sha256='x',
                )
            )
    return documents


def test_sample_spreads_companies_and_seasons() -> None:
    """Ten documents cover ten companies and more than one season."""
    from nowcast.extraction.selection import describe

    sample = stratified_sample(_index_documents(), 10, seed=1)
    shape = describe(sample)
    assert len(sample) == 10
    assert shape['companies'] == 6
    assert len(shape['seasons']) >= 2
    # `documents[:10]` is two seasons from six companies in the ancient order; the point
    # is the first pass takes each company once before taking a second document.
    assert max(shape['per_company'].values()) == 2


def test_sample_deterministic_for_seed() -> None:
    """The same seed and input choose the same documents, twice."""
    documents = _index_documents()
    first = stratified_sample(documents, 7, seed=11)
    second = stratified_sample(documents, 7, seed=11)
    assert [item.document_id for item in first] == [item.document_id for item in second]


def test_sample_is_not_the_index_head() -> None:
    """A capped sample is not simply the first N rows."""
    documents = _index_documents()
    sample = stratified_sample(documents, 5, seed=3)
    assert [item.document_id for item in sample] != [item.document_id for item in documents[:5]]


def test_season_of_date_uses_calendar_quarters() -> None:
    """A filing in April is Q2 of that year."""
    assert season_of_date('2025-04-24') == '2025Q2'
    assert season_of_date('2025-12-31') == '2025Q4'
    assert season_of_date('2025-01-01') == '2025Q1'
