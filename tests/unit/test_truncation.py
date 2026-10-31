"""N2: an empty completion is a truncated reply, not a parse failure."""

from __future__ import annotations

import asyncio
import dataclasses
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


def _ok_body(text: str = '{"ok": true}') -> dict[str, object]:
    """Return a provider body for a successful reply."""
    return {
        'model': MODEL,
        'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
    }


def _small(config: Config) -> Config:
    """Return the config with a small token budget, so a retry stays well inside it.

    The models URL is cleared: these tests count provider requests, and a capability
    probe per model would be a request of its own.
    """
    return dataclasses.replace(
        config,
        llm=dataclasses.replace(
            config.llm, max_tokens=1024, max_tokens_ceiling=4096, models_url=''
        ),
    )


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


def test_truncated_retries_with_larger_max_tokens_then_gives_up(
    config: Config, tmp_path: Path
) -> None:
    """One retry at double the budget, then a clear failure rather than an endless loop."""
    inner, seen = _caller(config, [_length_body(), _length_body(), _length_body()])
    # The run's budget comes from the config the composition holds, not from the inner
    # caller, so both are given the same small budget here.
    small = _small(config)
    wrapper = RetryingCaller(inner, ResponseCache(config.cache, tmp_path / 'cache'), small)
    with pytest.raises(TruncatedCompletion):
        wrapper.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
    # First attempt at the configured budget, one retry at double, then stop.
    assert seen == [1024, 2048]
    assert wrapper.calls == 2


def test_truncation_retry_does_not_change_budget_for_other_documents(
    config: Config, tmp_path: Path
) -> None:
    """A truncated retry raises the budget for that retry only, not for every later call."""
    bodies = [_length_body(), _length_body(), _ok_body()]
    request_budgets: list[int] = []
    queue = list(bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        request_budgets.append(json.loads(request.content)['max_tokens'])
        return _response(queue.pop(0))

    small = _small(config)
    inner = LLMCaller(small.llm, transport=httpx.MockTransport(handler))
    wrapper = RetryingCaller(inner, ResponseCache(config.cache, tmp_path / 'cache'), small)
    with pytest.raises(TruncatedCompletion):
        wrapper.complete(MODEL, [{'role': 'user', 'content': 'first'}])
    wrapper.complete(MODEL, [{'role': 'user', 'content': 'second'}])
    # The retry ran at 2048; the next document went back to the configured 1024.
    assert request_budgets == [1024, 2048, 1024]


def test_truncated_attempt_is_ledgered(config: Config, tmp_path: Path) -> None:
    """The attempts that mattered — the ones that failed — are in the ledger."""
    from nowcast.llm.ledger import BudgetLedger

    inner, _seen = _caller(config, [_length_body(), _length_body(), _length_body()])
    ledger = BudgetLedger(tmp_path / 'ledger.parquet', max_usd=1.0)
    small = _small(config)
    inner = LLMCaller(small.llm, ledger=ledger, transport=inner._client._transport)
    wrapper = RetryingCaller(inner, ResponseCache(config.cache, tmp_path / 'cache'), small)
    with pytest.raises(TruncatedCompletion):
        wrapper.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
    ledger.flush()
    import pandas as pd

    frame = pd.read_parquet(tmp_path / 'ledger.parquet')
    assert frame['outcome'].tolist() == ['truncated', 'truncated']
    assert frame['finish_reason'].tolist() == ['length', 'length']
    assert frame['max_tokens'].tolist() == [1024, 2048]


def test_empty_with_stop_finish_raises_empty_completion(config: Config) -> None:
    """Empty content with finish_reason=stop is empty, not something to repair."""
    from nowcast.errors import EmptyCompletion

    body = _length_body()
    body['choices'] = [{'message': {'content': '  '}, 'finish_reason': 'stop'}]
    caller, _seen = _caller(config, [body])
    with pytest.raises(EmptyCompletion) as excinfo:
        caller.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
    assert not isinstance(excinfo.value, TruncatedCompletion)
    assert excinfo.value.finish_reason == 'stop'


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


def test_reasoning_param_only_sent_when_supported(config: Config) -> None:
    """An unsupported `reasoning` parameter is not sent; a supported one is."""
    import json

    def run(models_body: dict[str, object]) -> dict[str, object]:
        sent: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith('/models'):
                return _response(models_body)
            sent.append(json.loads(request.content))
            return _response(_ok_body())

        model_config = dataclasses.replace(
            config.llm, models_url='https://openrouter.test/api/v1/models'
        )
        caller = LLMCaller(model_config, transport=httpx.MockTransport(handler))
        caller.complete(MODEL, [{'role': 'user', 'content': 'hi'}])
        return sent[0]

    without = run({'data': [{'id': MODEL, 'supported_parameters': ['temperature']}]})
    with_param = run({'data': [{'id': MODEL, 'supported_parameters': ['reasoning']}]})
    assert 'reasoning' not in without
    assert with_param['reasoning'] == {'effort': config.llm.reasoning_effort}
