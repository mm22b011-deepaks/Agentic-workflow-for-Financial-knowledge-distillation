from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def scanner():
    path = Path(__file__).resolve().parents[2] / 'scripts/scan_secrets.py'
    spec = importlib.util.spec_from_file_location('secret_scan_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_values_are_found_in_binary_and_shadowed_dotenv(tmp_path: Path, monkeypatch):
    module = scanner()
    environment = 'env-' + 'a' * 24
    dotenv = 'dotenv-' + 'b' * 24
    monkeypatch.setenv('OPENROUTER_API_KEY', environment)
    (tmp_path / '.env').write_text('OPENROUTER_API_KEY=' + dotenv + '\n')
    for name, value in [('first.bin', environment), ('second.bin', dotenv)]:
        (tmp_path / name).write_bytes(b'\0' + value.encode())
    monkeypatch.chdir(tmp_path)
    assert module.scan(['first.bin', 'second.bin']) == ['first.bin', 'second.bin']


def test_scanner_reports_names_only_and_ignores_no_untracked_candidates(tmp_path: Path):
    import os

    module = scanner()
    source = Path(module.__file__)
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    value = 'probe-' + 'c' * 24
    (tmp_path / '.env').write_text('OPENROUTER_API_KEY=' + value + '\n')
    (tmp_path / '.gitignore').write_text('.env\n')
    (tmp_path / 'leak.bin').write_bytes(b'\0' + value.encode())
    result = subprocess.run(
        [sys.executable, str(source)],
        cwd=tmp_path,
        capture_output=True,
        env={**os.environ, 'OPENROUTER_API_KEY': 'different'},
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr == b'leak.bin\n'
    assert not result.stdout
    assert value.encode() not in result.stderr
