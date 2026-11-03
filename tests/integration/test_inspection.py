from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from nowcast.api import create_app
from nowcast.cli import main
from nowcast.cli_registry import catalogue
from nowcast.config import ScopeConfig
from nowcast.contracts import (
    GraphDocument,
    KPIKnowledgeBase,
    MetricSnapshot,
    PaneResponse,
    StageSnapshot,
)
from nowcast.extraction.runner import model_slug
from nowcast.extraction.schema import ExtractionRecord, NumField
from nowcast.paths import Paths
from nowcast.workflow_registry import canvas_registry

CONFIG = Path(__file__).resolve().parents[2] / 'configs/config.yaml'


def test_empty_checkout_can_open_dashboard_before_the_first_run(config):
    with TestClient(create_app(CONFIG, launch_workers=False)) as client:
        for endpoint in (
            'session',
            'registry',
            'index',
            'stages',
            'coverage',
            'cost',
            'bakeoff',
            'plan',
            'schedule',
        ):
            response = client.get('/api/v1/' + endpoint)
            assert response.status_code == 200, (endpoint, response.text)
        stages = client.get('/api/v1/stages').json()
        assert next(n for n in stages['nodes'] if n['id'] == 'extract')['out_count'] is None
        assert client.get('/api/v1/nodes/build-constituents/input').status_code == 200


@pytest.fixture
def corpus(config, monkeypatch):
    config = dataclasses.replace(config, scope=ScopeConfig())
    monkeypatch.setattr('nowcast.api.load_config', lambda path: config)
    paths = Paths.from_config(config)
    raw = paths.resolve('raw/doc.htm')
    raw.parent.mkdir(parents=True)
    raw.write_text(
        '<table><tr><th>Metric</th><th>2025</th></tr><tr><td>EPS</td><td>1.20</td></tr><tr><td>Other</td><td>9.90</td></tr></table>'
    )
    pd.DataFrame(
        [
            {
                'document_id': 'private-record',
                'cik': '0000000001',
                'report_date': '2025-04-10',
                'document_type': 'EX-99.1',
                'source': 'edgar',
                'raw_path': 'raw/doc.htm',
                'sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
                'chars': len(raw.read_text()),
                'downloaded_at': '2025-04-10',
                'items': '2.02',
            }
        ]
    ).to_parquet(paths.resolve(config.data.document_index), index=False)
    from nowcast.parsing.html import html_to_text

    quote = next(line for line in html_to_text(raw.read_text()).splitlines() if 'EPS' in line)
    record = ExtractionRecord(
        schema_version='v1',
        document_id='private-record',
        fiscal_year=2025,
        fiscal_quarter=1,
        reported_eps=NumField(value=9.90, evidence_quote=quote, confidence=0.9),
    )
    folder = paths.extractions(config) / model_slug(config.llm.models[0])
    folder.mkdir(parents=True)
    (folder / 'private-record.json').write_text(
        json.dumps(
            {
                'document_id': 'private-record',
                'model': config.llm.models[0],
                'record': record.model_dump(),
                'diagnostics': {},
            }
        )
    )
    return config


def client_for():
    return TestClient(create_app(CONFIG, launch_workers=False), base_url='http://127.0.0.1:18765')


def test_registry_cli_flags_and_served_build_have_exact_parity(config):
    registry = canvas_registry()
    nodes = {n.id: n for n in registry.nodes}
    for command in catalogue():
        assert command['id'] in nodes
        assert [c.model_dump() for c in nodes[command['id']].controls] == command['controls']
    built = json.loads((CONFIG.parents[1] / 'web/src/registry.json').read_text())
    assert registry.model_dump(mode='json') == built
    with client_for() as client:
        assert client.get('/api/v1/registry').json() == built


