"""Restricted smoke-process helpers for dotenv loading and redacted key provenance."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def load_dotenv_without_overriding(candidates: Iterable[Path]) -> None:
    """Fill unset variables from each existing file, never overriding set ones."""
    from dotenv import load_dotenv

    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(candidate, override=False)


def _sha8(value: str) -> str:
    """Return a short fingerprint of a secret: comparable, not reversible, not the secret."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]


def key_provenance(name: str, candidates: Iterable[Path]) -> dict[str, object]:
    """Return where `name` came from, without ever returning its value.

    `env` means the process environment, `dotenv` means an unset variable filled from a
    file, `missing` means neither. When both exist and disagree, that is warned about:
    `override=False` means an exported key silently beats the file, which looks exactly
    like a stale or revoked key and is the first thing to rule out when the provider says
    401.
    """
    from dotenv import dotenv_values

    exported = os.environ.get(name)
    file_values: list[tuple[Path, str]] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        value = dotenv_values(candidate).get(name)
        if value:
            file_values.append((candidate, str(value)))
    if exported:
        source = 'env'
        active = exported
    elif file_values:
        source = 'dotenv'
        active = file_values[0][1]
    else:
        LOGGER.warning('%s is not set in the environment or any .env file', name)
        return {'source': 'missing', 'key_len': 0, 'key_sha8': ''}

    for path, value in file_values:
        if exported and _sha8(value) != _sha8(exported):
            LOGGER.warning(
                '%s shadows the value in %s (exported %s…, file %s…); '
                'run `unset %s` to use the file',
                name,
                path,
                _sha8(exported),
                _sha8(value),
                name,
            )
    return {'source': source, 'key_len': len(active), 'key_sha8': _sha8(active)}
