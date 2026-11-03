from __future__ import annotations

import dataclasses
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import yaml

from nowcast.config import load_config

ROOT = Path(__file__).resolve().parents[2]


def checkout(tmp_path):
    (tmp_path / 'configs').mkdir()
    shutil.copy2(ROOT / 'configs/config.yaml', tmp_path / 'configs/config.yaml')
    shutil.copy2(ROOT / 'configs/registry.yaml', tmp_path / 'configs/registry.yaml')
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    return tmp_path


def test_website_refreshes_generated_ui_before_serving_from_any_directory(tmp_path):
    root = checkout(tmp_path)
    shutil.copy2(ROOT / 'setup.sh', root / 'setup.sh')
    python = root / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\nprintf "python %s\\n" "$*" >> startup-log\n')
    python.chmod(0o755)
    mise = root / '.tools/bin/mise'
    mise.parent.mkdir(parents=True)
    mise.write_text('#!/bin/sh\nprintf "mise %s\\n" "$*" >> startup-log\n')
    mise.chmod(0o755)
    child = {**os.environ, 'PATH': str(mise.parent) + os.pathsep + os.environ['PATH']}
    subprocess.run(
        ['/bin/bash', str(root / 'setup.sh'), 'website', '--port', '8768'],
        cwd=root.parent,
        env=child,
        check=True,
    )
    lines = (root / 'startup-log').read_text().splitlines()
    assert len(lines) == 3
    assert 'bootstrap(Path.cwd())' in lines[0]
    assert lines[1] == 'mise exec -- make references web-build'
    assert lines[2] == 'mise exec -- .venv/bin/python -m nowcast.launcher serve --port 8768'


@pytest.mark.parametrize('arguments', [[], ['init', '--yes', '--no-key']])
def test_bare_setup_enters_wizard_and_forwards_explicit_init_flags(tmp_path, arguments):
    root = checkout(tmp_path)
    shutil.copy2(ROOT / 'setup.sh', root / 'setup.sh')
    python = root / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > wizard-arguments\n')
    python.chmod(0o755)
    mise = root / '.tools/bin/mise'
    mise.parent.mkdir(parents=True)
    mise.write_text('#!/bin/sh\nexit 70\n')
    mise.chmod(0o755)
    child = {k: v for k, v in os.environ.items() if k != 'OPENROUTER_API_KEY'}
    child['PATH'] = str(mise.parent) + os.pathsep + os.environ['PATH']
    result = subprocess.run(
        ['/bin/bash', str(root / 'setup.sh'), *arguments],
        cwd=root,
        env=child,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert (root / 'wizard-arguments').read_text().splitlines() == [
        '-m',
        'nowcast.setup_wizard',
        *arguments[1:],
    ]


def test_missing_dotenv_key_prompts_even_when_an_exported_key_exists(tmp_path, monkeypatch, capsys):
    from dotenv import dotenv_values

    from nowcast.setup_wizard import build_parser, initialize

    root = checkout(tmp_path)
    exported = 'exported-' + 'a' * 24
    pasted = 'pasted-' + 'b' * 24
    monkeypatch.setenv('OPENROUTER_API_KEY', exported)
    monkeypatch.setattr('nowcast.setup_wizard.bootstrap', lambda root: None)
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    prompts = []

    def hidden(label):
        prompts.append(label)
        return pasted

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
        assert (
            initialize(
                build_parser().parse_args([]),
                root,
                prompt=lambda label: '',
                secret_prompt=hidden,
                client=client,
            )
            == 0
        )
    assert prompts == ['OpenRouter API key (input hidden):']
    assert dotenv_values(root / '.env')['OPENROUTER_API_KEY'] == pasted
    assert (root / '.env').stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    assert pasted not in output.out + output.err and exported not in output.out + output.err
    assert 'unset OPENROUTER_API_KEY' in output.out


def test_noninteractive_skip_key_is_offline_and_does_not_prompt(tmp_path, monkeypatch, capsys):
    from nowcast.setup_wizard import build_parser, initialize

    root = checkout(tmp_path)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'exported-' + 'x' * 20)
    monkeypatch.setattr('nowcast.setup_wizard.bootstrap', lambda root: None)
    monkeypatch.setattr('builtins.input', lambda *args: pytest.fail('non-TTY prompted'))
    assert (
        initialize(build_parser().parse_args(['--yes', '--no-key', '--scope', 'standard']), root)
        == 0
    )
    local = yaml.safe_load((root / 'configs/local.yaml').read_text())
    assert local['llm']['offline'] is True
    assert local['scope']['profile'] == 'standard'
    assert 'exported-' not in capsys.readouterr().out
    assert not (root / '.env').exists()


