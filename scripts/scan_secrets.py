"""Scan the candidate tree and optional history; report file names only."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = (
    re.compile(rb'\bsk-or-v1-[a-fA-F0-9]{32,}\b'),
    re.compile(rb'\b(?:ghp|github_pat)_[a-zA-Z0-9_]{30,}\b'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(rb'(?i)(?:api[_-]?key|secret|password)\s*[=:]\s*[\x22\x27]?[A-Za-z0-9_/-]{32,}'),
)


def current_secrets(root: Path) -> tuple[bytes, ...]:
    """Read secrets only in this process, including a shadowed dotenv value."""
    from dotenv import dotenv_values

    values = [os.environ.get('OPENROUTER_API_KEY', '')]
    path = root / '.env'
    if path.is_file():
        values.append(dotenv_values(path).get('OPENROUTER_API_KEY') or '')
    return tuple({value.encode() for value in values if value})


def contains_secret(body: bytes, secrets: tuple[bytes, ...]) -> bool:
    if any(value in body for value in secrets):
        return True
    return b'\0' not in body and any(pattern.search(body) for pattern in PATTERNS)


def scan(paths: list[str], secrets: tuple[bytes, ...] | None = None) -> list[str]:
    """Inspect binary and text files without returning matched bytes."""
    values = current_secrets(Path.cwd()) if secrets is None else secrets
    return sorted(
        {
            name
            for name in paths
            if Path(name).is_file() and contains_secret(Path(name).read_bytes(), values)
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', help='Git revision range to audit')
    parser.add_argument(
        'files', nargs='*', help='Additional files; the full tree is always scanned'
    )
    args = parser.parse_args()
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
    os.chdir(root)
    values = current_secrets(root)
    candidates = (
        subprocess.check_output(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard']
        )
        .decode()
        .split('\0')
    )
    findings = set(scan([name for name in candidates + args.files if name], values))
    if args.history:
        commits = subprocess.check_output(['git', 'rev-list', args.history], text=True).splitlines()
        inspected: set[str] = set()
        for commit in commits:
            entries = subprocess.check_output(['git', 'ls-tree', '-rz', commit]).split(b'\0')
            for entry in entries:
                if not entry:
                    continue
                metadata, name = entry.split(b'\t', 1)
                _, kind, oid = metadata.decode().split()
                if kind != 'blob' or oid in inspected:
                    continue
                inspected.add(oid)
                body = subprocess.check_output(['git', 'cat-file', 'blob', oid])
                if contains_secret(body, values):
                    findings.add(name.decode())
    for name in sorted(findings):
        sys.stderr.write(name + '\n')
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
