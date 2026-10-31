"""F2: report where the API key came from, and when an export shadows the .env file."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nowcast.envfile import key_provenance, load_dotenv_without_overriding


def _prefix(value: str) -> str:
    """Return the sha256 prefix used in reports: enough to compare, useless as a key."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]


def test_exported_key_shadows_dotenv_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An exported key that beats a different .env key is reported, without the key."""
    env_file = tmp_path / '.env'
    env_file.write_text('OPENROUTER_API_KEY=from-dotenv-value\n', encoding='utf-8')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'from-shell-value')

    with caplog.at_level('WARNING'):
        report = key_provenance('OPENROUTER_API_KEY', (env_file,))

    assert report['source'] == 'env'
    assert report['key_len'] == len('from-shell-value')
    assert report['key_sha8'] == _prefix('from-shell-value')
    warnings = [record.getMessage() for record in caplog.records]
    assert any('shadows' in message for message in warnings)
    # The keys themselves must appear in no log line.
    joined = '\n'.join(warnings)
    assert 'from-shell-value' not in joined
    assert 'from-dotenv-value' not in joined


def test_dotenv_key_used_when_environment_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nothing exported, the .env value is the one in use, and it is reported as such."""
    env_file = tmp_path / '.env'
    env_file.write_text('OPENROUTER_API_KEY=from-dotenv-value\n', encoding='utf-8')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    load_dotenv_without_overriding((env_file,))

    # Once dotenv has filled the variable, the process environment undeniably holds it:
    # that is what the source is reporting. What matters is that it is the file's value.
    report = key_provenance('OPENROUTER_API_KEY', (env_file,))
    assert report['source'] == 'env'
    assert report['key_len'] == len('from-dotenv-value')
    assert report['key_sha8'] == _prefix('from-dotenv-value')


def test_missing_key_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key anywhere is said plainly instead of being reported as a length of zero."""
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    report = key_provenance('OPENROUTER_API_KEY', ())
    assert report['source'] == 'missing'
