"""Tests for the command-line entry point."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.cli import main

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO / 'configs' / 'config.yaml'


def test_validate_config_cli_ok(capsys: pytest.CaptureFixture[str]) -> None:
    """validate-config prints OK and exits zero for the shipped config."""
    code = main(['validate-config', '--config', str(CONFIG_PATH)])
    out = capsys.readouterr().out
    assert code == 0
    assert 'config OK' in out
    assert 'data root' in out


def test_validate_config_cli_reports_problems(capsys: pytest.CaptureFixture[str]) -> None:
    """A bad override surfaces as a problem line and a non-zero exit."""
    code = main(
        [
            'validate-config',
            '--config',
            str(CONFIG_PATH),
            '--set',
            'llm.models=openai/gpt-4o',
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert 'not a free model' in out


def test_unknown_config_key_is_a_config_error(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown config key fails cleanly instead of raising TypeError."""
    code = main(['validate-config', '--config', str(CONFIG_PATH), '--set', 'universe.not_a_key=1'])
    err = capsys.readouterr().err
    assert code == 2
    assert 'unknown keys' in err
    assert 'not_a_key' in err


def test_missing_config_file_is_a_config_error(capsys: pytest.CaptureFixture[str]) -> None:
    """A missing config file exits 2 with a readable message."""
    code = main(['validate-config', '--config', 'does/not/exist.yaml'])
    err = capsys.readouterr().err
    assert code == 2
    assert 'config file not found' in err


def test_estimate_scope_cli_is_offline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """estimate-scope prints a labelled estimate and never opens a socket."""
    import socket

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('estimate-scope opened a socket')

    monkeypatch.setattr(socket.socket, 'connect', refuse)

    path = tmp_path / 'constituents.csv'
    pd.DataFrame(
        [
            {
                'ticker': 'AAA',
                'cik': '0000320193',
                'effective_from': '2025-01-01',
                'effective_to': '',
                'company_name': 'Alpha Industries',
            }
        ]
    ).to_csv(path, index=False)

    code = main(
        [
            'estimate-scope',
            '--config',
            str(CONFIG_PATH),
            '--set',
            f'data.constituents_csv={path}',
            '--set',
            'data.start_date=2025-01-01',
            '--set',
            'data.end_date=2025-12-31',
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert 'ESTIMATE ONLY' in out
    assert 'expected documents' in out
    assert '$0.00' in out


def test_dotenv_never_overrides_real_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real environment variable wins over .env, so deployed secrets are not clobbered."""
    from nowcast.cli import _bootstrap_dotenv

    dotenv = tmp_path / '.env'
    dotenv.write_text(
        'SEC_USER_AGENT=from-file\nDOTENV_ONLY_VALUE=only-in-file\n', encoding='utf-8'
    )
    monkeypatch.setenv('SEC_USER_AGENT', 'from-real-env')
    monkeypatch.delenv('DOTENV_ONLY_VALUE', raising=False)

    _bootstrap_dotenv((dotenv,))
    import os

    assert os.environ['SEC_USER_AGENT'] == 'from-real-env'
    assert os.environ['DOTENV_ONLY_VALUE'] == 'only-in-file'


def test_validate_config_strict_reports_missing_env(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--strict exits 1 and names the missing variable without ever printing a value."""
    import nowcast.cli as cli

    # The repository .env supplies the key, so disable that source to model a bare CI box.
    monkeypatch.setattr(cli, '_bootstrap_dotenv', lambda *args, **kwargs: None)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    code = main(['validate-config', '--config', str(CONFIG_PATH), '--strict'])
    out = capsys.readouterr().out
    assert code == 1
    assert 'OPENROUTER_API_KEY' in out
    assert 'is not set' in out


def test_ingest_records_a_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A completed ingest leaves a manifest with the input fingerprint and no secrets."""
    import json

    import nowcast.ingestion.edgar as edgar

    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setenv('DATA_DIR', str(data))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'sk-or-v1-manifest-check-not-real')
    monkeypatch.setenv('SEC_USER_AGENT', 'manifest-check pytest@example.com')

    constituents = data / 'constituents.csv'
    pd.DataFrame(
        [
            {
                'ticker': 'AAA',
                'cik': '0000320193',
                'effective_from': '2025-01-01',
                'effective_to': '',
            }
        ]
    ).to_csv(constituents, index=False)

    def fake_ingest(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(edgar, 'ingest_edgar', fake_ingest)
    code = main(
        [
            'ingest',
            '--config',
            str(CONFIG_PATH),
            '--set',
            f'data.constituents_csv={constituents}',
        ]
    )
    assert code == 0
    manifest_path = data / 'manifests' / 'ingest.manifest.json'
    assert manifest_path.is_file()
    text = manifest_path.read_text(encoding='utf-8')
    body = json.loads(text)
    assert body['stage'] == 'ingest'
    assert body['ended_at']
    assert 'constituents.csv' in body['input_fingerprints']
    assert 'sk-or-v1-manifest-check-not-real' not in text
    assert 'pytest@example.com' not in text
