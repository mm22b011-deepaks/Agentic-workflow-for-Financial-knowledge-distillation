"""N2: the bakeoff table is built offline from a fake transport."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import httpx
import pytest

from nowcast.config import Config
from nowcast.extraction.bakeoff import FIELDS, run_bakeoff
from nowcast.llm.caller import LLMCaller
from nowcast.llm.composition import RetryingCaller


@pytest.fixture
def config(config):
    from nowcast.config import ScopeConfig

    return dataclasses.replace(config, scope=ScopeConfig())


REPLY = json.dumps(
    {
        'schema_version': 'v1',
        'document_id': 'x',
        'currency': 'USD',
        'units': 'USD billion',
        'reported_eps': {
            'value': 0.55,
            'evidence_quote': 'earnings per share were $0.55',
            'confidence': 0.9,
        },
        'revenue': {
            'value': 1.2,
            'evidence_quote': 'Revenue was $1.20 billion',
            'confidence': 0.9,
        },
        'tone': {
            'value': 'neutral',
            'evidence_quote': 'Revenue was $1.20 billion',
            'confidence': 0.9,
        },
    }
)


def _index(tmp_path: Path, documents: int = 3) -> Path:
    """Write an index and the raw files it names."""
    import pandas as pd

    rows = []
    raw = tmp_path / 'raw'
    raw.mkdir()
    for index in range(documents):
        path = raw / f'doc{index}.htm'
        path.write_text(
            '<html><body>Revenue was $1.20 billion. GAAP earnings per share were $0.55.'
            '</body></html>',
            encoding='utf-8',
        )
        rows.append(
            {
                'document_id': f'doc{index}',
                'cik': f'{index + 1:010d}',
                'report_date': '2025-04-20',
                'document_type': 'EX-99.1',
                'source': 'edgar',
                'raw_path': str(path),
                'sha256': f'h{index}',
                'chars': 100,
                'downloaded_at': '2025-04-20T00:00:00+00:00',
                'items': '2.02,9.01',
            }
        )
    target = tmp_path / 'index.parquet'
    pd.DataFrame(rows).to_parquet(target, index=False)
    return target


def test_bakeoff_writes_a_table_without_network(
    config: Config, tmp_path: Path, monkeypatch: object
) -> None:
    """The table carries one row per model, with coverage and a rate per column."""
    index = _index(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': []}, request=request)
        return httpx.Response(
            200,
            json={
                'model': 'fake/model:free',
                'choices': [{'message': {'content': REPLY}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
            },
            request=request,
        )

    import nowcast.llm.composition as composition

    def fake_make_caller(_config: Config, *args: object, **kwargs: object) -> RetryingCaller:
        inner = LLMCaller(_config.llm, transport=httpx.MockTransport(handler))
        return RetryingCaller(
            inner, composition.ResponseCache(_config.cache, tmp_path / 'cache'), _config
        )

    monkeypatch.setattr(composition, 'make_caller', fake_make_caller)  # type: ignore[attr-defined]
    table = run_bakeoff(config, ['fake/model:free'], index, count=3)
    assert len(table['models']) == 1
    row = table['models'][0]
    assert row['documents'] == 3
    assert row['parse_success_rate'] == 1.0
    assert row['empty_completion_rate'] == 0.0
    # Coverage is a share of documents, and a missing field is zero, not absent.
    assert set(row['coverage']) == set(FIELDS)
    assert row['coverage']['reported_eps'] > 0.0


def test_bakeoff_isolated_and_requests_ledgered(
    config: Config, tmp_path: Path, monkeypatch: object
) -> None:
    index = _index(tmp_path, documents=1)
    import nowcast.llm.composition as composition

    original = composition.make_caller

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': []})
        return httpx.Response(
            200,
            json={
                'model': 'fake/model:free',
                'choices': [{'message': {'content': REPLY}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
            },
        )

    def factory(c: Config, **kwargs: object) -> RetryingCaller:
        return original(c, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(composition, 'make_caller', factory)  # type: ignore[attr-defined]
    table = run_bakeoff(config, ['fake/model:free'], index, 1)
    assert table['models'][0]['requests'] == 1
    assert table['models'][0]['latency_p95_seconds'] is not None
    assert not (tmp_path / 'data/extractions').exists()


def test_auth_failure_preserves_partial_bakeoff_and_unvisited_models(config, tmp_path, monkeypatch):
    import nowcast.llm.composition as composition
    from nowcast.errors import AuthError
    from nowcast.paths import Paths

    original = composition.make_caller
    index = _index(tmp_path, documents=3)
    local = dataclasses.replace(
        config,
        runtime=dataclasses.replace(config.runtime, max_concurrency=1, durable_requests=True),
    )
    calls = []

    def handler(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': []})
        calls.append(request)
        return httpx.Response(401, json={'error': {'message': 'rejected'}})

    monkeypatch.setattr(
        composition,
        'make_caller',
        lambda c, **kwargs: original(c, transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(AuthError):
        run_bakeoff(local, ['fake/first:free', 'fake/second:free'], index, 3)
    files = list(Paths.from_config(local).manifests(local).glob('bakeoff/*/scores.json'))
    assert len(files) == 1 and len(calls) == 1
    result = json.loads(files[0].read_text())
    assert result['execution_complete'] is False
    assert result['error_kind'] == 'AuthError'
    assert result['models'][0]['requests'] == 1
    assert result['models'][0]['unvisited'] == 2
    assert result['models'][1]['unvisited'] == 3
