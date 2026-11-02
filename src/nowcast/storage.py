"""Atomic local artifact replacement; temporary files stay beside their targets."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_parquet(frame: Any, target: Path) -> None:
    """Publish a complete parquet file with one atomic rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=target.name + '.', suffix='.part', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            frame.to_parquet(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def atomic_bytes(body: bytes, target: Path, mode: int = 0o600) -> None:
    """Publish private bytes atomically, including the directory entry."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=target.name + '.', suffix='.part', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
        directory = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def atomic_json(value: Any, target: Path) -> None:
    import json

    atomic_bytes((json.dumps(value, indent=2, allow_nan=False) + '\n').encode(), target)


from contextlib import contextmanager  # noqa: E402


@contextmanager
def file_lock(target: Path, blocking: bool = True) -> Any:
    import fcntl

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_suffix(target.suffix + '.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
