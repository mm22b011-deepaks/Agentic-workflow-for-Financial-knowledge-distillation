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


def test_replace_rows_clears_a_documents_rows(tmp_path: Path) -> None:
    """Re-extracting a document that passes removes its old queue rows."""
    from nowcast.extraction.review_queue import append_rows, load_queue, replace_rows

    path = tmp_path / 'queue.parquet'
    append_rows(
        path,
        [{'document_id': 'doc-1', 'field': 'record', 'reason': 'llm_failed', 'model': 'm:free'}],
    )
    replace_rows(path, 'doc-1', 'm:free', [])
    assert load_queue(path).empty


def test_replace_rows_keeps_other_models(tmp_path: Path) -> None:
    """One model's rows are replaced; the other model's rows stay."""
    from nowcast.extraction.review_queue import append_rows, load_queue, replace_rows

    path = tmp_path / 'queue.parquet'
    append_rows(
        path,
        [
            {'document_id': 'doc-1', 'field': 'record', 'reason': 'llm_failed', 'model': 'a:free'},
            {'document_id': 'doc-1', 'field': 'record', 'reason': 'llm_failed', 'model': 'b:free'},
        ],
    )
    replace_rows(path, 'doc-1', 'a:free', [])
    frame = load_queue(path)
    assert frame['model'].tolist() == ['b:free']


def test_replace_rows_archives_what_it_replaced(tmp_path: Path) -> None:
    """History is kept under superseded/, not deleted."""
    from nowcast.extraction.review_queue import SUPERSEDED_DIR, append_rows, replace_rows

    path = tmp_path / 'queue.parquet'
    append_rows(
        path,
        [{'document_id': 'doc-1', 'field': 'record', 'reason': 'llm_failed', 'model': 'm:free'}],
    )
    replace_rows(path, 'doc-1', 'm:free', [])
    archived = list((tmp_path / SUPERSEDED_DIR).glob('review_queue.*.parquet'))
    assert len(archived) == 1
