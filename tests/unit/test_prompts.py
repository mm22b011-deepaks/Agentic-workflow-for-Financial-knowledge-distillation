"""Unit tests for prompt loading and rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from nowcast.errors import ConfigError
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


def test_few_shots_loaded_as_pairs() -> None:
    """Few-shot examples load as a tuple of input/output dicts."""
    bundle = _bundle()
    assert len(bundle.few_shots) >= 2  # type: ignore[attr-defined]
    for shot in bundle.few_shots:  # type: ignore[attr-defined]
        assert 'input' in shot
        assert 'output' in shot


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
