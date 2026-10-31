"""Unit tests for structured extraction with repair."""

from __future__ import annotations

from pathlib import Path

from nowcast.extraction.schema import ExtractionRecord
from nowcast.llm.structured import extract_structured, strip_code_fences

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS = REPO_ROOT / 'prompts'

VALID = (Path(__file__).resolve().parent.parent / 'fixtures' / 'extraction_record.json').read_text(
    encoding='utf-8'
)


def _variables() -> dict[str, object]:
    """Variables required by the v1 prompt templates."""
    return {
        'document_id': 'doc-1',
        'document_text': 'Revenue was $1.20 billion.',
        'max_evidence_words': 25,
        'themes': 'demand, pricing',
    }


def _bundle() -> object:
    """Load the v1 extraction bundle."""
    from nowcast.llm.prompts import load_prompt

    return load_prompt('extraction', 'v1', PROMPTS)


def _run(replies: list[str], max_repairs: int = 2):
    """Run extract_structured against canned replies."""
    from tests.conftest import FakeCaller

    caller = FakeCaller(replies)
    result, text, error = extract_structured(
        caller,
        'fake/model:free',
        _bundle(),  # type: ignore[arg-type]
        _variables(),
        ExtractionRecord,
        max_repairs,
    )
    return result, text, error, caller


def test_structured_valid_json() -> None:
    """A valid JSON reply parses with no error and one call."""
    result, _text, error, caller = _run([VALID])
    assert isinstance(result, ExtractionRecord)
    assert error is None
    assert caller.call_count == 1


def test_structured_fenced_json() -> None:
    """A fenced JSON reply is stripped and parsed."""
    result, _text, error, _caller = _run([f'```json\n{VALID}\n```'])
    assert isinstance(result, ExtractionRecord)
    assert error is None


def test_structured_repair_then_success() -> None:
    """An invalid first reply is repaired by a second valid reply."""
    result, _text, error, caller = _run(['not json at all', VALID])
    assert isinstance(result, ExtractionRecord)
    assert error is None
    assert caller.call_count == 2


def test_structured_gives_up_returns_error() -> None:
    """Exhausting repairs returns the error string without raising."""
    result, text, error, caller = _run(['still not json'], max_repairs=1)
    assert result is None
    assert text == 'still not json'
    assert error is not None
    assert caller.call_count == 2


def test_structured_reraises_budget_exceeded() -> None:
    """A budget stop is not a per-document failure; it must escape to the runner."""
    from nowcast.errors import BudgetExceeded

    class BudgetCaller:
        """A caller that has already spent its budget."""

        def complete(self, model: str, messages: list[dict[str, str]]) -> object:
            raise BudgetExceeded('budget exhausted')

    try:
        extract_structured(
            BudgetCaller(),  # type: ignore[arg-type]
            'fake/model:free',
            _bundle(),  # type: ignore[arg-type]
            _variables(),
            ExtractionRecord,
            2,
        )
    except BudgetExceeded:
        return
    raise AssertionError('extract_structured swallowed BudgetExceeded')


def test_strip_code_fences_plain_text() -> None:
    """Plain text without fences is returned unchanged apart from whitespace."""
    assert strip_code_fences('  {"a": 1}  ') == '{"a": 1}'


def test_strip_code_fences_removes_closed_think_block() -> None:
    """A closed reasoning block is removed and the JSON after it survives."""
    text = '<think>weighing options</think>{"a": 1}'
    assert strip_code_fences(text) == '{"a": 1}'


def test_strip_code_fences_drops_unclosed_think_block() -> None:
    """A truncated reasoning block has no JSON after it, so nothing is left to parse."""
    text = '{"a": 1}\n<thinking>still reasoning and then the reply was cut off'
    assert strip_code_fences(text) == '{"a": 1}'
    assert strip_code_fences('<thinking>only reasoning, truncated') == ''


def test_structured_salvages_json_from_commentary() -> None:
    """An object wrapped in prose is salvaged without spending a repair turn."""
    import json

    wrapped = (
        'Here is the extraction you asked for:\n\n' + VALID + '\n\nLet me know if you need more.'
    )
    result, _text, error, caller = _run([wrapped])
    assert isinstance(result, ExtractionRecord)
    assert error is None
    assert caller.call_count == 1
    assert json.loads(VALID)['fiscal_year'] == result.fiscal_year


def test_structured_strips_think_block_before_parsing() -> None:
    """A reasoning block before the JSON is stripped, so no repair call is needed."""
    reply = ' thinkingThe revenue line says 1.2 billion, so I will copy that.</think>\n' + VALID
    result, _text, error, caller = _run([reply])
    assert isinstance(result, ExtractionRecord)
    assert error is None
    assert caller.call_count == 1
