"""OpenRouter chat-completion caller restricted to free models."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from nowcast.config import LLMConfig
from nowcast.errors import ConfigError, RateLimited, TruncatedCompletion
from nowcast.llm.ledger import BudgetLedger

LOGGER = logging.getLogger(__name__)
FREE_SUFFIX = ':free'
DEFAULT_429_WAIT_SECONDS = 30.0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Read a Retry-After header in seconds, or retry_after_ms in the JSON body.

    Free OpenRouter models answer 429 when a shared upstream pool is busy, and the
    delay they ask for is usually far longer than a fixed backoff would allow.
    """
    header = response.headers.get('retry-after', '').strip()
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass  # an HTTP-date form is possible; fall through to the body
    try:
        payload = response.json()
    except ValueError:
        payload = None
    body_wait = _find_wait_seconds(payload)
    if body_wait is not None:
        return body_wait
    if response.status_code == 429:
        return DEFAULT_429_WAIT_SECONDS
    return None


def _find_wait_seconds(payload: object, depth: int = 0) -> float | None:
    """Search a provider error body, at any depth, for a stated retry delay.

    Providers disagree on shape: the delay turns up at the top level, under
    `metadata`, or wrapped in `error.metadata`, so the shape is not assumed.
    """
    if depth > 4:
        return None
    if isinstance(payload, dict):
        for key in ('retry_after_seconds', 'retry_after_ms'):
            value = payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                divisor = 1000.0 if key.endswith('_ms') else 1.0
                return max(0.0, float(value) / divisor)
        for value in payload.values():
            found = _find_wait_seconds(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_wait_seconds(item, depth + 1)
            if found is not None:
                return found
    return None


@dataclass(frozen=True)
class LLMResult:
    """One completion plus the usage figures reported by the provider."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False


class LLMCaller:
    """Synchronous chat-completion caller for free OpenRouter models."""

    def __init__(
        self,
        config: LLMConfig,
        ledger: BudgetLedger | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Store settings and resolve the API key from the configured environment variable."""
        self._config = config
        self._ledger = ledger
        api_key = os.environ.get(config.api_key_env, '')
        if not api_key:
            raise ConfigError(f'environment variable {config.api_key_env!r} is not set')
        self._api_key = api_key
        self._budget = int(config.max_tokens)
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            transport=transport,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': config.app_name,
                'X-Title': config.app_name,
            },
        )

    def close(self) -> None:
        """Flush the spend ledger and close the underlying HTTP client."""
        if self._ledger is not None:
            self._ledger.flush()
        self._client.close()

    def __enter__(self) -> LLMCaller:
        """Enter the client context."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the client on exit."""
        self.close()

    @staticmethod
    def _assert_free(model: str) -> None:
        """Reject any model id that is not a free OpenRouter model."""
        if not model.endswith(FREE_SUFFIX):
            raise ConfigError(f'model {model!r} is not a free OpenRouter model (must end in :free)')

    def with_max_tokens(self, max_tokens: int) -> None:
        """Raise the completion budget for subsequent calls.

        Called only after a truncated completion, so the retry gets room the first
        attempt did not have. The configured value is never mutated.
        """
        self._budget = max(int(self._budget), int(max_tokens))

    def _payload(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Build the request body for one completion."""
        payload: dict[str, Any] = {
            'model': model,
            'messages': messages,
            'temperature': self._config.temperature,
            'max_tokens': self._budget,
        }
        if self._config.reasoning_effort:
            payload['reasoning'] = {'effort': self._config.reasoning_effort}
        elif self._config.max_reasoning_tokens:
            payload['reasoning'] = {'max_tokens': self._config.max_reasoning_tokens}
        return payload

    def _cost_from_headers(self, response: httpx.Response, usage: dict[str, Any]) -> float:
        """Read the billed cost from the provider, defaulting to zero for free models."""
        raw = usage.get('cost')
        if isinstance(raw, (int, float)):
            return float(raw)
        header = response.headers.get('x-openrouter-cost', '')
        try:
            return float(header)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Raise the usual httpx error, but carry the provider's Retry-After delay."""
        if response.is_success:
            return
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            retry_after = _retry_after_seconds(response)
            if retry_after is not None:
                raise RateLimited(
                    f'{response.status_code} from {response.request.url}: '
                    f'retry after {retry_after:.1f}s',
                    retry_after_seconds=retry_after,
                ) from exc
            raise

    def complete(self, model: str, messages: list[dict[str, str]]) -> LLMResult:
        """Send one chat completion and return the text with usage and cost."""
        self._assert_free(model)
        if self._ledger is not None:
            self._ledger.check_budget()
        response = self._client.post('/chat/completions', json=self._payload(model, messages))
        self._raise_for_status(response)
        body = response.json()
        choices = body.get('choices') or []
        text = ''
        if choices:
            text = str((choices[0].get('message') or {}).get('content') or '')
        usage: dict[str, Any] = body.get('usage') or {}
        cost = self._cost_from_headers(response, usage)
        finish = str(choices[0].get('finish_reason') or '') if choices else ''
        completion_tokens = int(usage.get('completion_tokens') or 0)
        if not text.strip() and finish == 'length':
            # Nothing came back because the budget ran out. Raising here keeps the empty
            # text out of the repair loop, which would spend 1 + max_repairs calls on it.
            LOGGER.warning(
                'empty completion: reasoning used the whole token budget model=%s '
                'completion_tokens=%d max_tokens=%d',
                model,
                completion_tokens,
                self._budget,
            )
            raise TruncatedCompletion(
                f'empty completion from {model}: finish_reason=length',
                max_tokens=int(self._budget),
                completion_tokens=completion_tokens,
            )
        result = LLMResult(
            text=text,
            model=str(body.get('model') or model),
            prompt_tokens=int(usage.get('prompt_tokens') or 0),
            completion_tokens=int(usage.get('completion_tokens') or 0),
            total_tokens=int(usage.get('total_tokens') or 0),
            cost_usd=cost,
        )
        if self._ledger is not None:
            self._ledger.record(model=result.model, usage=result, max_tokens=int(self._budget))
            self._ledger.check_budget()
        LOGGER.info(
            'completion model=%s tokens=%s cost_usd=%s',
            result.model,
            result.total_tokens,
            result.cost_usd,
        )
        return result
