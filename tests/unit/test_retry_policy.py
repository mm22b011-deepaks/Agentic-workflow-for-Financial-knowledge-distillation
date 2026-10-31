"""Tests for provider-directed retry delays (Retry-After, 429 bodies)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from nowcast.config import load_config
from nowcast.errors import BudgetExceeded, RateLimited
from nowcast.llm.cache import ResponseCache
from nowcast.llm.caller import LLMResult, _retry_after_seconds
from nowcast.llm.composition import RetryingCaller

REPO = Path(__file__).resolve().parent.parent.parent


def _response(
    status: int, headers: dict[str, str] | None = None, body: Any = None
) -> httpx.Response:
    """Build a response with a request attached, as httpx does for real traffic."""
    request = httpx.Request('POST', 'https://openrouter.test/chat/completions')
    if body is None:
        return httpx.Response(status, headers=headers or {}, request=request)
    return httpx.Response(status, headers=headers or {}, json=body, request=request)


def test_retry_after_header_is_used() -> None:
    """A Retry-After header is converted to seconds."""
    assert _retry_after_seconds(_response(429, {'retry-after': '17'})) == 17.0
    assert _retry_after_seconds(_response(503, {'retry-after': '0'})) == 0.0


def test_retry_after_body_and_default() -> None:
    """A body field is used when the header is missing; bare 429s get a floor."""
    body = {'error': {'metadata': {'retry_after_ms': 4500}}}
    assert _retry_after_seconds(_response(429, body=body)) == 4.5
    assert _retry_after_seconds(_response(429)) == 30.0
    # A plain 500 with no guidance is left to the fixed backoff.
    assert _retry_after_seconds(_response(500)) is None


class FlakyCaller:
    """Raises a scripted exception first, then returns a completion."""

    def __init__(self, errors: list[Exception], text: str = '{"ok": true}') -> None:
        """Store the errors to raise, in order, then the eventual reply."""
        self.errors = list(errors)
        self.text = text
        self.calls = 0

    def complete(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> LLMResult:
        """Raise the next scripted error or return the reply."""
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return LLMResult(text=self.text, model=model)


def test_retry_honours_provider_delay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider-stated wait replaces the shorter fixed backoff, capped by config."""
    config = load_config(
        REPO / 'configs' / 'config.yaml',
        overrides={
            'llm.retry_backoff_seconds': '2',
            'llm.retry_attempts': '3',
            'llm.retry_max_wait_seconds': '120',
        },
    )
    inner = FlakyCaller([RateLimited('429', retry_after_seconds=45.0)])
    sleeps: list[float] = []

    wrapper = RetryingCaller(
        inner, ResponseCache(config.cache, tmp_path / 'cache'), config, sleep=sleeps.append
    )
    result = wrapper.complete('fake/model:free', [{'role': 'user', 'content': 'hi'}])
    assert result.text == '{"ok": true}'
    assert sleeps == [45.0]


def test_retry_caps_absurd_provider_delay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider asking for an hour is capped so the run does not hang."""
    config = load_config(
        REPO / 'configs' / 'config.yaml',
        overrides={'llm.retry_max_wait_seconds': '60', 'llm.retry_attempts': '2'},
    )
    inner = FlakyCaller([RateLimited('429', retry_after_seconds=3600.0)])
    sleeps: list[float] = []

    wrapper = RetryingCaller(
        inner, ResponseCache(config.cache, tmp_path / 'cache'), config, sleep=sleeps.append
    )
    wrapper.complete('fake/model:free', [{'role': 'user', 'content': 'hi'}])
    assert sleeps == [60.0]


def test_budget_exceeded_is_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spending the cap stops immediately instead of burning retries."""
    config = load_config(REPO / 'configs' / 'config.yaml', overrides={'llm.retry_attempts': '3'})
    inner = FlakyCaller([BudgetExceeded('spent')])
    sleeps: list[float] = []

    wrapper = RetryingCaller(
        inner, ResponseCache(config.cache, tmp_path / 'cache'), config, sleep=sleeps.append
    )
    with pytest.raises(BudgetExceeded):
        wrapper.complete('fake/model:free', [{'role': 'user', 'content': 'hi'}])
    assert sleeps == []
    assert inner.calls == 1
