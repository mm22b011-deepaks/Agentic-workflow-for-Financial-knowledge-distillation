from pathlib import Path

import pandas as pd

from nowcast.cli import main
from nowcast.config import Config
from nowcast.extraction.schema import ExtractionRecord, NumField
from nowcast.extraction.validators import validate_record
from nowcast.ingestion.doc_index import INDEX_COLUMNS, write_index
from nowcast.parsing.html import html_to_text
from nowcast.paths import Paths


def test_force_rebuild_requires_an_explicit_cli_source(config: Config) -> None:
    paths = Paths.from_config(config)
    row = dict.fromkeys(INDEX_COLUMNS, '')
    row.update(
        document_id='current',
        cik='0000000001',
        report_date='2025-04-15',
        raw_path='raw/current.html',
        items='2.02',
    )
    target = paths.resolve(config.data.document_index)
    write_index(pd.DataFrame([row]), target)
    before = target.read_bytes()
    from nowcast.ingestion.doc_index import file_sha256

    raw = paths.resolve('raw/legacy.html')
    raw.parent.mkdir(parents=True)
    raw.write_text('<p>Revenue $100 million.</p>')
    row = {
        **row,
        'document_id': 'legacy',
        'raw_path': 'raw/legacy.html',
        'sha256': file_sha256(raw),
    }
    write_index(pd.DataFrame([row]), paths.resolve('document_index.parquet'))
    config_path = Path(__file__).resolve().parents[2] / 'configs/config.yaml'
    assert main(['rebuild-index', '--config', str(config_path), '--force']) == 2
    assert target.read_bytes() == before


def test_eps_does_not_inherit_table_millions(config: Config) -> None:
    source = html_to_text(
        '<table><caption>In millions</caption><tr><th></th><th>2025</th></tr><tr><td>EPS</td><td>2.00</td></tr></table>'
    )
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        reported_eps=NumField(value=2e6, evidence_quote='EPS 2.00', confidence=1),
    )
    assert 'number_not_in_quote' in {
        issue.code for issue in validate_record(record, source, config)[0]
    }


def test_table_units_reset_between_tables(config: Config) -> None:
    source = html_to_text(
        '<table><caption>In millions</caption><tr><td>Sales</td><td>100</td></tr></table><table><tr><th></th><th>2025</th></tr><tr><td>Revenue</td><td>2</td></tr></table>'
    )
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        revenue=NumField(value=2e6, evidence_quote='Revenue 2', confidence=1),
    )
    assert 'number_not_in_quote' in {
        issue.code for issue in validate_record(record, source, config)[0]
    }


def test_bakeoff_scores_numeric_labels_and_missing_predictions(tmp_path: Path) -> None:
    from nowcast.extraction.bakeoff import score_labels

    labels = tmp_path / 'labels.csv'
    pd.DataFrame(
        [{'document_id': f'd{i}', 'reported_eps': 1, 'revenue': 5} for i in range(10)]
    ).to_csv(labels, index=False)
    predicted = pd.DataFrame([{'document_id': f'd{i}', 'reported_eps': 1.0} for i in range(9)])
    result = score_labels(predicted, labels)
    assert result['reported_eps'] == 0.9
    assert result['revenue'] == 0
    assert score_labels(pd.DataFrame(), labels)['reported_eps'] == 0


def test_preparing_review_does_not_overwrite_human_work(
    config: Config, monkeypatch: object
) -> None:
    import runpy

    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / 'scripts'))
    path = Paths.from_config(config).resolve('verification/human-panel.json')
    path.parent.mkdir(parents=True)
    path.write_text('{"labels":"human work"}')
    before = path.read_bytes()
    runpy.run_path(str(root / 'scripts/prepare_review.py'))['main']()
    assert path.read_bytes() == before


def test_colspan_date_headers_bind_currency_columns(config: Config) -> None:
    source = html_to_text(
        '<table><tr><td></td><td colspan="2">June 30, 2025</td><td colspan="2">June 30, 2024</td></tr><tr><td>Revenue</td><td>$</td><td>100</td><td>$</td><td>200</td></tr></table>'
    )
    for value, wrong in [(100, False), (200, True)]:
        record = ExtractionRecord(
            schema_version='v1',
            document_id='d',
            fiscal_year=2025,
            revenue=NumField(value=value, evidence_quote=f'Revenue ${value}', confidence=1),
        )
        issues, _ = validate_record(record, source, config)
        assert ('number_not_in_source' in {i.code for i in issues}) is wrong