def test_index_projections_have_no_private_identifiers_and_schemas_validate(corpus):
    with client_for() as client:
        for stage in [
            'ingest',
            'parse',
            'extract',
            'validate',
            'consolidate',
            'build-constituents',
        ]:
            response = client.get(f'/api/v1/nodes/{stage}/output')
            assert response.status_code == 200, response.text
            parsed = PaneResponse.model_validate(response.json())
            assert all(
                not {'document_id', 'cik', 'ticker', 'company', 'sector'} & row.keys()
                for row in parsed.rows
            )
            assert 'private-record' not in response.text and '0000000001' not in response.text
        for name in ['coverage', 'cost', 'plan', 'bakeoff']:
            MetricSnapshot.model_validate(client.get('/api/v1/' + name).json())
        StageSnapshot.model_validate(client.get('/api/v1/stages').json())
        KPIKnowledgeBase.model_validate(client.get('/api/v1/kpis').json())
        assert client.get('/api/v1/records/private-record/evidence').status_code == 403
        assert client.get('/api/v1/nodes/unknown/output').status_code == 404
        assert client.get('/api/v1/nodes/ingest/output?limit=1000').status_code == 422


def test_real_releases_take_precedence_over_demo_when_kpis_are_unavailable(corpus):
    path = Paths.from_config(corpus).resolve('demo/index.json')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'source': 'synthetic', 'snapshots': []}))
    with client_for() as client:
        snapshot = client.get('/api/v1/index').json()
        assert snapshot['source'] == 'pipeline'
        assert snapshot['status'] == 'unavailable'


def test_public_bakeoff_pane_does_not_serialize_private_sample_identifiers(corpus):
    path = Paths.from_config(corpus).manifests(corpus) / 'bakeoff/private/scores.json'
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                'documents': {'per_company': {'0000000001': 1}},
                'models': [{'model': 'synthetic:free', 'parse_success_rate': 1.0}],
            }
        )
    )
    with client_for() as client:
        response = client.get('/api/v1/nodes/model-bakeoff/output')
        assert response.status_code == 200
        assert '0000000001' not in response.text
        assert response.json()['rows'][0]['model'] == 'synthetic:free'


def test_label_sheet_uses_only_current_index_scope(corpus, monkeypatch):
    monkeypatch.setattr('nowcast.cli._load', lambda args: corpus)
    monkeypatch.setattr(
        'nowcast.extraction.runner.consolidate',
        lambda *args: pd.DataFrame(
            [
                {'document_id': 'private-record', 'cik': '0000000001'},
                {'document_id': 'orphaned-old-season', 'cik': '0000000001'},
            ]
        ),
    )
    assert main(['prepare-labels', '--config', str(CONFIG)]) == 0
    sheet = json.loads(Paths.from_config(corpus).resolve('inputs/label-sheet.json').read_text())
    assert [row['document_id'] for row in sheet['records']] == ['private-record']


def test_inspector_names_the_upstream_artifact_it_reads(corpus):
    with client_for() as client:
        response = client.get('/api/v1/nodes/extract/input')
        assert response.status_code == 200
        assert response.json()['upstream'][0] == 'parse'


def test_running_stage_does_not_report_startup_time_as_completed_duration(corpus):
    import os

    from nowcast.contracts import RunRequest
    from nowcast.jobs import process_identity, store_for

    with client_for() as client:
        store = store_for(corpus)
        row, _ = store.create(
            RunRequest(
                workflow_id='command', command_id='extract', submission_id='duration-regression'
            ),
            corpus,
            CONFIG,
        )
        assert store.claim(row['id'])
        store.update(
            row['id'], stage='extract', pid=os.getpid(), identity=process_identity(os.getpid())
        )
        store.event(row['id'], 'extract', 'started')
        state = next(
            node for node in client.get('/api/v1/stages').json()['nodes'] if node['id'] == 'extract'
        )
        assert state['status'] == 'running'
        assert state['duration'] is None
        alias = next(
            node
            for node in client.get('/api/v1/stages').json()['nodes']
            if node['id'] == 'extract-step'
        )
        assert alias['status'] == 'running'
        assert alias['last_run'] == row['id']