def test_empty_hidden_input_skips_key_without_provider_calls(tmp_path, monkeypatch):
    from nowcast.setup_wizard import build_parser, initialize

    root = checkout(tmp_path)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    monkeypatch.setattr('nowcast.setup_wizard.bootstrap', lambda root: None)
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail('skipped key made a request'))
    ) as client:
        assert (
            initialize(
                build_parser().parse_args([]),
                root,
                prompt=lambda label: '',
                secret_prompt=lambda label: '',
                client=client,
            )
            == 0
        )
    assert load_config(root / 'configs/config.yaml', local=True).llm.offline
    assert not (root / '.env').exists()


def test_interactive_rerun_keeps_saved_key_without_another_secret_prompt(tmp_path, monkeypatch):
    from dotenv import dotenv_values

    from nowcast.setup_wizard import build_parser, initialize

    root = checkout(tmp_path)
    saved = 'saved-' + 'c' * 24
    (root / '.env').write_text('OPENROUTER_API_KEY=' + saved + '\n')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr('nowcast.setup_wizard.bootstrap', lambda root: None)
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
        assert (
            initialize(
                build_parser().parse_args([]),
                root,
                prompt=lambda label: '',
                secret_prompt=lambda label: pytest.fail('saved key prompted again'),
                client=client,
            )
            == 0
        )
    assert dotenv_values(root / '.env')['OPENROUTER_API_KEY'] == saved


