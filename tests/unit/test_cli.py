"""Tests for the command-line entry point."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.cli import main as pipeline_main

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO / 'configs' / 'config.yaml'


def main(argv):
    # These compatibility cases exercise the explicit full-window profile.
    return pipeline_main(
        [
            *argv,
            '--set',
            'scope.profile=custom',
            '--set',
            'scope.companies=0',
            '--set',
            'scope.seasons=0',
        ]
    )


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


def test_normal_cli_does_not_load_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    (tmp_path / '.env').write_text('DOTENV_ONLY_VALUE=from-file\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('DOTENV_ONLY_VALUE', raising=False)
    assert main(['validate-config', '--config', str(CONFIG_PATH)]) == 0
    assert 'DOTENV_ONLY_VALUE' not in os.environ


def test_validate_config_strict_reports_missing_env(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--strict exits 1 and names the missing variable without ever printing a value."""
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
    # The run's own report is written too, so "no documents" can be told apart from
    # "every request was refused" without digging through logs.
    report = json.loads((data / 'manifests' / 'ingest_report.json').read_text(encoding='utf-8'))
    assert report['documents'] == 0
    assert report['aborted'] is None
    # The sample is in both the manifest and the summary: how the run chose what to
    # read is part of what makes it reproducible.
    assert body['sample']['seed'] == 42
    assert body['sample']['companies'] == 1
    summary = json.loads((data / 'manifests' / 'ingest_summary.json').read_text(encoding='utf-8'))
    assert summary['sample']['ciks'] == 1
    assert summary['sample']['seasons'][0] == '2025Q1'


def test_ingest_report_written_even_when_aborted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An aborted ingest still leaves its report, naming the abort."""
    import json

    import nowcast.ingestion.edgar as edgar
    from nowcast.errors import DataError

    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setenv('DATA_DIR', str(data))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('SEC_USER_AGENT', 'abort-check pytest@example.com')
    constituents = data / 'constituents.csv'
    pd.DataFrame(
        [{'ticker': 'AAA', 'cik': '0000320193', 'effective_from': '2025-01-01', 'effective_to': ''}]
    ).to_csv(constituents, index=False)

    def fake_ingest(*_args: object, report: object = None, **_kwargs: object) -> list[dict]:
        assert report is not None, 'the CLI must pass a report for the abort path to record'
        report.companies = 3
        report.record_status(403)
        report.aborted = '3 consecutive blocked responses'
        raise DataError(report.aborted)

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
    assert code == 2
    report = json.loads((data / 'manifests' / 'ingest_report.json').read_text(encoding='utf-8'))
    assert report['aborted'] == '3 consecutive blocked responses'
    assert report['status_counts'] == {'403': 1}
    # Nothing was written to the index on the abort path.
    assert not (data / 'document_index.parquet').exists()


def test_operator_setup_never_loads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import runpy

    (tmp_path / '.env').write_text('DOTENV_ONLY_VALUE=from-file\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('DOTENV_ONLY_VALUE', raising=False)
    setup = runpy.run_path(str(REPO / 'scripts/_bootstrap.py'))['setup']
    setup()
    assert 'DOTENV_ONLY_VALUE' not in os.environ