def test_evidence_rejects_number_in_another_row_and_labels_are_csrf_protected(corpus, monkeypatch):
    monkeypatch.setenv('NOWCAST_INTERNAL_TRACE', '1')
    with client_for() as client:
        headers = {'x-tresata-trace': 'session'}
        response = client.get('/api/v1/records/private-record/evidence', headers=headers)
        assert response.status_code == 200, response.text
        eps = next(f for f in response.json()['fields'] if f['field'] == 'reported_eps')
        assert eps['number_present'] is False
        assert 'number_not_in_quote' in eps['issues']
        assert response.json()['source'][eps['start'] : eps['end']] == eps['quote']
        body = {
            'record_id': 'private-record',
            'field': 'reported_eps',
            'value': 9.9,
            'verdict': 'wrong',
        }
        assert client.post('/api/v1/labels', json=body, headers=headers).status_code == 403
        token = client.get('/api/v1/session').json()['csrf_token']
        headers['x-tresata-csrf'] = token
        assert (
            client.post('/api/v1/labels', json={**body, 'value': 123}, headers=headers).status_code
            == 409
        )
        assert client.post('/api/v1/labels', json=body, headers=headers).json()['checked'] == 1
        assert (
            client.post(
                '/api/v1/labels', json={**body, 'verdict': 'correct'}, headers=headers
            ).status_code
            == 200
        )
        labels = pd.read_csv(Paths.from_config(corpus).resolve('inputs/labels.csv'))
        assert len(labels) == 1 and labels.iloc[0].verdict == 'correct'
        assert 'timestamp' in labels and labels.iloc[0]['field'] == 'reported_eps'
        assert (
            client.get('/api/v1/records/private-record/evidence', headers=headers).json()[
                'verdicts'
            ]['reported_eps']
            == 'correct'
        )
        assert (
            client.post('/api/v1/labels', json=body, headers={'x-tresata-csrf': token}).status_code
            == 403
        )


def test_phase_parse_consolidate_and_review_use_real_artifacts(corpus, monkeypatch):
    monkeypatch.setattr('nowcast.cli._load', lambda args: corpus)
    for phase in ['parse', 'validate', 'review', 'consolidate']:
        assert main([phase]) == 0
        assert Paths.from_config(corpus).resolve('manifests/stages/' + phase + '.parquet').exists()
    assert (
        pd.read_parquet(Paths.from_config(corpus).resolve('manifests/stages/parse.parquet'))
        .iloc[0]
        .chars
        > 0
    )


def test_graph_rejects_cycles_extra_data_and_unknown_ports():
    from pydantic import ValidationError

    valid = {
        'nodes': [{'id': 'ingest', 'x': 0, 'y': 0}, {'id': 'extract', 'x': 100, 'y': 0}],
        'edges': [{'source': 'ingest', 'target': 'extract'}],
    }
    GraphDocument.model_validate(valid)
    for bad in [
        {**valid, 'document_id': 'secret'},
        {**valid, 'edges': [{'source': 'extract', 'target': 'extract'}]},
        {**valid, 'edges': [{'source': 'ingest', 'target': 'missing'}]},
    ]:
        with pytest.raises(ValidationError):
            GraphDocument.model_validate(bad)


def test_index_knowledge_base_keeps_suppression_and_provenance(corpus):
    from nowcast.knowledge import knowledge_base

    paths = Paths.from_config(corpus)
    paths.aggregates(corpus).mkdir(parents=True)
    pd.DataFrame(
        [
            {
                'season_year': 2025,
                'season_quarter': 1,
                'as_of_date': '2025-04-10',
                'n_expected': 40,
                'n_obs_growth': 4,
                'eps_growth_agg': 12,
                'metric_status_eps_growth_agg': 'ok',
                'suppressed': True,
            }
        ]
    ).to_parquet(paths.aggregates(corpus) / 'index_aggregates.parquet')
    result = knowledge_base(corpus, write=True)
    assert len(result.records) == 4
    assert all(row.value is None and row.status == 'suppressed' for row in result.records)
    assert result.records[0].coverage == 0.1
    assert result.records[0].source_hash
    assert Paths.from_config(corpus).resolve('exports/kpis.json').is_file()


