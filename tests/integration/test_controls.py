from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nowcast.api import create_app
from nowcast.config import Config
from nowcast.contracts import Registry, RunRequest
from nowcast.errors import BudgetExceeded
from nowcast.jobs import JobStore, store_for
from nowcast.llm.throttle import SharedRequestLimiter
from nowcast.registry import load_registry

CONFIG = Path(__file__).resolve().parents[2] / 'configs/config.yaml'


def session(client: TestClient) -> dict[str, str]:
    token = client.get('/api/v1/session').json()['csrf_token']
    return {'x-tresata-csrf': token}


def test_controls_protect_mutations_and_duplicate_submissions(config: Config) -> None:
    with TestClient(
        create_app(CONFIG, launch_workers=False), base_url='http://127.0.0.1:8765'
    ) as client:
        body = {'workflow_id': 'demo', 'submission_id': 'abcdefgh'}
        assert client.post('/api/v1/runs', json=body).status_code == 403
        headers = session(client)
        first = client.post('/api/v1/runs', json=body, headers=headers)
        assert first.status_code == 202, first.text
        second = client.post('/api/v1/runs', json=body, headers=headers)
        assert second.json()['id'] == first.json()['id']
        assert (
            client.post(
                '/api/v1/runs', json={**body, 'shell': 'anything'}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.get('/api/v1/runs', headers={'Origin': 'https://evil.invalid'}).status_code
            == 403
        )
        assert client.get('/api/v1/trace').status_code == 403
        assert client.get('/api/v1/index').json()['snapshots'] == []
        assert not {'config_path', 'fingerprint', 'pid'} & first.json().keys()
        assert client.get('/api/v1/runs', headers={'Host': 'evil.invalid'}).status_code == 403
        assert client.post(
            '/api/v1/runs/' + first.json()['id'] + '/cancel', headers=headers
        ).json()['cancel_requested']


@pytest.mark.parametrize('host', ['192.168.1.50', '100.64.0.2', 'workstation-test'])
def test_network_access_retains_host_origin_and_csrf_checks(
    config: Config, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setattr('socket.gethostname', lambda: 'workstation-test')
    origin = f'http://{host}:8767'
    with TestClient(create_app(CONFIG, launch_workers=False), base_url=origin) as client:
        response = client.get('/api/v1/session')
        assert response.status_code == 200
        headers = {'x-tresata-csrf': response.json()['csrf_token'], 'Origin': origin}
        body = {'workflow_id': 'demo', 'submission_id': 'network-access-check'}
        assert client.post('/api/v1/runs', json=body).status_code == 403
        assert client.post('/api/v1/runs', json=body, headers=headers).status_code == 202
        assert client.get('/api/v1/session', headers={'Host': 'evil.invalid'}).status_code == 403
        assert client.get('/api/v1/session', headers={'Host': '203.0.113.42'}).status_code == 403
        assert (
            client.get('/api/v1/runs', headers={'Origin': 'https://evil.invalid'}).status_code
            == 403
        )


def test_restart_reconciles_dead_workers(config: Config) -> None:
    store = store_for(config)
    row, _ = store.create(
        RunRequest(workflow_id='demo', submission_id='restart-check'), config, CONFIG
    )
    store.update(row['id'], status='running', pid=99999999, identity='missing')
    restarted = JobStore(store.path)
    restarted.reconcile()
    assert restarted.get(row['id'])['status'] == 'interrupted'
    restarted.resume(row['id'], config)
    assert restarted.get(row['id'])['status'] == 'queued'


def test_shared_daily_quota_is_transactional(config: Config) -> None:
    store = store_for(config)

    def reserve(_: int) -> bool:
        limiter = SharedRequestLimiter(store, 'provider', 20, 3)
        try:
            limiter.acquire()
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reserve, range(10)))
    assert sum(results) == 3
    with pytest.raises(BudgetExceeded):
        SharedRequestLimiter(JobStore(store.path), 'provider', 20, 3).acquire()


def test_registry_rejects_malformed_graphs(config: Config) -> None:
    registry = load_registry(config)
    raw = registry.model_dump()
    raw['workflows'][0]['edges'].append(('aggregate', 'validate-config'))
    with pytest.raises(ValueError):
        Registry.model_validate(raw)
    raw = registry.model_dump()
    raw['workflows'][0]['nodes'].append('nowcast')
    with pytest.raises(ValueError):
        Registry.model_validate(raw)