def test_explicit_prior_year_prose_is_not_current_year_evidence(config: Config) -> None:
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        revenue=NumField(value=200, evidence_quote='Revenue in 2024 was $200', confidence=1),
    )
    assert 'number_not_in_source' in {
        i.code for i in validate_record(record, 'Revenue in 2024 was $200', config)[0]
    }


def test_number_only_quote_cannot_select_another_table_period(config: Config) -> None:
    source = html_to_text(
        '<table><tr><th></th><th>2025</th><th>2024</th></tr><tr><td>Revenue</td><td>$100</td><td>$200</td></tr></table>'
    )
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        revenue=NumField(value=200, evidence_quote='$200', confidence=1),
    )
    assert 'number_not_in_source' in {i.code for i in validate_record(record, source, config)[0]}


def test_malformed_table_span_is_still_parseable() -> None:
    assert '100' in html_to_text(
        '<table><tr><td colspan="garbage">Revenue</td><td>100</td></tr></table>'
    )


def test_fuzzy_quote_cannot_change_the_source_year(config: Config) -> None:
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        revenue=NumField(value=200, evidence_quote='Revenue in 2025 was $200', confidence=1),
    )
    assert 'number_not_in_source' in {
        i.code for i in validate_record(record, 'Revenue in 2024 was $200', config)[0]
    }


def test_restart_reconciles_a_job_whose_launcher_died(config: Config) -> None:
    from nowcast.contracts import RunRequest
    from nowcast.jobs import store_for

    store = store_for(config)
    row, _ = store.create(
        RunRequest(workflow_id='demo', submission_id='launcher-died'),
        config,
        Path(__file__).resolve().parents[2] / 'configs/config.yaml',
    )
    store.update(row['id'], pid=99999999, identity='dead')
    store.reconcile()
    assert store.get(row['id'])['status'] == 'interrupted'


def test_explicit_replacement_validates_before_writing(config: Config) -> None:
    import pytest

    from nowcast.errors import DataError
    from nowcast.ingestion.rebuild import rebuild_index

    paths = Paths.from_config(config)
    row = dict.fromkeys(INDEX_COLUMNS, '')
    row.update(
        document_id='current',
        cik='0000000001',
        report_date='2025-04-15',
        raw_path='raw/current.html',
        items='2.02',
    )
    target = paths.resolve(config.data.document_index)
    write_index(pd.DataFrame([row]), target)
    before = target.read_bytes()
    source = paths.resolve('candidate.parquet')
    candidate = {**row, 'document_id': 'candidate', 'raw_path': 'raw/missing.html'}
    write_index(pd.DataFrame([candidate]), source)
    with pytest.raises(DataError):
        rebuild_index(config, pd.DataFrame([candidate]), source_path=source, force=True)
    assert target.read_bytes() == before


def test_unforced_explicit_replacement_keeps_the_target(config: Config) -> None:
    import pytest

    from nowcast.errors import DataError
    from nowcast.ingestion.doc_index import file_sha256
    from nowcast.ingestion.rebuild import rebuild_index

    paths = Paths.from_config(config)
    row = dict.fromkeys(INDEX_COLUMNS, '')
    row.update(
        document_id='current',
        cik='0000000001',
        report_date='2025-04-15',
        raw_path='raw/current.html',
        items='2.02',
    )
    target = paths.resolve(config.data.document_index)
    write_index(pd.DataFrame([row]), target)
    before = target.read_bytes()
    raw = paths.resolve('raw/new.html')
    raw.parent.mkdir(parents=True)
    raw.write_text('<p>Revenue $100 million.</p>')
    candidate = {
        **row,
        'document_id': 'new',
        'raw_path': 'raw/new.html',
        'sha256': file_sha256(raw),
    }
    source = paths.resolve('candidate.parquet')
    write_index(pd.DataFrame([candidate]), source)
    with pytest.raises(DataError):
        rebuild_index(config, pd.DataFrame([candidate]), source_path=source)
    assert target.read_bytes() == before


