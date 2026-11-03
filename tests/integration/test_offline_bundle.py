from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nowcast.api import create_app
from nowcast.contracts import (
    IndexSnapshot,
    KPIKnowledgeBase,
    MetricSnapshot,
    ScheduleSnapshot,
    StageSnapshot,
)
from nowcast.offline import PUBLIC_FILES, saved_snapshot
from nowcast.paths import Paths

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / 'data/offline'


def test_public_bundle_is_complete_and_has_no_private_artifacts():
    manifest = json.loads((BUNDLE / 'manifest.json').read_text())
    assert manifest['partial'] is True
    assert set(manifest['files']) == set(PUBLIC_FILES) - {'manifest.json'}
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest() == digest
    assert not any(name.startswith(('raw/', 'extractions/', 'inputs/')) for name in PUBLIC_FILES)
    assert not any(name.endswith(('.sqlite', '.log', '.zip')) for name in PUBLIC_FILES)


def test_only_the_public_bundle_is_unignored():
    private = {
        'data/raw/filing.htm',
        'data/inputs/labels.csv',
        'data/offline/.env',
        'data/offline/jobs.sqlite',
        'data/offline/raw/private.json',
        'data/offline/exports/private.json',
        'data/offline/snapshots/private.json',
        'data/offline/aggregates/private.parquet',
    }
    candidates = [*(f'data/offline/{name}' for name in PUBLIC_FILES), *private]
    result = subprocess.run(
        ['git', 'check-ignore', '--no-index', '--stdin'],
        cwd=ROOT,
        input='\n'.join(candidates) + '\n',
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == private


def test_real_public_data_is_viewable_offline_without_keys(tmp_path, monkeypatch):
    for name in PUBLIC_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUNDLE / name, target)
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    monkeypatch.delenv('NOWCAST_INTERNAL_TRACE', raising=False)
    with TestClient(
        create_app(BUNDLE / 'config.yaml', launch_workers=False),
        base_url='http://127.0.0.1:18765',
    ) as client:
        models = {
            'index': IndexSnapshot,
            'kpis': KPIKnowledgeBase,
            'stages': StageSnapshot,
            'coverage': MetricSnapshot,
            'cost': MetricSnapshot,
            'bakeoff': MetricSnapshot,
            'plan': MetricSnapshot,
            'schedule': ScheduleSnapshot,
        }
        for name, model in models.items():
            response = client.get('/api/v1/' + name)
            assert response.status_code == 200
            model.model_validate(response.json())
            folder = 'exports' if name in {'index', 'kpis'} else 'snapshots'
            assert response.json() == json.loads((BUNDLE / folder / f'{name}.json').read_text())
        assert client.get('/api/v1/index').json()['source'] == 'pipeline'
        assert client.get('/api/v1/nodes/aggregate/output').json()['total'] > 0
        session = client.get('/api/v1/session').json()
        assert session['internal_trace_available'] is False
        assert session['read_only'] is True
        assert client.get('/api/v1/records/private/evidence').status_code == 403
        response = client.post(
            '/api/v1/runs',
            json={'workflow_id': 'demo', 'submission_id': 'offline-view'},
            headers={'x-tresata-csrf': session['csrf_token']},
        )
        assert response.status_code == 409
        assert client.get('/api/v1/runs').json() == []
    assert not (tmp_path / 'raw').exists()
    assert not (tmp_path / 'extractions').exists()


def test_offline_snapshots_are_schema_checked_and_do_not_override_live_data(config):
    path = Paths.from_config(config).resolve('snapshots/cost.json')
    path.parent.mkdir(parents=True)
    Paths.from_config(config).resolve('manifest.json').write_text(
        '{"kind":"public-offline-snapshot"}'
    )
    path.write_text('{"metrics":{"p50":12.5}}')
    live = dataclasses.replace(config, llm=dataclasses.replace(config.llm, offline=False))
    offline = dataclasses.replace(config, llm=dataclasses.replace(config.llm, offline=True))
    assert saved_snapshot(live, 'cost', MetricSnapshot) is None
    assert saved_snapshot(offline, 'cost', MetricSnapshot).metrics['p50'] == 12.5
    path.write_text('{"metrics":{"p50":"invalid"},"cik":"private"}')
    with pytest.raises(ValidationError):
        saved_snapshot(offline, 'cost', MetricSnapshot)
    with pytest.raises(ValueError, match='unknown public snapshot'):
        saved_snapshot(offline, '../private', MetricSnapshot)
