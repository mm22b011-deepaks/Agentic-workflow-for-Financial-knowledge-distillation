"""N2: an empty completion is a truncated reply, not a parse failure."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from nowcast.config import Config, resolve_data_path
from nowcast.errors import TruncatedCompletion
from nowcast.extraction.runner import Document, run_extraction
from nowcast.llm.cache import ResponseCache
from nowcast.llm.caller import LLMCaller
from nowcast.llm.composition import RetryingCaller

MODEL = 'fake/model:free'


def _response(body: dict[str, object], status: int = 200) -> httpx.Response:
    """Build a response with a request attached, as httpx does for real traffic."""
    request = httpx.Request('POST', 'https://openrouter.test/chat/completions')
    return httpx.Response(status, json=body, request=request)


def _length_body(completion_tokens: int = 8192) -> dict[str, object]:
    """Return a provider body for an empty reply that ran out of budget."""
    return {
        'model': MODEL,
        'choices': [
            {'message': {'content': '', 'reasoning': 'thinking...'}, 'finish_reason': 'length'}
        ],
        'usage': {
            'prompt_tokens': 100,
            'completion_tokens': completion_tokens,
            'total_tokens': 100,
        },
    }


def _caller(config: Config, responses: list[dict[str, object]]) -> tuple[LLMCaller, list[int]]:
    """Build an LLMCaller over a mock transport, recording the max_tokens it was sent."""
    seen: list[int] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        seen.append(payload['max_tokens'])
        body = queue.pop(0) if queue else _length_body()
        return _response(body)

    model_config = type(config.llm)(**{**config.llm.__dict__, 'max_tokens': 1024})
    return LLMCaller(model_config, transport=httpx.MockTransport(handler)), seen


def test_empty_length_completion_raises_truncated(config: Config) -> None:
    """An empty reply with finish_reason=length raises instead of returning ''."""
    caller, _seen = _caller(config, [_length_body()])
    with pytest.raises(TruncatedCompletion) as excinfo:
        caller.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
    assert excinfo.value.max_tokens == 1024
    assert excinfo.value.completion_tokens == 8192


def test_truncated_retries_with_larger_max_tokens_then_gives_up(config: Config) -> None:
    """One retry at double the budget, then a clear failure rather than an endless loop."""
    inner, seen = _caller(config, [_length_body(), _length_body(), _length_body()])
    wrapper = RetryingCaller(inner, ResponseCache(config.cache, config.paths.data_dir), config)
    with pytest.raises(TruncatedCompletion):
        wrapper.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
    # First attempt at the configured budget, one retry at double, then stop.
    assert seen == [1024, 2048]
    assert wrapper.calls == 2


def test_truncated_not_counted_as_parse_failure(config: Config, tmp_path: Path) -> None:
    """A truncated reply must not spend the repair turns; the document fails once."""
    inner, seen = _caller(config, [_length_body() for _ in range(20)])
    wrapper = RetryingCaller(inner, ResponseCache(config.cache, tmp_path / 'cache'), config)

    source = tmp_path / 'doc.txt'
    source.write_text('GAAP earnings per share were $0.55.', encoding='utf-8')
    documents = [
        Document(
            document_id='doc0',
            cik='0000000001',
            report_date='2026-01-15',
            document_type='EX-99.1',
            raw_path=source,
            sha256='h0',
        )
    ]
    outcomes = asyncio.run(
        run_extraction(
            config,
            documents,
            caller_factory=lambda _model: wrapper,
            models=[MODEL],
            queue_path=resolve_data_path(config, config.extraction.review_queue_path),
        )
    )
    assert [outcome.status for outcome in outcomes] == ['failed']
    # Two calls total (attempt + one larger-budget retry), not 1 + max_repairs per turn.
    assert len(seen) <= 2
    import pandas as pd

    queue = pd.read_parquet(resolve_data_path(config, config.extraction.review_queue_path))
    assert 'truncated' in set(queue['reason'])
