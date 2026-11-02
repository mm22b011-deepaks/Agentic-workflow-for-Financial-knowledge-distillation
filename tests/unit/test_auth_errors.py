"""F12: a rejected credential is reported once, not retried per document."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import httpx
import pytest

from nowcast.config import Config, resolve_data_path
from nowcast.errors import AuthError, ModelNotFound
from nowcast.extraction.runner import Document, run_extraction
from nowcast.llm.cache import ResponseCache
from nowcast.llm.caller import LLMCaller
from nowcast.llm.composition import RetryingCaller

MODEL = 'fake/model:free'


def _no_probe(config: Config) -> Config:
    """Clear the models URL: these tests count one provider request at a time."""
    return dataclasses.replace(config, llm=dataclasses.replace(config.llm, models_url=''))


BODY = {
    'error': {'message': 'User not found.', 'code': 401},
}


def _transport(status: int, calls: list[int], body: object = BODY) -> httpx.MockTransport:
    """Return a transport answering every request with one status, counting requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(status)
        return httpx.Response(status, json=body, request=request)

    return httpx.MockTransport(handler)


def test_401_not_retried(config: Config) -> None:
    """A 401 reaches the caller once: retrying a bad key spends the budget on the same answer."""
    calls: list[int] = []
    config = _no_probe(config)
    caller = LLMCaller(config.llm, transport=_transport(401, calls))
    wrapper = RetryingCaller(caller, ResponseCache(config.cache, config.paths.data_dir), config)
    with pytest.raises(AuthError) as excinfo:
        wrapper.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
    assert len(calls) == 1
    assert '401' in str(excinfo.value)
    assert 'User not found' not in str(excinfo.value)
    assert wrapper.calls == 1


def test_404_model_not_found_not_retried(config: Config) -> None:
    """A model the provider does not have is a fact, not a transient failure."""
    calls: list[int] = []
    config = _no_probe(config)
    caller = LLMCaller(config.llm, transport=_transport(404, calls, {'error': 'no such model'}))
    wrapper = RetryingCaller(caller, ResponseCache(config.cache, config.paths.data_dir), config)
    with pytest.raises(ModelNotFound):
        wrapper.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
    assert len(calls) == 1


def test_5xx_is_retried(config: Config) -> None:
    """A server error is worth another attempt."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(500)
        if len(calls) < 2:
            return httpx.Response(500, text='boom', request=request)
        return httpx.Response(
            200,
            json={
                'model': MODEL,
                'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}],
            },
            request=request,
        )

    caller = LLMCaller(config.llm, transport=httpx.MockTransport(handler))
    wrapper = RetryingCaller(
        caller,
        ResponseCache(config.cache, config.paths.data_dir),
        config,
        sleep=lambda _seconds: None,
    )
    result = wrapper.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
    assert result.text == 'ok'
    assert len(calls) == 2


def test_auth_error_aborts_run_not_every_document_failed(config: Config, tmp_path: Path) -> None:
    """Every document would fail the same way, so the run stops with the real cause."""
    source = tmp_path / 'doc.txt'
    source.write_text('GAAP earnings per share were $0.55.', encoding='utf-8')
    # More documents than the concurrency limit, so "stopped early" is observable
    # rather than true only by accident.
    documents = [
        Document(
            document_id=f'doc{index}',
            cik='0000000001',
            report_date='2026-01-15',
            document_type='EX-99.1',
            raw_path=source,
            sha256=f'h{index}',
        )
        for index in range(8)
    ]
    calls: list[int] = []
    config = _no_probe(config)
    caller = LLMCaller(config.llm, transport=_transport(401, calls))
    with pytest.raises(AuthError):
        asyncio.run(
            run_extraction(
                config,
                documents,
                caller_factory=lambda _model: caller,
                models=[MODEL],
                queue_path=resolve_data_path(config, config.extraction.review_queue_path),
            )
        )
    # Only the in-flight documents were called; the rest never reached the provider.
    assert len(calls) <= int(config.runtime.max_concurrency)
    # And none of them was queued as a per-document llm_failed row.
    queue = resolve_data_path(config, config.extraction.review_queue_path)
    if queue.is_file():
        import pandas as pd

        assert 'llm_failed' not in set(pd.read_parquet(queue)['reason'])


def test_cache_key_changes_with_reasoning_settings(config: Config, tmp_path: Path) -> None:
    """A reply sampled under a different reasoning budget is a different reply."""
    from nowcast.llm.composition import RetryingCaller as Wrapper

    cache = ResponseCache(config.cache, tmp_path / 'cache')
    seen: list[str] = []

    class Recording:
        def complete(self, model, messages, max_tokens=None):
            from nowcast.llm.caller import LLMResult

            seen.append(json.dumps(messages))
            return LLMResult(text='{"a": 1}', model=model)

    def key_for(llm_config: object) -> str:
        variant = dataclasses.replace(config, llm=llm_config)
        wrapper = Wrapper(Recording(), cache, variant)
        return wrapper._key(MODEL, [{'role': 'user', 'content': 'x'}])

    effort = key_for(dataclasses.replace(config.llm, reasoning_effort='low'))
    more = key_for(dataclasses.replace(config.llm, reasoning_effort='high'))
    capped = key_for(
        dataclasses.replace(config.llm, reasoning_control='max_tokens', max_reasoning_tokens=100)
    )
    assert effort != more
    assert effort != capped
