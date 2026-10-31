"""OpenRouter chat-completion caller restricted to free models."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from nowcast.config import FREE_MODEL_SUFFIX, LLMConfig
from nowcast.errors import (
    AuthError,
    ConfigError,
    EmptyCompletion,
    ModelNotFound,
    RateLimited,
    TruncatedCompletion,
)
from nowcast.llm.ledger import BudgetLedger

LOGGER = logging.getLogger(__name__)
DEFAULT_429_WAIT_SECONDS = 30.0
# 401/403 are the provider rejecting this credential, 404 a model that does not exist and
# 400 a parameter it does not support: none of them change on a retry.
AUTH_STATUSES = frozenset({401, 403})
MODEL_STATUSES = frozenset({400, 404})


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


def _provider_message(response: httpx.Response) -> str:
    """Return the provider's own error text, or '' when the body has none."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        error = payload.get('error')
        if isinstance(error, dict):
            return str(error.get('message') or '').strip()
        if error:
            return str(error).strip()
    return ''


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
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'X-Title': config.app_name,
        }
        if config.referer_url:
            # OpenRouter reads this header as a URL; sending an app name there is a lie
            # the provider echoes back in its rankings.
            headers['HTTP-Referer'] = config.referer_url
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            transport=transport,
            headers=headers,
        )
        self._reasoning_support: dict[str, bool] = {}

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
        if not model.endswith(FREE_MODEL_SUFFIX):
            raise ConfigError(f'model {model!r} is not a free OpenRouter model (must end in :free)')

    @property
    def model_config(self) -> LLMConfig:
        """Return the settings this caller was built with."""
        return self._config

    def _payload(
        self, model: str, messages: list[dict[str, str]], max_tokens: int
    ) -> dict[str, Any]:
        """Build the request body for one completion.

        `max_tokens` is per call, never a value the caller ratchets: a truncated reply is
        retried with a larger budget for that retry only, and the next document gets the
        configured budget again.
        """
        payload: dict[str, Any] = {
            'model': model,
            'messages': messages,
            'temperature': self._config.temperature,
            'max_tokens': int(max_tokens),
        }
        reasoning = self._config.reasoning_params()
        if reasoning and self._supports_reasoning(model):
            payload['reasoning'] = reasoning
        return payload

    def _supports_reasoning(self, model: str) -> bool:
        """Ask the provider whether this model accepts a `reasoning` parameter.

        Sending an unsupported parameter is answered with 400, which looks like a bad
        request rather than a model capability. The answer is read from the provider's
        models list, never assumed. If the list cannot be read, the parameter is sent:
        a 400 is a clear failure, while silently dropping it hides why a model reasons.
        """
        if model in self._reasoning_support:
            return self._reasoning_support[model]
        supported = True
        if self._config.models_url:
            try:
                response = self._client.get(self._config.models_url, timeout=30.0)
                response.raise_for_status()
                for entry in response.json().get('data') or []:
                    if str(entry.get('id')) != model:
                        continue
                    params = entry.get('supported_parameters')
                    if isinstance(params, list):
                        supported = 'reasoning' in params
                    break
            except (httpx.HTTPError, ValueError) as exc:
                LOGGER.warning('could not read model capabilities model=%s error=%s', model, exc)
        self._reasoning_support[model] = supported
        if not supported:
            LOGGER.info('model does not support reasoning parameters model=%s', model)
        return supported

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
        """Raise the error that says what happened, not just a status code.

        A rejected credential, a model that does not exist and a transient server error
        all arrive as HTTP errors, but only the last one is worth retrying. The status
        decides the exception type so the retrying caller can tell them apart.
        """
        if response.is_success:
            return
        status = response.status_code
        detail = _provider_message(response)
        if status in AUTH_STATUSES:
            raise AuthError(f'{status} from {response.request.url}: {detail}')
        if status in MODEL_STATUSES:
            raise ModelNotFound(f'{status} from {response.request.url}: {detail}')
        retry_after = _retry_after_seconds(response)
        if retry_after is not None:
            raise RateLimited(
                f'{status} from {response.request.url}: retry after {retry_after:.1f}s',
                retry_after_seconds=retry_after,
            )
        response.raise_for_status()

    def complete(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> LLMResult:
        """Send one chat completion and return the text with usage and cost."""
        self._assert_free(model)
        budget = int(max_tokens or self._config.max_tokens)
        if self._ledger is not None:
            self._ledger.check_budget()
        response = self._client.post(
            '/chat/completions', json=self._payload(model, messages, budget)
        )
        self._raise_for_status(response)
        body = response.json()
        choices = body.get('choices') or []
        message = (choices[0].get('message') or {}) if choices else {}
        text = str(message.get('content') or '')
        usage: dict[str, Any] = body.get('usage') or {}
        cost = self._cost_from_headers(response, usage)
        finish = str(choices[0].get('finish_reason') or '') if choices else ''
        result = LLMResult(
            text=text,
            model=str(body.get('model') or model),
            prompt_tokens=int(usage.get('prompt_tokens') or 0),
            completion_tokens=int(usage.get('completion_tokens') or 0),
            total_tokens=int(usage.get('total_tokens') or 0),
            cost_usd=cost,
        )
        empty = not text.strip()
        outcome = 'ok'
        if empty:
            outcome = 'truncated' if finish == 'length' else 'empty'
        # Ledgered before any raise: the calls that fail are the ones a truncation or
        # cost analysis needs, and a raise must not be able to erase them.
        if self._ledger is not None:
            self._ledger.record(
                model=result.model,
                usage=result,
                max_tokens=budget,
                finish_reason=finish,
                outcome=outcome,
            )
        if empty:
            reasoning = message.get('reasoning') or message.get('reasoning_content') or ''
            LOGGER.warning(
                'empty completion model=%s finish_reason=%s completion_tokens=%d '
                'max_tokens=%d reasoning_chars=%d',
                model,
                finish or 'none',
                result.completion_tokens,
                budget,
                len(str(reasoning)),
            )
            if finish == 'length':
                raise TruncatedCompletion(
                    f'empty completion from {model}: finish_reason=length',
                    max_tokens=budget,
                    finish_reason=finish,
                    completion_tokens=result.completion_tokens,
                )
            raise EmptyCompletion(
                f'empty completion from {model}: finish_reason={finish or "none"}',
                max_tokens=budget,
                finish_reason=finish,
                completion_tokens=result.completion_tokens,
            )
        if self._ledger is not None:
            self._ledger.check_budget()
        LOGGER.info(
            'completion model=%s tokens=%s cost_usd=%s',
            result.model,
            result.total_tokens,
            result.cost_usd,
        )
        return result
