"""N7: the index rebuild writes a new path, never overwrites the old one."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import Config, extractions_dir, resolve_data_path
from nowcast.errors import DataError
from nowcast.ingestion.doc_index import load_index
from nowcast.ingestion.rebuild import (
    INVALID_NO_EARNINGS_ITEM,
    INVALID_NON_TEXT,
    INVALID_OUT_OF_WINDOW,
    index_path,
    rebuild_index,
    validate_index_rows,
    write_rebuild_report,
)


def _row(document_id: str, **overrides: object) -> dict[str, object]:
    """Build one index row with everything a valid earnings exhibit needs."""
    row: dict[str, object] = {
        'document_id': document_id,
        'cik': '0000000001',
        'report_date': '2025-04-25',
        'document_type': 'EX-99.1',
        'source': 'edgar',
        'raw_path': f'raw/0000000001/a/{document_id}.htm',
        'sha256': document_id,
        'chars': 100,
        'downloaded_at': '2025-04-25T00:00:00+00:00',
        'items': '2.02,9.01',
    }
    row.update(overrides)
    return row


def _legacy(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    """Write a pre-v2 index and return its path."""
    path = tmp_path / 'data' / 'document_index.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def test_index_validation_rejects_non_202_non_text_out_of_window(config: Config) -> None:
    """Each reason a row can fail is named separately, not collapsed into 'invalid'."""
    frame = pd.DataFrame(
        [
            _row('good'),
            _row('scan', raw_path='raw/1/a/scan.jpg'),
            _row('dividend', items='8.01'),
            _row('old', report_date='2019-01-01'),
            _row('unknown_items', items=''),
        ]
    )
    problems = validate_index_rows(frame, config)
    by_id = {problem.document_id: problem.code for problem in problems}
    assert 'good' not in by_id
    assert by_id['scan'] == INVALID_NON_TEXT
    assert by_id['dividend'] == INVALID_NO_EARNINGS_ITEM
    assert by_id['unknown_items'] == INVALID_NO_EARNINGS_ITEM
    assert by_id['old'] == INVALID_OUT_OF_WINDOW


def test_rebuild_writes_new_path_and_keeps_backup(config: Config, tmp_path: Path) -> None:
    """The rebuild lands at data.document_index and leaves the source untouched."""
    source = _legacy(tmp_path, [_row('good'), _row('scan', raw_path='raw/1/a/scan.jpg')])
    before = source.read_bytes()

    report = rebuild_index(config, load_index(source), source_path=source)

    target = index_path(config)
    assert target == resolve_data_path(config, config.data.document_index)
    assert target.name == 'document_index.v2.parquet'
    assert target.is_file()
    assert source.read_bytes() == before, 'the source index must not be rewritten'
    rebuilt = load_index(target)
    assert list(rebuilt['document_id']) == ['good']
    assert report.kept_rows == 1
    assert report.dropped_documents == ['scan']


def test_rebuild_writes_report(config: Config, tmp_path: Path) -> None:
    """The report says what was dropped and where the new index went."""
    source = _legacy(tmp_path, [_row('good'), _row('dividend', items='8.01')])
    report = rebuild_index(config, load_index(source), source_path=source)
    path = write_rebuild_report(config, report)
    body = json.loads(Path(path).read_text(encoding='utf-8'))
    assert body['source_rows'] == 2
    assert body['kept_rows'] == 1
    assert body['dropped_documents'] == ['dividend']
    assert body['problem_count_by_code'] == {INVALID_NO_EARNINGS_ITEM: 1}
    assert body['new_path'].endswith('document_index.v2.parquet')


def test_rebuild_refuses_to_overwrite_its_source(config: Config, tmp_path: Path) -> None:
    """Naming the source as the target is a DataError, not a silent replacement."""
    target = index_path(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([_row('good')]).to_parquet(target, index=False)
    with pytest.raises(DataError, match='refusing to rebuild'):
        rebuild_index(config, load_index(target), source_path=target)


def test_rebuild_moves_superseded_results_and_queue_rows(config: Config, tmp_path: Path) -> None:
    """Results and queue rows for dropped documents are moved aside, never deleted."""
    source = _legacy(tmp_path, [_row('good'), _row('scan', raw_path='raw/1/a/scan.jpg')])
    model_dir = extractions_dir(config) / 'fake__model-free'
    model_dir.mkdir(parents=True, exist_ok=True)
    for document_id in ('good', 'scan'):
        (model_dir / f'{document_id}.json').write_text('{}', encoding='utf-8')
    queue_path = resolve_data_path(config, config.extraction.review_queue_path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {'document_id': 'good', 'field': 'record', 'reason': 'x', 'model': 'm'},
            {'document_id': 'scan', 'field': 'record', 'reason': 'x', 'model': 'm'},
        ]
    ).to_parquet(queue_path, index=False)

    report = rebuild_index(config, load_index(source), source_path=source)

    assert not (model_dir / 'scan.json').exists()
    assert (extractions_dir(config) / 'superseded' / 'fake__model-free' / 'scan.json').is_file()
    assert (model_dir / 'good.json').is_file()
    assert report.superseded_queue_rows == 1
    remaining = pd.read_parquet(queue_path)
    assert list(remaining['document_id']) == ['good']
    archives = list((queue_path.parent / 'superseded').glob('review_queue.*.parquet'))
    assert len(archives) == 1
    assert list(pd.read_parquet(archives[0])['document_id']) == ['scan']


def test_rebuild_cli_keeps_the_legacy_index(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rebuild-index command runs end to end and the old index still exists."""
    import nowcast.cli as cli

    source = _legacy(tmp_path, [_row('good')])
    monkeypatch.setattr(cli, '_load', lambda _args: config)
    args = cli.build_parser().parse_args(['rebuild-index', '--source', str(source)])
    assert cli._cmd_rebuild_index(args) == 0
    assert source.is_file()
    assert load_index(index_path(config)).shape[0] == 1


def test_rebuild_does_not_wipe_populated_v2(config: Config, tmp_path: Path) -> None:
    """A populated v2 target is refused unless the caller says --force."""
    target = index_path(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([_row('existing')]).to_parquet(target, index=False)
    with pytest.raises(DataError, match='already holds'):
        rebuild_index(config, pd.DataFrame([_row('new')]), source_path=None)


def test_rebuild_backs_up_target(config: Config, tmp_path: Path) -> None:
    """With force, the file being replaced is kept with a timestamp before the write."""
    target = index_path(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([_row('existing')]).to_parquet(target, index=False)
    from nowcast.ingestion.doc_index import file_sha256

    row = _row('new')
    raw = resolve_data_path(config, str(row['raw_path']))
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text('<p>Revenue was $100 million.</p>')
    row['sha256'] = file_sha256(raw)
    source = _legacy(tmp_path, [row])
    report = rebuild_index(config, pd.DataFrame([row]), source_path=source, force=True)
    assert report.backup_path is not None and report.backup_path.is_file()
    backups = pd.read_parquet(report.backup_path)
    assert backups['document_id'].tolist() == ['existing']
    assert load_index(target)['document_id'].tolist() == ['new']