def test_quota_stop_is_resumable_and_does_not_expose_exception_text(
    config: Config, monkeypatch: object
) -> None:
    import nowcast.worker as worker
    from nowcast.contracts import RunRequest
    from nowcast.errors import BudgetExceeded
    from nowcast.jobs import store_for

    store = store_for(config)
    row, _ = store.create(
        RunRequest(workflow_id='demo', submission_id='quota-worker'),
        config,
        Path(__file__).resolve().parents[2] / 'configs/config.yaml',
    )

    def exhausted(*args: object) -> None:
        raise BudgetExceeded('private detail must stay private')

    monkeypatch.setattr(worker, 'execute_stage', exhausted)
    worker.run(store, row['id'])
    assert store.get(row['id'])['status'] == 'interrupted'
    events = store.events(row['id'])
    assert events[-1]['kind'] == 'quota_exhausted'
    assert 'private detail' not in str(events)


def test_worker_service_preserves_domain_errors(monkeypatch: object) -> None:
    import pytest

    import nowcast.cli as cli
    from nowcast.errors import BudgetExceeded
    from nowcast.worker import execute_stage

    def exhausted(*args: object) -> int:
        raise BudgetExceeded('quota')

    monkeypatch.setattr(cli, '_cmd_ingest', exhausted)
    with pytest.raises(BudgetExceeded):
        execute_stage(Path(__file__).resolve().parents[2] / 'configs/config.yaml', 'ingest')


def test_demo_index_is_identified_as_synthetic(config: Config) -> None:
    import json

    from fastapi.testclient import TestClient

    from nowcast.api import create_app

    path = Paths.from_config(config).resolve('demo/index.json')
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                'version': 'v1',
                'label': 'index-level proxies',
                'source': 'synthetic',
                'snapshots': [{'n_reported': 125, 'n_expected': 125}],
            }
        )
    )
    with TestClient(
        create_app(
            Path(__file__).resolve().parents[2] / 'configs/config.yaml', launch_workers=False
        ),
        base_url='http://127.0.0.1:8765',
    ) as client:
        result = client.get('/api/v1/index').json()
        assert result.get('source') == 'synthetic'
        assert result['snapshots'][0]['n_reported'] == 125


def test_smoke_reserves_requests_without_logging_response_bodies(
    config: Config, tmp_path: Path, monkeypatch: object, caplog: object
) -> None:
    import importlib.util

    import httpx
    from sqlalchemy import text

    from nowcast.jobs import store_for

    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / 'scripts'))
    spec = importlib.util.spec_from_file_location(
        'smoke_budget_test', root / 'scripts/smoke_llm.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'setup', lambda: config)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text='response-body-secret')
    )
    monkeypatch.setattr(
        module.httpx, 'Client', lambda **kwargs: client(transport=transport, **kwargs)
    )
    with caplog.at_level('INFO'):
        assert module.main(['--model', 'one:free', '--model', 'two:free']) == 0
    with store_for(config).engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM reservations')).scalar_one() == 2
    assert 'response-body-secret' not in caplog.text


def test_ingest_records_unvisited_plan_before_rejecting_unmapped_members(
    config: Config, monkeypatch: object
) -> None:
    import pandas as pd

    import nowcast.cli as cli
    from nowcast.paths import Paths

    root = Paths.from_config(config)
    members = root.resolve(config.data.constituents_csv)
    members.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                'ticker': 'VALID',
                'cik': '0000000001',
                'effective_from': '2025-01-01',
                'effective_to': '',
            },
            {
                'ticker': 'UNKNOWN',
                'cik': 'UNRESOLVED',
                'effective_from': '2025-01-01',
                'effective_to': '',
            },
        ]
    ).to_csv(members, index=False)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError('unmapped membership reached the SEC client')

    import nowcast.ingestion.edgar as edgar

    monkeypatch.setattr(edgar, 'ingest_edgar', refuse)
    code = cli.main(
        [
            'ingest',
            '--config',
            str(Path(__file__).resolve().parents[2] / 'configs/config.yaml'),
            '--set',
            'data.start_date=2025-01-01',
            '--set',
            'data.end_date=2025-03-31',
            '--set',
            'scope.profile=custom',
            '--set',
            'scope.companies=0',
            '--set',
            'scope.seasons=0',
        ]
    )
    assert code == 2
    planned = pd.read_csv(root.resolve('manifests/pair_outcomes.csv'))
    assert len(planned) == 2
    assert planned.outcome.eq('unvisited').all()
