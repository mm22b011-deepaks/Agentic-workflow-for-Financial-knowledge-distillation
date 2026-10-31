"""Logging setup shared by the CLI and the scripts."""

from __future__ import annotations

import logging
import sys
from typing import TextIO

LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s %(message)s'
DATE_FORMAT = '%Y-%m-%dT%H:%M:%S'
HANDLER_PREFIX = 'nowcast'


class _BelowError(logging.Filter):
    """Pass everything below ERROR, so errors are not printed twice."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True for records handled by the ordinary output stream."""
        return record.levelno < logging.ERROR


def resolve_level(level: str | int | None) -> int:
    """Turn a configured level name into a logging level, defaulting to INFO."""
    if isinstance(level, int):
        return level
    if not level:
        return logging.INFO
    resolved = logging.getLevelName(str(level).strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def _handler(stream: TextIO, name: str) -> logging.StreamHandler:
    """Build a named stream handler with the project's format."""
    handler = logging.StreamHandler(stream)
    handler.set_name(name)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    return handler


def setup_logging(level: str | int | None = None, stdout: bool = False) -> None:
    """Configure root logging once; calling it again replaces this package's handlers.

    Handlers we installed are removed first, so a CLI run followed by a test does
    not print every line twice. For a CLI, ordinary output goes to stdout and
    errors still go to stderr, which is what a shell pipeline expects.
    """
    resolved = resolve_level(level)
    root = logging.getLogger()
    for existing in list(root.handlers):
        if str(existing.get_name()).startswith(HANDLER_PREFIX):
            root.removeHandler(existing)
    if stdout:
        out = _handler(sys.stdout, f'{HANDLER_PREFIX}-out')
        out.addFilter(_BelowError())
        out.setLevel(resolved)
        err = _handler(sys.stderr, f'{HANDLER_PREFIX}-err')
        err.setLevel(logging.ERROR)
        root.addHandler(out)
        root.addHandler(err)
    else:
        root.addHandler(_handler(sys.stderr, f'{HANDLER_PREFIX}-out'))
    root.setLevel(resolved)
