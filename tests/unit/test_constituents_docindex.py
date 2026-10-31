"""Unit tests for constituents loading and the document index."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.errors import DataError
from nowcast.ingestion.constituents import active_on, cik_list, load_constituents
from nowcast.ingestion.doc_index import INDEX_COLUMNS, load_index, upsert_index


def _write_constituents(path: Path, drop: str | None = None) -> Path:
    """Write a three-row constituents CSV, optionally dropping one column."""
    frame = pd.DataFrame(
        {
            'ticker': ['AAA', 'BBB', 'CCC'],
            'cik': ['1', '2', '3'],
            'effective_from': ['2024-01-01', '2024-01-01', '2025-06-01'],
            'effective_to': ['2026-12-31', '2025-05-31', '2026-12-31'],
            'weight': [0.5, 0.3, 0.2],
        }
    )
    if drop:
        frame = frame.drop(columns=[drop])
    frame.to_csv(path, index=False)
    return path


def test_constituents_missing_column_message(tmp_path: Path) -> None:
    """A missing required column raises DataError naming the column."""
    path = _write_constituents(tmp_path / 'c.csv', drop='effective_to')
    with pytest.raises(DataError) as excinfo:
        load_constituents(path)
    assert 'effective_to' in str(excinfo.value)


def test_constituents_missing_file(tmp_path: Path) -> None:
    """A missing file raises DataError."""
    with pytest.raises(DataError):
        load_constituents(tmp_path / 'absent.csv')


def test_active_on_point_in_time(tmp_path: Path) -> None:
    """Membership is evaluated point in time."""
    frame = load_constituents(_write_constituents(tmp_path / 'c.csv'))
    early = active_on(frame, '2024-06-01')
    late = active_on(frame, '2025-08-01')
    assert set(early['ticker']) == {'AAA', 'BBB'}
    assert set(late['ticker']) == {'AAA', 'CCC'}
    assert cik_list(frame, '2025-08-01') == ['0000000001', '0000000003']


def test_cik_zero_padded(tmp_path: Path) -> None:
    """CIKs load zero-padded to ten digits."""
    frame = load_constituents(_write_constituents(tmp_path / 'c.csv'))
    assert all(len(cik) == 10 for cik in frame['cik'])


def test_doc_index_upsert_is_idempotent(tmp_path: Path) -> None:
    """Upserting the same rows twice leaves one row per document."""
    index_path = tmp_path / 'index.parquet'
    row = {
        'document_id': 'doc-1',
        'cik': '0000000001',
        'report_date': '2026-01-02',
        'document_type': 'EX-99',
        'source': 'local',
        'raw_path': str(tmp_path / 'a.html'),
        'sha256': 'abc',
        'chars': 10,
        'downloaded_at': '2026-01-02T00:00:00',
    }
    upsert_index(index_path, [row])
    frame = upsert_index(index_path, [row])
    assert len(frame) == 1
    assert list(frame.columns) == list(INDEX_COLUMNS)


def test_doc_index_latest_row_wins(tmp_path: Path) -> None:
    """A later upsert for the same document replaces the earlier one."""
    index_path = tmp_path / 'index.parquet'
    base = {
        'document_id': 'doc-1',
        'cik': '0000000001',
        'report_date': '2026-01-02',
        'document_type': 'EX-99',
        'source': 'local',
        'raw_path': 'a',
        'sha256': 'aaa',
        'chars': 10,
        'downloaded_at': '2026-01-02T00:00:00',
    }
    upsert_index(index_path, [base])
    frame = upsert_index(index_path, [{**base, 'sha256': 'bbb'}])
    assert frame.loc[frame['document_id'] == 'doc-1', 'sha256'].item() == 'bbb'


def test_load_index_missing_returns_empty(tmp_path: Path) -> None:
    """A missing index file yields an empty frame with the expected columns."""
    frame = load_index(tmp_path / 'absent.parquet')
    assert frame.empty
    assert list(frame.columns) == list(INDEX_COLUMNS)


def test_active_on_includes_open_ended_members(tmp_path: Path) -> None:
    """A blank effective_to means 'still a member' and must never be excluded.

    NaT compares False against every timestamp, so an unguarded mask silently
    drops every current member — the whole universe — from any point-in-time query.
    """
    path = tmp_path / 'c.csv'
    pd.DataFrame(
        {
            'ticker': ['AAA', 'BBB'],
            'cik': ['1', '2'],
            'effective_from': ['2024-01-01', '2024-01-01'],
            'effective_to': ['2024-06-01', ''],
        }
    ).to_csv(path, index=False)
    frame = load_constituents(path)

    later = active_on(frame, '2026-10-01')
    assert list(later['ticker']) == ['BBB']
    assert cik_list(frame, '2026-10-01') == ['0000000002']

    earlier = active_on(frame, '2024-03-01')
    assert list(earlier['ticker']) == ['AAA', 'BBB']