def test_inspector_command_validates_upstream_again_under_worker_lock(corpus, monkeypatch):
    from nowcast.artifacts import record_artifacts
    from nowcast.contracts import RunRequest
    from nowcast.jobs import store_for
    from nowcast.worker import run

    store = store_for(corpus)
    request = RunRequest(
        workflow_id='command',
        submission_id='inspect-parse-0001',
        command_id='parse',
        node_id='parse',
    )
    with pytest.raises(ValueError, match='upstream'):
        store.create(request, corpus, CONFIG)
    root, _ = store.create(
        RunRequest(
            workflow_id='command', submission_id='inspect-download-0001', command_id='download'
        ),
        corpus,
        CONFIG,
    )
    from nowcast.phase_services import phase_path
    from nowcast.storage import atomic_parquet

    atomic_parquet(
        pd.read_parquet(Paths.from_config(corpus).resolve(corpus.data.document_index)),
        phase_path(corpus, 'download'),
    )
    record_artifacts(store, root['id'], 'download', corpus, CONFIG)
    store.update(root['id'], status='succeeded')
    request = request.model_copy(update={'upstream_run_id': root['id']})
    row, _ = store.create(request, corpus, CONFIG)
    with phase_path(corpus, 'download').open('ab') as output:
        output.write(b'changed')
    monkeypatch.setattr('nowcast.worker.load_config', lambda path: corpus)
    monkeypatch.setattr('nowcast.cli._load', lambda args: corpus)
    run(store, row['id'])
    assert store.get(row['id'])['status'] == 'failed'
    assert not Paths.from_config(corpus).resolve('manifests/stages/parse.parquet').exists()


def test_run_all_is_the_canonical_cli_stage_order(corpus):
    from nowcast.contracts import RunRequest
    from nowcast.jobs import store_for
    from nowcast.phase_services import RUN_ALL_STAGES

    row, _ = store_for(corpus).create(
        RunRequest(workflow_id='command', submission_id='canonical-run-all', command_id='run-all'),
        corpus,
        CONFIG,
    )
    assert json.loads(row['stages']) == list(RUN_ALL_STAGES)


def test_cli_rejects_paid_override_before_any_provider_call(corpus, monkeypatch):
    monkeypatch.setattr('nowcast.cli._load', lambda args: corpus)
    monkeypatch.setattr(
        'nowcast.extraction.bakeoff.run_bakeoff',
        lambda *args, **kwargs: pytest.fail('provider path reached'),
    )
    assert main(['model-bakeoff', '--model', 'paid/model']) == 2


def test_runtime_bindings_are_typed_and_never_include_secrets(corpus):
    from nowcast.contracts import SettingsResponse

    with client_for() as client:
        raw = client.get('/api/v1/settings')
        result = SettingsResponse.model_validate(raw.json())
        assert result.nodes['model'][0].path == 'llm.models'
        assert not any(
            'api_key' in control.path or control.path.endswith('_env')
            for controls in result.nodes.values()
            for control in controls
        )


