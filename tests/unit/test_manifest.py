"""Tests for the run manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nowcast.config import Config, load_config
from nowcast.errors import ConfigError
from nowcast.manifest import (
    file_fingerprint,
    finish_manifest,
    git_sha,
    package_versions,
    prompt_hashes,
    secret_names,
    start_manifest,
)

REPO = Path(__file__).resolve().parent.parent.parent
REQUIRED_KEYS = {
    'config_hash',
    'git_sha',
    'python_version',
    'package_versions',
    'seed',
    'started_at',
    'ended_at',
    'prompt_hashes',
    'input_fingerprints',
    'stage',
    'notes',
    'sample',
}


def _config(overrides: dict[str, object] | None = None) -> Config:
    """Load the shipped config with optional overrides."""
    return load_config(REPO / 'configs' / 'config.yaml', overrides=overrides)


def test_manifest_has_required_keys() -> None:
    """The serialised manifest carries every key the spec names."""
    manifest = start_manifest(_config(), stage='unit')
    finish_manifest(manifest)
    body = json.loads(manifest.to_json())
    assert set(body) == REQUIRED_KEYS
    assert body['ended_at'] is not None
    assert body['stage'] == 'unit'
    assert isinstance(body['package_versions'], dict)


def test_manifest_excludes_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An API key in the environment never appears in the manifest text."""
    fake_key = 'sk-or-v1-this-is-not-a-real-key-0123456789'
    monkeypatch.setenv('OPENROUTER_API_KEY', fake_key)
    monkeypatch.setenv('SEC_USER_AGENT', 'manifest-test pytest@example.com')
    config = _config()
    manifest = start_manifest(config, stage='secret-check')
    manifest.notes = f'leaked {fake_key} here'
    finish_manifest(manifest)
    text = manifest.to_json(config)
    assert fake_key not in text
    assert '<redacted:OPENROUTER_API_KEY>' in text
    assert 'pytest@example.com' not in text

    # Without a config the tampering is not scrubbed, which is why write() takes one.
    assert fake_key in manifest.to_json()


def test_manifest_write_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """write() creates parent folders and produces readable JSON."""
    monkeypatch.setenv('OPENROUTER_API_KEY', 'sk-test-value-not-real')
    config = _config()
    target = tmp_path / 'nested' / 'run.json'
    manifest = start_manifest(config, stage='write')
    assert manifest.write(target, config) == target
    body = json.loads(target.read_text(encoding='utf-8'))
    assert body['config_hash'] == manifest.config_hash
    assert 'sk-test-value-not-real' not in target.read_text(encoding='utf-8')


def test_config_hash_stable() -> None:
    """The same config hashed twice gives the same digest."""
    assert start_manifest(_config()).config_hash == start_manifest(_config()).config_hash


def test_config_hash_changes() -> None:
    """Changing one setting changes the digest."""
    base = start_manifest(_config()).config_hash
    changed = start_manifest(_config({'llm.temperature': 0.5})).config_hash
    assert base != changed


def test_secret_names_deduplicates() -> None:
    """Secret names are unique and non-empty."""
    config = _config()
    names = secret_names(config)
    assert len(names) == len(set(names))
    assert config.llm.api_key_env in names


def test_git_sha_is_str_or_none() -> None:
    """A repository without commits reports None rather than raising."""
    value = git_sha(REPO)
    assert value is None or (isinstance(value, str) and len(value) >= 7)


def test_package_versions_records_missing_as_none() -> None:
    """A tracked package that is not installed is recorded as None, not omitted."""
    versions = package_versions(('pandas', 'definitely-not-a-real-package-xyz'))
    assert versions['pandas']
    assert 'definitely-not-a-real-package-xyz' in versions
    assert versions['definitely-not-a-real-package-xyz'] is None


def test_file_fingerprint_of_missing_file_raises(tmp_path: Path) -> None:
    """Fingerprinting a missing file is an error, not an empty hash."""
    with pytest.raises(ConfigError):
        file_fingerprint(tmp_path / 'nope.csv')


def test_prompt_hashes_cover_system_and_user() -> None:
    """The prompt fingerprint names the system and user templates separately."""
    hashes = prompt_hashes(REPO / 'prompts', 'extraction', 'v1')
    assert set(hashes) == {'bundle', 'system', 'user'}
    assert all(len(value) == 64 for value in hashes.values())