def test_worker_cancellation_and_public_events(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nowcast.worker import run

    store = store_for(config)
    row, _ = store.create(
        RunRequest(workflow_id='demo', submission_id='cancel-worker'), config, CONFIG
    )
    store.cancel(row['id'])
    monkeypatch.setenv('NOWCAST_JOB_DATABASE', str(store.path))
    monkeypatch.setenv('NOWCAST_JOB_ID', row['id'])
    run(store, row['id'])
    assert store.get(row['id'])['status'] == 'cancelled'
    assert store.events(row['id'])[-1]['kind'] == 'cancelled'


def test_worker_uses_the_shared_stage_service(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nowcast.worker as worker

    store = store_for(config)
    row, _ = store.create(
        RunRequest(workflow_id='demo', submission_id='success-worker'), config, CONFIG
    )
    stages = []
    monkeypatch.setattr(worker, 'execute_stage', lambda path, stage: stages.append(stage))
    import nowcast.artifacts as artifacts

    monkeypatch.setattr(artifacts, 'record_artifacts', lambda *args: None)
    monkeypatch.setenv('NOWCAST_JOB_DATABASE', str(store.path))
    monkeypatch.setenv('NOWCAST_JOB_ID', row['id'])
    worker.run(store, row['id'])
    assert stages == ['demo']
    assert store.get(row['id'])['status'] == 'succeeded'


def test_inspector_rejects_stale_upstream_artifacts(config: Config, tmp_path: Path) -> None:
    from nowcast.artifacts import record_artifacts

    store = store_for(config)
    row, _ = store.create(
        RunRequest(workflow_id='production', submission_id='upstream-record'), config, CONFIG
    )
    record_artifacts(store, row['id'], 'validate-config', config, CONFIG)
    store.update(row['id'], status='succeeded')
    request = RunRequest(
        workflow_id='production',
        submission_id='node-inspection',
        node_id='build-constituents',
        upstream_run_id=row['id'],
    )
    created, _ = store.create(request, config, CONFIG)
    assert created['total'] == 1
    store.update(created['id'], status='succeeded')
    with store.engine.begin() as connection:
        from sqlalchemy import text

        connection.execute(text("UPDATE artifacts SET config_fingerprint='stale'"))
    with pytest.raises(ValueError, match='fingerprint'):
        store.create(
            RunRequest(
                workflow_id='production',
                submission_id='stale-inspection',
                node_id='build-constituents',
                upstream_run_id=row['id'],
            ),
            config,
            CONFIG,
        )


def test_index_contract_rejects_identifier_exports() -> None:
    from nowcast.contracts import IndexSnapshot

    for row in (
        {'cik': '0000000001'},
        {'tone_score_mean': 'private-company'},
        {'metric_status_tone_score_mean': 'private-company'},
    ):
        with pytest.raises(ValueError):
            IndexSnapshot(snapshots=[row])


def test_node_parameter_bindings_match_configuration(config: Config) -> None:
    registry = load_registry(config)
    extraction = next(node for node in registry.nodes if node.id == 'extract')
    assert (
        next(p.value for p in extraction.parameters if p.config_path == 'llm.max_tokens')
        == config.llm.max_tokens
    )
    raw = registry.model_dump()
    raw['nodes'][0]['parameters'] = [{'label': 'secret', 'config_path': 'llm.api_key_env'}]
    with pytest.raises(ValueError):
        Registry.model_validate(raw)


def test_optimise_distinguishes_unknown_tokens_and_utc_reservations(config: Config) -> None:
    import pandas as pd

    from nowcast.paths import Paths

    ledger = Paths.from_config(config).resolve(config.budget.ledger_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                'outcome': 'ok',
                'request_kind': 'completion',
                'prompt_tokens': 100,
                'completion_tokens': 200,
                'reasoning_tokens': None,
            },
            {
                'outcome': 'ok',
                'request_kind': 'completion',
                'prompt_tokens': 300,
                'completion_tokens': 400,
                'reasoning_tokens': 20,
            },
            {
                'outcome': 'ok',
                'request_kind': 'cache',
                'prompt_tokens': 999,
                'completion_tokens': 999,
                'reasoning_tokens': 999,
            },
        ]
    ).to_parquet(ledger, index=False)
    SharedRequestLimiter(store_for(config), config.llm.base_url, 20, 50).acquire()
    with TestClient(
        create_app(CONFIG, launch_workers=False), base_url='http://127.0.0.1:8765'
    ) as client:
        result = client.get('/api/v1/optimise').json()
    assert result['recorded_prompt_tokens'] == 400
    assert result['recorded_completion_tokens'] == 600
    assert result['recorded_reasoning_tokens'] == 20
    assert result['reasoning_tokens_measured_attempts'] == 1
    assert result['recorded_content_tokens'] is None
    assert result['content_tokens_measured_attempts'] == 0
    assert result['utc_requests_reserved'] == 1
    assert result['configured_daily_request_limit'] == config.llm.requests_per_day
