"""The one place a model caller is composed: retry, provider delays and cache.

Every entry point goes through `make_caller`. Before this module existed the runner was
handed a bare `LLMCaller`, so retry and `Retry-After` never ran on real traffic, and a
second cache path wrote replies that nothing ever read.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from pydantic import ValidationError

from nowcast.config import Config, cache_dir
from nowcast.errors import (
    AuthError,
    BudgetExceeded,
    EmptyCompletion,
    ModelNotFound,
    RateLimited,
    TruncatedCompletion,
)
from nowcast.extraction.schema import ExtractionRecord
from nowcast.llm.cache import ResponseCache, cache_key
from nowcast.llm.caller import LLMResult

LOGGER = logging.getLogger(__name__)


def cacheable_reply(text: str) -> bool:
    """Return whether a reply may be stored for reuse.

    An empty reply, or one that does not contain a JSON object, can never satisfy a
    caller. Storing it would replay the failure forever: `ResponseCache.get` returns ''
    for an empty entry, and callers test `is not None`, so the miss would never happen.
    """
    if not text or not text.strip():
        return False
    candidate = text.strip()
    start = candidate.find('{')
    end = candidate.rfind('}')
    if start < 0 or end <= start:
        return False
    try:
        loaded = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return False
    if not isinstance(loaded, dict):
        return False
    try:
        ExtractionRecord.model_validate(loaded)
    except ValidationError:
        return False
    return True


def retry_delay(exc: Exception, attempt: int, backoff: float, max_wait: float) -> float:
    """Return the wait before the next attempt, honouring a provider-stated delay."""
    requested = getattr(exc, 'retry_after_seconds', None)
    delay = backoff * (attempt + 1)
    if isinstance(requested, (int, float)) and not isinstance(requested, bool):
        # A provider-stated delay (a 429 on a busy free pool) beats the fixed backoff,
        # which is far shorter than what the provider is asking for.
        delay = max(delay, float(requested))
    return min(delay, max_wait)


class RetryingCaller:
    """Wrap a caller with the response cache and bounded retries."""

    def __init__(
        self,
        caller: Any,
        cache: ResponseCache,
        config: Config,
        sleep: Any = None,
        limiter: Any = None,
    ) -> None:
        """Store the inner caller, the cache, the retry settings and the shared limiter."""
        self._caller = caller
        self._limiter = limiter
        self._cache = cache
        self._config = config
        self._sleep = sleep or time.sleep
        self.cache_hits = 0
        self.calls = 0
        # Extraction calls this from a thread pool; an unsynchronised counter loses hits
        # and makes a cache measurement wrong.
        self._lock = threading.Lock()

    def close(self) -> None:
        """Close the wrapped caller if it owns a client; safe to call twice."""
        close = getattr(self._caller, 'close', None)
        if close is not None:
            close()

    def _key(self, model: str, messages: list[dict[str, str]]) -> str:
        """Return the cache key for one request, including every sampling setting.

        The prompt text already carries the rendered prompt, so the few-shot examples and
        the document are in the key. The sampling parameters are not, and a reply sampled
        with a different reasoning budget is a different reply.
        """
        prompt_text = '\n'.join(message['content'] for message in messages)
        return cache_key(
            prompt_text,
            model,
            params={
                'temperature': self._config.llm.temperature,
                'max_tokens': self._config.llm.max_tokens,
                'schema_version': self._config.extraction.schema_version,
                'reasoning': self._config.llm.reasoning_params(),
            },
        )

    def complete(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> LLMResult:
        """Return a cached or fresh completion, retrying transient failures only."""
        key = self._key(model, messages)
        cache_started = time.perf_counter()
        cached = self._cache.get(key)
        if cached is not None and cacheable_reply(cached):
            with self._lock:
                self.cache_hits += 1
            note = getattr(self._caller, 'note_cache_hit', None)
            if note is not None:
                note(model, time.perf_counter() - cache_started)
            return LLMResult(text=cached, model=model, cached=True)
        attempts = max(1, int(self._config.llm.retry_attempts))
        backoff = float(self._config.llm.retry_backoff_seconds)
        max_wait = float(self._config.llm.retry_max_wait_seconds)
        ceiling = int(self._config.llm.max_tokens_ceiling)
        budget = int(max_tokens or self._config.llm.max_tokens)
        last_error: Exception | None = None
        truncated_retry_used = False
        empty_retry_used = False
        for attempt in range(attempts):
            try:
                with self._lock:
                    self.calls += 1
                if self._limiter is not None:
                    self._limiter.acquire()
                try:
                    result = self._caller.complete(model, messages, max_tokens=budget)
                except RateLimited as exc:
                    # One refusal means the shared pool is busy: pause every caller, not
                    # just this one, or the next thread walks straight into the same 429.
                    if self._limiter is not None and exc.retry_after_seconds:
                        self._limiter.cooldown(float(exc.retry_after_seconds))
                    raise
            except (BudgetExceeded, AuthError, ModelNotFound):
                # A spend cap, a rejected credential and a missing model are facts about
                # the run, not transient states: retrying them spends the budget on the
                # same answer and buries the cause under N identical failures.
                raise
            except EmptyCompletion as exc:
                last_error = exc
                if not isinstance(exc, TruncatedCompletion):
                    # A provider that returns finish_reason=stop with no content is
                    # transient, not fatal: one more attempt, then hand it up as it is.
                    if empty_retry_used:
                        break
                    empty_retry_used = True
                    LOGGER.warning('empty completion: retrying once model=%s', model)
                    continue
                if truncated_retry_used or exc.max_tokens >= ceiling:
                    break
                truncated_retry_used = True
                budget = min(int(exc.max_tokens) * 2, ceiling)
                LOGGER.warning(
                    'truncated completion: retrying with max_tokens=%d (was %d) model=%s',
                    budget,
                    exc.max_tokens,
                    model,
                )
                continue
            except Exception as exc:
                last_error = exc
                LOGGER.warning('call failed attempt=%d model=%s error=%s', attempt, model, exc)
                if attempt < attempts - 1:
                    delay = retry_delay(exc, attempt, backoff, max_wait)
                    if delay > 0:
                        LOGGER.info('retrying in %.1fs attempt=%d model=%s', delay, attempt, model)
                        self._sleep(delay)
                continue
            if cacheable_reply(result.text):
                self._cache.set(key, result.text, model)
            else:
                LOGGER.info('reply not cacheable model=%s chars=%d', model, len(result.text))
            return result
        if isinstance(last_error, EmptyCompletion):
            raise last_error
        requested = getattr(last_error, 'retry_after_seconds', None)
        if isinstance(requested, (int, float)) and not isinstance(requested, bool):
            raise RateLimited(
                f'all {attempts} attempts failed: {last_error}',
                retry_after_seconds=float(requested),
            )
        raise RuntimeError(f'all {attempts} attempts failed: {last_error}')


def make_caller(
    config: Config,
    ledger: Any = None,
    cache: ResponseCache | None = None,
    inner: Any = None,
    transport: Any = None,
    sleep: Any = None,
) -> RetryingCaller:
    """Return the composed caller every entry point must use.

    `inner` and `transport` exist so tests can supply a fake or a mock transport; with
    neither, a real `LLMCaller` is built against the configured provider.
    """
    from nowcast.llm.caller import LLMCaller

    caller = (
        inner if inner is not None else LLMCaller(config.llm, ledger=ledger, transport=transport)
    )
    active_cache = cache if cache is not None else ResponseCache(config.cache, cache_dir(config))
    from nowcast.jobs import store_for
    from nowcast.llm.throttle import SharedRequestLimiter

    limiter = SharedRequestLimiter(
        store_for(config),
        config.llm.base_url,
        per_minute=int(config.llm.requests_per_minute),
        per_day=int(config.llm.requests_per_day),
    )
    return RetryingCaller(caller, active_cache, config, sleep=sleep, limiter=limiter)
