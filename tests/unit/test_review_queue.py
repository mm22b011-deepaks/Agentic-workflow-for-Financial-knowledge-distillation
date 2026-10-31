"""Unit tests for review-queue persistence."""

from __future__ import annotations

from pathlib import Path

from nowcast.extraction.review_queue import QUEUE_COLUMNS, append_rows, load_queue, rows_for_record


def test_append_rows_creates_queue(tmp_path: Path) -> None:
    """Appending rows writes a parquet with the fixed schema."""
    path = tmp_path / 'queue.parquet'
    frame = append_rows(
        path,
        [{'document_id': 'd1', 'field': 'reported_eps', 'reason': 'llm_failed', 'model': 'm:free'}],
    )
    assert list(frame.columns) == list(QUEUE_COLUMNS)
    assert len(frame) == 1


def test_append_rows_is_idempotent(tmp_path: Path) -> None:
    """Re-appending the same row does not duplicate it."""
    path = tmp_path / 'queue.parquet'
    row = {'document_id': 'd1', 'field': 'record', 'reason': 'llm_failed', 'model': 'm:free'}
    append_rows(path, [row])
    frame = append_rows(path, [row])
    assert len(frame) == 1


def test_load_queue_missing_returns_empty(tmp_path: Path) -> None:
    """A missing queue file yields an empty typed frame."""
    frame = load_queue(tmp_path / 'absent.parquet')
    assert frame.empty
    assert list(frame.columns) == list(QUEUE_COLUMNS)


def test_rows_for_record_splits_reasons_and_issues() -> None:
    """Review reasons and validation issues both become queue rows."""
    rows = rows_for_record(
        'd1',
        'm:free',
        ['low_confidence:reported_eps', 'validation_issues'],
        [('reported_eps', 'number_not_in_quote')],
    )
    fields = {(row['field'], row['reason']) for row in rows}
    assert ('reported_eps', 'low_confidence') in fields
    assert ('record', 'validation_issues') in fields
    assert ('reported_eps', 'number_not_in_quote') in fields
