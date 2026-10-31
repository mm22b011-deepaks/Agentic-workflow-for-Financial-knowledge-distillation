"""Structured extraction: build messages, call the model, parse and repair."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Protocol

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel

from nowcast.errors import BudgetExceeded
from nowcast.llm.caller import LLMResult
from nowcast.llm.prompts import PromptBundle, render_template

LOGGER = logging.getLogger(__name__)
FENCE_RE = re.compile(r'^```[a-zA-Z]*\s*|\s*```$')
THINK_RE = re.compile(r'<(think|thinking|reasoning)>.*?</\1>', re.S | re.I)
# A reply truncated mid-reasoning has an opening tag and no closing one; everything
# after it is reasoning, not JSON, so it must be dropped rather than parsed.
UNCLOSED_THINK_RE = re.compile(r'<(think|thinking|reasoning)>.*$', re.S | re.I)


class CallerLike(Protocol):
    """Anything that can complete one chat call, including test fakes."""

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        cache: Any | None = None,
    ) -> LLMResult:
        """Return one completion, optionally reusing a validated cached reply."""


def strip_code_fences(text: str) -> str:
    """Remove reasoning blocks and markdown code fences from model output."""
    stripped = UNCLOSED_THINK_RE.sub('', THINK_RE.sub('', text.strip()))
    return FENCE_RE.sub('', stripped).strip()


def _messages(
    bundle: PromptBundle, variables: dict[str, Any], schema: type[BaseModel]
) -> list[dict[str, str]]:
    """Build the chat messages for one structured extraction call."""
    parser = PydanticOutputParser(pydantic_object=schema)
    system_text = render_template(bundle.system_template, variables)
    system_text = system_text + '\n\n' + parser.get_format_instructions()
    user_text = render_template(bundle.user_template, variables)
    messages = [{'role': 'system', 'content': system_text}]
    for shot in bundle.few_shots:
        messages.append({'role': 'user', 'content': str(shot.get('input', ''))})
        messages.append({'role': 'assistant', 'content': str(shot.get('output', ''))})
    messages.append({'role': 'user', 'content': user_text})
    return messages


def extract_structured(
    caller: CallerLike,
    model: str,
    bundle: PromptBundle,
    variables: dict[str, Any],
    schema: type[BaseModel],
    max_repairs: int,
    cache: Any | None = None,
) -> tuple[BaseModel | None, str, str | None]:
    """Extract a schema object, repairing up to max_repairs times without raising."""
    parser = PydanticOutputParser(pydantic_object=schema)
    messages = _messages(bundle, variables, schema)
    cache_key_text = hashlib.sha256(
        json.dumps([model, messages], sort_keys=True).encode('utf-8')
    ).hexdigest()
    last_text = ''
    error: str | None = None
    for attempt in range(max_repairs + 1):
        try:
            result = caller.complete(model, messages)
        except BudgetExceeded:
            # A spend cap is a deliberate stop, not a per-document failure: let it
            # reach the runner so the batch halts instead of being reported as llm_failed.
            raise
        except Exception as exc:
            LOGGER.warning('model call failed attempt=%d model=%s error=%s', attempt, model, exc)
            return None, last_text, f'llm_call_failed: {exc}'
        last_text = result.text
        candidate = strip_code_fences(last_text)
        try:
            parsed = parser.parse(candidate)
            if cache is not None:
                cache.set(cache_key_text, candidate, model)
            return parsed, last_text, None
        except Exception as exc:
            # A model that wraps the object in commentary still yields the object:
            # parse it out and validate that, instead of spending a repair turn.
            salvaged = parse_json_loosely(last_text)
            if salvaged is not None:
                try:
                    parsed = parser.parse(json.dumps(salvaged))
                except Exception:
                    parsed = None
                if parsed is not None:
                    LOGGER.info('salvaged JSON from commentary attempt=%d model=%s', attempt, model)
                    if cache is not None:
                        cache.set(cache_key_text, json.dumps(salvaged), model)
                    return parsed, last_text, None
            error = str(exc)
            LOGGER.info('parse failed attempt=%d model=%s', attempt, model)
            if attempt >= max_repairs:
                break
            messages = [
                *messages,
                {'role': 'assistant', 'content': candidate},
                {
                    'role': 'user',
                    'content': (
                        'Your previous reply did not satisfy the schema. Error:\n'
                        f'{error}\nReturn only the corrected JSON object.'
                    ),
                },
            ]
    return None, last_text, error


def parse_json_loosely(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from text that may carry fences or commentary."""
    candidate = strip_code_fences(text)
    try:
        loaded = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find('{')
        end = candidate.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            loaded = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return loaded if isinstance(loaded, dict) else None