def test_provider_key_in_mutation_is_rejected_without_echo(corpus, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fake-private-provider-value')
    with client_for() as client:
        token = client.get('/api/v1/session').json()['csrf_token']
        response = client.post(
            '/api/v1/runs',
            json={
                'workflow_id': 'command',
                'submission_id': 'secret-guard-0001',
                'command_id': 'extract',
                'parameters': {'set': ['llm.app_name=fake-private-provider-value']},
            },
            headers={'x-tresata-csrf': token},
        )
        assert response.status_code == 422
        assert 'fake-private-provider-value' not in response.text


def test_selected_run_evidence_remains_immutable_when_latest_facts_change(corpus, monkeypatch):
    from nowcast.artifacts import record_artifacts
    from nowcast.contracts import RunRequest
    from nowcast.jobs import store_for

    monkeypatch.setenv('NOWCAST_INTERNAL_TRACE', '1')
    store = store_for(corpus)
    row, _ = store.create(
        RunRequest(
            workflow_id='command', submission_id='immutable-evidence-run', command_id='extract'
        ),
        corpus,
        CONFIG,
    )
    paths = Paths.from_config(corpus)
    pd.DataFrame([{'document_id': 'private-record', 'reported_eps': 9.9}]).to_parquet(
        paths.extractions(corpus) / 'extractions.parquet'
    )
    record_artifacts(store, row['id'], 'extract', corpus, CONFIG)
    store.update(row['id'], status='succeeded')
    raw = paths.extractions(corpus) / model_slug(corpus.llm.models[0]) / 'private-record.json'
    payload = json.loads(raw.read_text())
    payload['record']['reported_eps']['value'] = 1.2
    raw.write_text(json.dumps(payload))
    with client_for() as client:
        headers = {'x-tresata-trace': 'session'}
        current = client.get('/api/v1/records/private-record/evidence', headers=headers).json()
        previous = client.get(
            '/api/v1/records/private-record/evidence?run=' + row['id'], headers=headers
        ).json()
        assert current['fields'][0]['value'] == 1.2
        assert previous['fields'][0]['value'] == 9.9
        assert previous['fields'][0]['number_present'] is False
        assert (
            client.get('/api/v1/records/private-record/evidence?run=' + row['id']).status_code
            == 403
        )


@pytest.mark.parametrize('source_stage', ['ingest', 'download', 'rebuild-index'])
def test_individual_parse_accepts_equivalent_file_producers(corpus, monkeypatch, source_stage):
    from nowcast.artifacts import latest_upstream, record_artifacts
    from nowcast.contracts import RunRequest
    from nowcast.jobs import store_for
    from nowcast.phase_services import phase_path
    from nowcast.worker import run

    store = store_for(corpus)
    if source_stage == 'download':
        phase_path(corpus, 'download').parent.mkdir(parents=True, exist_ok=True)
        pd.read_parquet(Paths.from_config(corpus).resolve(corpus.data.document_index)).to_parquet(
            phase_path(corpus, 'download')
        )
    root, _ = store.create(
        RunRequest(
            workflow_id='command',
            command_id=source_stage,
            submission_id='equivalent-source-' + source_stage,
        ),
        corpus,
        CONFIG,
    )
    record_artifacts(store, root['id'], source_stage, corpus, CONFIG)
    store.update(root['id'], status='succeeded')
    assert latest_upstream(store, corpus, 'parse') == (root['id'], source_stage)
    with client_for() as client:
        data = client.get('/api/v1/nodes/parse/input').json()
        assert data['runs'] == [root['id']]
        assert data['upstream'][0] == source_stage
    row, _ = store.create(
        RunRequest(
            workflow_id='command',
            command_id='parse',
            node_id='parse',
            upstream_run_id=root['id'],
            submission_id='equivalent-parse-' + source_stage,
        ),
        corpus,
        CONFIG,
    )
    monkeypatch.setattr('nowcast.worker.load_config', lambda path: corpus)
    monkeypatch.setattr('nowcast.cli._load', lambda args: corpus)
    run(store, row['id'])
    assert store.get(row['id'])['status'] == 'succeeded'
    assert phase_path(corpus, 'parse').is_file()
    # Equivalent producers still require unchanged, fingerprinted files.
    from nowcast.artifacts import stage_files

    with stage_files(corpus, CONFIG, source_stage)[0].open('ab') as output:
        output.write(b'changed')
    assert latest_upstream(store, corpus, 'parse', source_stage) is None
    with pytest.raises(ValueError, match='upstream artifacts changed'):
        store.create(
            RunRequest(
                workflow_id='command',
                command_id='parse',
                node_id='parse',
                upstream_run_id=root['id'],
                submission_id='stale-parse-' + source_stage,
            ),
            corpus,
            CONFIG,
        )


def test_aggregate_accepts_the_combined_extraction_output(corpus):
    from nowcast.artifacts import record_artifacts
    from nowcast.contracts import RunRequest
    from nowcast.jobs import store_for

    store = store_for(corpus)
    target = Paths.from_config(corpus).extractions(corpus) / 'extractions.parquet'
    pd.DataFrame([{'document_id': 'private-record', 'reported_eps': 1.2}]).to_parquet(target)
    root, _ = store.create(
        RunRequest(
            workflow_id='command', command_id='extract', submission_id='combined-extract-root'
        ),
        corpus,
        CONFIG,
    )
    record_artifacts(store, root['id'], 'extract', corpus, CONFIG)
    store.update(root['id'], status='succeeded')
    with client_for() as client:
        data = client.get('/api/v1/nodes/aggregate/input').json()
        assert data['runs'] == [root['id']]
        assert data['upstream'][0] == 'extract'
    row, _ = store.create(
        RunRequest(
            workflow_id='command',
            command_id='aggregate',
            node_id='aggregate',
            upstream_run_id=root['id'],
            submission_id='combined-aggregate',
        ),
        corpus,
        CONFIG,
    )
    assert row['status'] == 'queued'


@pytest.mark.parametrize(
    'command',
    ['supersede-stale', 'schedule-plan', 'schedule-status', 'schedule-pause', 'schedule-resume'],
)
def test_nonfile_actions_report_completion_and_readable_output(corpus, monkeypatch, command):
    from nowcast.artifacts import stage_files
    from nowcast.contracts import RunRequest
    from nowcast.jobs import store_for
    from nowcast.worker import run

    store = store_for(corpus)
    row, _ = store.create(
        RunRequest(
            workflow_id='command',
            command_id=command,
            node_id=command,
            submission_id='completion-' + command,
        ),
        corpus,
        CONFIG,
    )
    monkeypatch.setattr('nowcast.worker.load_config', lambda path: corpus)
    monkeypatch.setattr('nowcast.cli._load', lambda args: corpus)
    run(store, row['id'])
    assert store.get(row['id'])['status'] == 'succeeded'
    assert json.loads(stage_files(corpus, CONFIG, command)[0].read_text())['status'] == 'succeeded'
    with client_for() as client:
        data = client.get('/api/v1/nodes/' + command + '/output').json()
        assert data['total'] == 1
        assert data['rows'][0]['status'] == 'succeeded'
        assert len(data['rows'][0]) >= 3


def test_empty_extraction_cannot_publish_old_records_as_a_new_success(corpus, monkeypatch):
    from nowcast.errors import DataError
    from nowcast.worker import execute_stage

    monkeypatch.setattr('nowcast.cli._load', lambda args: corpus)
    monkeypatch.setattr('nowcast.extraction.runner.load_documents', lambda *args: [])
    target = Paths.from_config(corpus).extractions(corpus) / 'extractions.parquet'
    pd.DataFrame([{'document_id': 'old-record'}]).to_parquet(target)
    before = target.read_bytes()
    with pytest.raises(DataError, match='no documents to extract'):
        execute_stage(CONFIG, 'extract')
    assert target.read_bytes() == before


def test_failed_nonfile_action_has_no_success_receipt(corpus, monkeypatch):
    from nowcast.artifacts import stage_files
    from nowcast.contracts import RunRequest
    from nowcast.jobs import store_for
    from nowcast.worker import run

    store = store_for(corpus)
    row, _ = store.create(
        RunRequest(
            workflow_id='command',
            command_id='schedule-pause',
            node_id='schedule-pause',
            submission_id='failed-completion-receipt',
        ),
        corpus,
        CONFIG,
    )
    monkeypatch.setattr('nowcast.worker.load_config', lambda path: corpus)

    def fail(*args):
        raise RuntimeError('controlled failure')

    monkeypatch.setattr('nowcast.worker.execute_stage', fail)
    run(store, row['id'])
    assert store.get(row['id'])['status'] == 'failed'
    assert not stage_files(corpus, CONFIG, 'schedule-pause')[0].exists()
