"""Interactive, secret-safe workstation initialization; no key-valued CLI arguments."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import dotenv_values

from nowcast.config import Config, load_config, validate_config
from nowcast.errors import BudgetExceeded, ConfigError
from nowcast.jobs import store_for
from nowcast.llm.throttle import SharedRequestLimiter
from nowcast.paths import Paths
from nowcast.scope import scope_summary
from nowcast.storage import atomic_bytes, atomic_json

FREE_NOTICE = 'Only free OpenRouter models (:free) are used. No paid requests are made.'
KEY = 'OPENROUTER_API_KEY'


def metadata(value: str) -> dict[str, Any]:
    return {
        'length': len(value),
        'sha8': hashlib.sha256(value.encode()).hexdigest()[:8] if value else '',
    }


def bootstrap(root: Path) -> None:
    inputs = [root / 'uv.lock', root / 'web/package-lock.json', root / 'mise.toml']
    digest = hashlib.sha256(b''.join(path.read_bytes() for path in inputs)).hexdigest()
    stamp = root / '.tools/bootstrap.sha256'
    if (
        not stamp.is_file()
        or stamp.read_text().strip() != digest
        or not (root / '.venv/bin/python').is_file()
        or not (root / 'web/dist/index.html').is_file()
    ):
        child = {k: v for k, v in os.environ.items() if k != KEY}
        subprocess.run([str(root / 'setup.sh'), 'bootstrap'], cwd=root, env=child, check=True)
    if not stamp.is_file():
        atomic_bytes((digest + '\n').encode(), stamp)


def write_dotenv(root: Path, updates: dict[str, str]) -> None:
    tracked = subprocess.run(
        ['git', 'ls-files', '--error-unmatch', '.env'], cwd=root, capture_output=True, check=False
    )
    if tracked.returncode == 0:
        raise ConfigError('.env is tracked; refusing to write credentials')
    path = root / '.env'
    lines = path.read_text().splitlines(keepends=True) if path.exists() else []
    for name, value in updates.items():
        replacement = name + '=' + json.dumps(value) + '\n'
        pattern = re.compile(r'^\s*(?:export\s+)?' + re.escape(name) + r'\s*=')
        found = False
        result = []
        for line in lines:
            if pattern.match(line):
                if not found:
                    result.append(replacement)
                found = True
            else:
                result.append(line)
        if not found:
            if result and not result[-1].endswith('\n'):
                result[-1] += '\n'
            result.append(replacement)
        lines = result
    if lines or updates:
        atomic_bytes(''.join(lines).encode(), path)


def verify_provider(config: Config, key: str, client: httpx.Client) -> dict[str, Any]:
    """Return allowlisted metadata only; bodies and key labels never leave this process."""
    result: dict[str, Any] = {
        'key_info': 'UNSURE',
        'pricing': 'UNSURE',
        'authenticated': False,
        'http_status': None,
        'model_requests': 0,
    }
    headers = {'Authorization': 'Bearer ' + key}
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        response = client.get(config.llm.base_url.rstrip('/') + '/key', headers=headers)
        result['http_status'] = response.status_code
        if response.status_code in {401, 403}:
            return result
        data = response.json().get('data', {}) if response.is_success else {}
        if (
            response.is_success
            and isinstance(data, dict)
            and ('is_free_tier' in data or isinstance(data.get('free_model_daily_requests'), dict))
        ):
            result['key_info'] = 'verified'
            result['authenticated'] = True
            usage = response.json()['data'].get('free_model_daily_requests')
            if isinstance(usage, dict) and all(
                isinstance(usage.get(name), int) for name in ('used', 'limit', 'remaining')
            ):
                result['account_usage'] = {
                    name: int(usage[name]) for name in ('used', 'limit', 'remaining')
                }
        else:
            limiter = SharedRequestLimiter(
                store_for(config),
                config.llm.base_url,
                config.llm.requests_per_minute,
                config.llm.requests_per_day,
            )
            limiter.acquire()
            result['model_requests'] = 1
            response = client.post(
                config.llm.base_url.rstrip('/') + '/chat/completions',
                headers=headers,
                json={
                    'model': config.llm.models[0],
                    'max_tokens': 8,
                    'messages': [{'role': 'user', 'content': 'Reply ready'}],
                },
            )
            result['http_status'] = response.status_code
            result['authenticated'] = response.is_success
        if result['authenticated'] and config.llm.models_url:
            response = client.get(config.llm.models_url, headers=headers)
            if response.is_success:
                listed = {
                    row['id']: row
                    for row in response.json().get('data', [])
                    if isinstance(row, dict) and 'id' in row
                }
                prices = []
                for model in config.llm.models:
                    pricing = listed.get(model, {}).get('pricing', {})
                    known = all(name in pricing for name in ('prompt', 'completion'))
                    if known:
                        zero = all(
                            float(pricing.get(name, 0)) == 0
                            for name in (
                                'prompt',
                                'completion',
                                'request',
                                'image',
                                'web_search',
                                'internal_reasoning',
                            )
                        )
                        if not zero:
                            result['pricing'] = 'rejected'
                            result['authenticated'] = False
                            return result
                    prices.append(known)
                if prices and all(prices):
                    result['pricing'] = 'verified'
    except (httpx.HTTPError, ValueError, TypeError, BudgetExceeded):
        pass
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yes', action='store_true')
    keys = parser.add_mutually_exclusive_group()
    keys.add_argument('--key-from-env', action='store_true')
    keys.add_argument('--no-key', action='store_true')
    parser.add_argument('--scope', choices=['small', 'standard', 'large', 'custom'])
    parser.add_argument('--daily-limit', type=int)
    parser.add_argument('--minute-limit', type=int)
    parser.add_argument('--sec-contact-from-env', action='store_true')
    return parser


def initialize(
    args: argparse.Namespace,
    root: Path,
    prompt: Callable[[str], str] | None = None,
    secret_prompt: Callable[[str], str] | None = None,
    client: httpx.Client | None = None,
) -> int:
    ask = prompt or input
    hidden = secret_prompt or getpass.getpass
    interactive = not args.yes and sys.stdin.isatty()
    try:
        if (
            subprocess.run(
                ['git', 'ls-files', '--error-unmatch', '.env'],
                cwd=root,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        ):
            raise ConfigError('.env is tracked; refusing credential initialization')
        bootstrap(root)
        print(FREE_NOTICE)
        config = load_config(root / 'configs/config.yaml', local=True)
        problems = validate_config(config)
        if problems:
            raise ConfigError('; '.join(problems))
        values = dotenv_values(root / '.env') if (root / '.env').exists() else {}
        saved = str(values.get(KEY) or '')
        exported = os.environ.get(KEY, '')
        if saved and exported and saved != exported:
            print(
                'Shadowed key: env '
                + json.dumps(metadata(exported))
                + '; dotenv '
                + json.dumps(metadata(saved))
            )
            print('Program uses env. Fix in current shell: unset OPENROUTER_API_KEY')
        updates = {}
        chosen = exported or saved
        if args.no_key:
            chosen = ''
        elif args.key_from_env:
            chosen = exported
            if chosen:
                updates[KEY] = chosen
        elif interactive:
            if chosen:
                print('Existing key ' + json.dumps(metadata(chosen)))
                if ask('Keep it? [Y/n] ').strip().lower() == 'n':
                    new = hidden('OpenRouter API key (input hidden):')
                    if new:
                        updates[KEY] = new
                    chosen = new
            else:
                chosen = hidden('OpenRouter API key (input hidden):')
                if chosen:
                    updates[KEY] = chosen
        if exported and updates.get(KEY) and exported != updates[KEY]:
            print(
                'Shadowed key: env '
                + json.dumps(metadata(exported))
                + '; dotenv '
                + json.dumps(metadata(updates[KEY]))
            )
            print('Program uses env. Fix in current shell: unset OPENROUTER_API_KEY')
        # An exported value remains authoritative even after a different value is saved.
        active = exported or updates.get(KEY, saved)
        if args.no_key or not chosen:
            active = ''
        contact = os.environ.get('SEC_USER_AGENT') or str(values.get('SEC_USER_AGENT') or '')
        if interactive:
            contact = ask('SEC contact (Name email) [' + contact + ']: ').strip() or contact
        if args.sec_contact_from_env:
            contact = os.environ.get('SEC_USER_AGENT', '')
        if contact and not re.fullmatch(r'.+\s+[^\s@]+@[^\s@]+\.[^\s@]+', contact):
            print('SEC contact invalid; SEC downloads disabled')
            contact = ''
        if contact:
            updates['SEC_USER_AGENT'] = contact
        else:
            print('SEC contact missing; SEC downloads disabled')
        daily = args.daily_limit if args.daily_limit is not None else config.llm.requests_per_day
        minute = (
            args.minute_limit if args.minute_limit is not None else config.llm.requests_per_minute
        )
        profile = args.scope or config.scope.profile
        if interactive:
            daily = int(
                ask(f'Daily requests, from your OpenRouter account; unverified [{daily}]: ')
                or daily
            )
            minute = int(
                ask(f'Per-minute requests, from your OpenRouter account; unverified [{minute}]: ')
                or minute
            )
            import dataclasses

            for name in ('small', 'standard', 'large'):
                candidate = dataclasses.replace(
                    config,
                    scope=dataclasses.replace(config.scope, profile=name),
                    llm=dataclasses.replace(config.llm, requests_per_day=daily),
                )
                plan = scope_summary(candidate)
                print(f'{name}: {plan["releases"]} releases; {plan["model_days"]} UTC days')
            profile = ask(f'Scope [{profile}]: ').strip() or profile
        if daily < 1 or minute < 1 or profile not in {'small', 'standard', 'large', 'custom'}:
            raise ConfigError('invalid scope or request limit')
        write_dotenv(root, updates)
        local = root / 'configs/local.yaml'
        choices = yaml.safe_load(local.read_text()) if local.exists() else {}
        choices = choices or {}
        choices.setdefault('scope', {})['profile'] = profile
        choices.setdefault('llm', {}).update(
            {'requests_per_day': daily, 'requests_per_minute': minute, 'offline': not bool(active)}
        )
        atomic_bytes(yaml.safe_dump(choices, sort_keys=False).encode(), local)
        config = load_config(root / 'configs/config.yaml', local=True)
        verification = {
            'authenticated': False,
            'key_info': 'UNSURE',
            'pricing': 'UNSURE',
            'http_status': None,
            'model_requests': 0,
        }
        if active:
            if client is None:
                with httpx.Client(timeout=20) as own:
                    verification = verify_provider(config, active, own)
            else:
                verification = verify_provider(config, active, client)
        if verification['http_status'] in {401, 403}:
            print('Authentication rejected; check shadowing. Continuing offline.')
        choices['llm']['offline'] = not verification['authenticated']
        atomic_bytes(yaml.safe_dump(choices, sort_keys=False).encode(), local)
        source = 'env' if exported and active else 'dotenv' if active else 'missing'
        summary = {
            'key_source': source,
            **metadata(active),
            'scope': profile,
            'forecast': scope_summary(config),
            'verification': verification,
            'offline': choices['llm']['offline'],
        }
        atomic_json(summary, Paths.from_config(config).resolve('manifests/setup.json'))
        print(json.dumps(summary, sort_keys=True))
        print('Next: ./setup.sh cli schedule plan')
        if interactive and ask('Install scheduler? [y/N] ').strip().lower() == 'y':
            subprocess.run(
                [str(root / 'setup.sh'), 'cli', 'schedule', 'install'], cwd=root, check=True
            )
        return 0
    except (ConfigError, ValueError, subprocess.SubprocessError):
        # Never render an exception that might contain entered input or provider text.
        print(
            'Setup refused: tracked .env, invalid choices, unsafe models, or missing bootstrap prerequisites.',
            file=sys.stderr,
        )
        return 2


def main() -> None:
    raise SystemExit(initialize(build_parser().parse_args(), Path(__file__).resolve().parents[2]))


if __name__ == '__main__':
    main()
