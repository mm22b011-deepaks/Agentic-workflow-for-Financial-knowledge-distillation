"""Unit tests for prompt loading and rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nowcast.errors import ConfigError
from nowcast.extraction.schema import ExtractionRecord
from nowcast.llm.prompts import load_prompt, prompt_hash, render_prompt

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS = REPO_ROOT / 'prompts'


def _bundle() -> object:
    """Load the v1 extraction prompt from the repo."""
    return load_prompt('extraction', 'v1', PROMPTS)


def test_render_missing_variable_raises() -> None:
    """Rendering without a template variable raises ConfigError."""
    bundle = _bundle()
    with pytest.raises(ConfigError):
        render_prompt(bundle, {'document_id': 'd1'})  # type: ignore[arg-type]


def test_prompt_hash_changes_with_text(tmp_path: Path) -> None:
    """Changing a template's text changes the prompt hash."""
    root = tmp_path / 'prompts'
    base = root / 'x' / 'v1'
    base.mkdir(parents=True)
    (base / 'system.md.j2').write_text('sys {{ a }}', encoding='utf-8')
    (base / 'user.md.j2').write_text('user {{ a }}', encoding='utf-8')
    first = load_prompt('x', 'v1', root)
    (base / 'user.md.j2').write_text('user {{ a }} changed', encoding='utf-8')
    second = load_prompt('x', 'v1', root)
    assert prompt_hash(first) != prompt_hash(second)


def test_prompt_hash_changes_with_few_shots(tmp_path: Path) -> None:
    """Few-shot examples are sent to the model, so editing one changes the hash."""
    root = tmp_path / 'prompts'
    base = root / 'x' / 'v1'
    base.mkdir(parents=True)
    (base / 'system.md.j2').write_text('sys', encoding='utf-8')
    (base / 'user.md.j2').write_text('user', encoding='utf-8')
    (base / 'few_shot.yaml').write_text('- input: q\n  output: {"a": 1}\n', encoding='utf-8')
    first = load_prompt('x', 'v1', root)
    (base / 'few_shot.yaml').write_text('- input: q\n  output: {"a": 2}\n', encoding='utf-8')
    second = load_prompt('x', 'v1', root)
    assert prompt_hash(first) != prompt_hash(second)
    assert first.prompt_hash != second.prompt_hash


def test_few_shots_loaded_as_pairs() -> None:
    """Few-shot examples load as a tuple of input/output dicts."""
    bundle = _bundle()
    assert len(bundle.few_shots) >= 2  # type: ignore[attr-defined]
    for shot in bundle.few_shots:  # type: ignore[attr-defined]
        assert 'input' in shot
        assert 'output' in shot


def test_every_schema_field_is_named_in_the_prompt() -> None:
    """A field the prompt never mentions is a field the model cannot know to fill."""
    bundle = _bundle()
    text = bundle.system_template + '\n' + bundle.user_template  # type: ignore[attr-defined]
    missing = [name for name in ExtractionRecord.model_fields if name not in text]
    assert not missing, f'prompt never names: {missing}'


def test_few_shot_outputs_validate_against_the_schema() -> None:
    """An example the schema rejects teaches the model to fail validation."""
    for shot in _bundle().few_shots:  # type: ignore[attr-defined]
        record = ExtractionRecord.model_validate(json.loads(shot['output']))
        assert record.document_id.startswith('synthetic-')


def test_render_prompt_fills_variables() -> None:
    """The user template renders the document id and text."""
    bundle = _bundle()
    text = render_prompt(
        bundle,  # type: ignore[arg-type]
        {
            'document_id': 'doc-1',
            'document_text': 'hello',
            'max_evidence_words': 25,
            'themes': 'a,b',
        },
    )
    assert 'doc-1' in text
    assert 'hello' in text
