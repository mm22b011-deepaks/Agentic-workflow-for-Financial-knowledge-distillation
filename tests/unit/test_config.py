"""Tests for config loading, overrides, hashing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from nowcast.config import Config, load_config, validate_config
from nowcast.errors import ConfigError
from nowcast.manifest import config_hash

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO / 'configs' / 'config.yaml'


def _config(overrides: dict[str, object] | None = None) -> Config:
    """Load the shipped config with optional overrides."""
    return load_config(CONFIG_PATH, overrides=overrides)


def test_config_hash_stable() -> None:
    """The same config twice gives the same hash."""
    assert config_hash(_config()) == config_hash(_config())


def test_config_hash_changes() -> None:
    """Changing llm.temperature changes the hash."""
    assert config_hash(_config()) != config_hash(_config({'llm.temperature': 0.7}))


def test_override_applies() -> None:
    """runtime.max_concurrency=3 gives 3, as an int not a string."""
    config = _config({'runtime.max_concurrency': 3})
    assert config.runtime.max_concurrency == 3
    assert isinstance(config.runtime.max_concurrency, int)


def test_override_list_from_comma_string() -> None:
    """A comma-separated override becomes a list of strings."""
    config = _config({'extraction.themes': 'pricing, demand'})
    assert config.extraction.themes == ('pricing', 'demand')


def test_env_data_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """DATA_DIR in the environment wins over the YAML value."""
    from nowcast.config import data_root

    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'from-env'))
    assert data_root(_config()) == (tmp_path / 'from-env').resolve()


def test_unknown_section_key_is_rejected() -> None:
    """An unknown key inside a known section is a ConfigError naming it."""
    with pytest.raises(ConfigError, match='unknown keys'):
        load_config(CONFIG_PATH, overrides={'llm.mystery': 'x'})


def test_unknown_top_level_section_is_rejected(tmp_path: Path) -> None:
    """A misspelled section name fails instead of silently keeping the defaults."""
    broken = tmp_path / 'config.yaml'
    broken.write_text('aggregaton:\n  min_constituents: 3\n', encoding='utf-8')
    with pytest.raises(ConfigError, match='unknown top-level section') as excinfo:
        load_config(broken)
    assert 'aggregaton' in str(excinfo.value)


def test_non_mapping_section_is_rejected(tmp_path: Path) -> None:
    """A section that is not a mapping produces a readable error."""
    broken = tmp_path / 'config.yaml'
    broken.write_text('llm: 3\n', encoding='utf-8')
    with pytest.raises(ConfigError, match='must be a mapping'):
        load_config(broken)


def test_missing_config_file_raises(tmp_path: Path) -> None:
    """A missing config file is a ConfigError, not FileNotFoundError."""
    with pytest.raises(ConfigError, match='not found'):
        load_config(tmp_path / 'absent.yaml')


def test_paid_model_is_rejected() -> None:
    """A model id without the :free suffix fails validation."""
    config = _config({'llm.models': 'openai/gpt-4o'})
    problems = validate_config(config)
    assert any('not a free model' in problem for problem in problems)


def test_strict_requires_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """--strict fails when the secret env vars are missing, naming them only."""
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    # Non-strict never looks at the environment, so the shipped config stays clean.
    assert validate_config(_config(), strict=False) == []
    with pytest.raises(ConfigError, match='OPENROUTER_API_KEY'):
        validate_config(_config(), strict=True)
