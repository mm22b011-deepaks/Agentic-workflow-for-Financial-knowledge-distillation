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