def test_hidden_key_is_private_preserves_lines_and_redacts_shadow(tmp_path, monkeypatch, capsys):
    from nowcast.setup_wizard import build_parser, initialize

    root = checkout(tmp_path)
    file_key = 'file-' + 'a' * 24
    export_key = 'export-' + 'b' * 24
    (root / '.env').write_text('UNRELATED=keep\nOPENROUTER_API_KEY=' + file_key + '\n')
    monkeypatch.setenv('OPENROUTER_API_KEY', export_key)
    monkeypatch.setenv('SEC_USER_AGENT', 'Tester test@example.invalid')
    monkeypatch.setattr('nowcast.setup_wizard.bootstrap', lambda root: None)

    def response(request):
        return httpx.Response(
            200,
            json={
                'data': {
                    'label': export_key,
                    'free_model_daily_requests': {'limit': 50, 'used': 2, 'remaining': 48},
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert (
            initialize(
                build_parser().parse_args(['--yes', '--scope', 'small', '--sec-contact-from-env']),
                root,
                client=client,
            )
            == 0
        )
    out = capsys.readouterr().out
    assert file_key not in out and export_key not in out
    assert hashlib.sha256(export_key.encode()).hexdigest()[:8] in out
    assert 'unset OPENROUTER_API_KEY' in out
    assert (root / '.env').stat().st_mode & 0o777 == 0o600
    body = (root / '.env').read_text()
    assert 'UNRELATED=keep' in body and file_key in body
    assert load_config(root / 'configs/config.yaml', local=True).scope.profile == 'small'


def test_tracked_dotenv_is_refused_without_showing_values(tmp_path, monkeypatch, capsys):
    from nowcast.setup_wizard import build_parser, initialize

    root = checkout(tmp_path)
    value = 'tracked-' + 'c' * 24
    (root / '.env').write_text('OPENROUTER_API_KEY=' + value + '\n')
    subprocess.run(['git', 'add', '.env'], cwd=root, check=True)
    monkeypatch.setattr('nowcast.setup_wizard.bootstrap', lambda root: None)
    assert initialize(build_parser().parse_args(['--yes', '--no-key']), root) == 2
    out = capsys.readouterr()
    assert value not in out.out + out.err
    assert 'tracked' in out.err


def test_provider_error_never_echoes_the_active_key(config, monkeypatch):
    from nowcast.errors import AuthError
    from nowcast.llm.caller import LLMCaller

    value = 'probe-' + 'd' * 24
    monkeypatch.setenv(config.llm.api_key_env, value)
    config = dataclasses.replace(config, llm=dataclasses.replace(config.llm, models_url=''))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401, json={'error': {'message': 'User not found ' + value}}, request=request
        )
    )
    caller = LLMCaller(config.llm, transport=transport)
    with pytest.raises(AuthError) as caught:
        caller.complete('probe:free', [{'role': 'user', 'content': 'ready'}])
    assert value not in str(caught.value)


def test_local_layer_does_not_modify_base_or_override_explicit_flags(tmp_path):
    root = checkout(tmp_path)
    before = (root / 'configs/config.yaml').read_bytes()
    (root / 'configs/local.yaml').write_text(
        'scope:\n  profile: small\nllm:\n  requests_per_day: 37\n'
    )
    config = load_config(
        root / 'configs/config.yaml', overrides={'llm.requests_per_day': '23'}, local=True
    )
    assert config.scope.profile == 'small' and config.llm.requests_per_day == 23
    assert before == (root / 'configs/config.yaml').read_bytes()


def test_pseudoterminal_hides_key_and_rerun_keeps_defaults(tmp_path):
    import pty
    import select
    import time

    root = checkout(tmp_path)
    value = 'tty-' + os.urandom(12).hex()
    code = """import os,httpx
from pathlib import Path
import nowcast.setup_wizard as wizard
wizard.bootstrap=lambda root:None
transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':{}}))
with httpx.Client(transport=transport) as client:
 wizard.initialize(wizard.build_parser().parse_args([]),Path(os.environ['WIZARD_TEST_ROOT']),client=client)
"""
    pid, fd = pty.fork()
    if pid == 0:
        child = {
            k: v
            for k, v in os.environ.items()
            if k not in {'OPENROUTER_API_KEY', 'SEC_USER_AGENT', 'DATA_DIR'}
        }
        child['WIZARD_TEST_ROOT'] = str(root)
        os.execve(sys.executable, [sys.executable, '-c', code], child)
    transcript = b''
    prompts = [
        (b'OpenRouter API key (input hidden):', value + '\n'),
        (b'SEC contact', '\n'),
        (b'Daily requests', '\n'),
        (b'Per-minute requests', '\n'),
        (b'Scope [', '\n'),
        (b'Install scheduler?', 'n\n'),
    ]
    index = 0
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                transcript += chunk
                if index < len(prompts) and prompts[index][0] in transcript:
                    os.write(fd, prompts[index][1].encode())
                    index += 1
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        if index != len(prompts):
            pytest.fail('wizard prompts incomplete', pytrace=False)
        if value.encode() in transcript:
            pytest.fail('hidden key appeared in PTY output', pytrace=False)
        assert (root / '.env').stat().st_mode & 0o777 == 0o600
        before = (root / '.env').read_bytes()
        from unittest.mock import patch

        from nowcast.setup_wizard import build_parser, initialize

        with (
            patch('nowcast.setup_wizard.bootstrap', lambda root: None),
            patch.dict(os.environ, {'OPENROUTER_API_KEY': '', 'SEC_USER_AGENT': ''}),
        ):
            assert initialize(build_parser().parse_args(['--yes', '--no-key']), root) == 0
        assert (root / '.env').read_bytes() == before
    finally:
        os.close(fd)


def test_init_rejects_paid_models_before_reading_a_key(tmp_path, monkeypatch):
    from nowcast.setup_wizard import build_parser, initialize

    root = checkout(tmp_path)
    path = root / 'configs/config.yaml'
    config = yaml.safe_load(path.read_text())
    config['llm']['models'] = ['provider/paid']
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr('nowcast.setup_wizard.bootstrap', lambda root: None)
    assert initialize(build_parser().parse_args(['--yes', '--no-key']), root) == 2
    assert not (root / '.env').exists()


def test_tiny_fallback_reserves_one_request_and_401_stops(tmp_path, monkeypatch):
    from sqlalchemy import text

    from nowcast.jobs import store_for
    from nowcast.setup_wizard import build_parser, initialize

    root = checkout(tmp_path)
    value = 'fallback-' + os.urandom(12).hex()
    (root / '.env').write_text('OPENROUTER_API_KEY=' + value + '\n')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr('nowcast.setup_wizard.bootstrap', lambda root: None)
    calls = []

    def response(request):
        calls.append(request.method)
        if request.url.path.endswith('/key'):
            return httpx.Response(404, json={})
        if request.method == 'POST':
            return httpx.Response(200, json={'choices': []})
        return httpx.Response(200, json={'data': []})

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert initialize(build_parser().parse_args(['--yes']), root, client=client) == 0
    config = load_config(root / 'configs/config.yaml', local=True)
    with store_for(config).engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM reservations')).scalar_one() == 1
    calls.clear()

    def rejected(request):
        calls.append(request.method)
        return httpx.Response(401, json={'error': {'message': value}})

    with httpx.Client(transport=httpx.MockTransport(rejected)) as client:
        assert initialize(build_parser().parse_args(['--yes']), root, client=client) == 0
    assert calls == ['GET']
    assert load_config(root / 'configs/config.yaml', local=True).llm.offline


def test_success_response_cannot_persist_an_echoed_key(config, monkeypatch):
    from nowcast.errors import AuthError
    from nowcast.llm.caller import LLMCaller

    value = 'echo-' + os.urandom(12).hex()
    monkeypatch.setenv(config.llm.api_key_env, value)
    local = dataclasses.replace(config.llm, models_url='')
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={'choices': [{'message': {'content': value}}]}, request=request
        )
    )
    with pytest.raises(AuthError) as caught:
        LLMCaller(local, transport=transport).complete(
            'probe:free', [{'role': 'user', 'content': 'ready'}]
        )
    assert 'credential material' in str(caught.value)
    if value in str(caught.value):
        pytest.fail('credential disclosure', pytrace=False)
