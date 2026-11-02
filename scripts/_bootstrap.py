"""Checkout-relative configuration and logging for scripts; credentials are environment-only."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from nowcast.config import Config, load_config  # noqa: E402
from nowcast.logging_setup import setup_logging  # noqa: E402


def setup(level: int = logging.INFO) -> Config:
    """Load checkout configuration and logging without loading secret files."""
    # The same formatter and stdout/stderr split the CLI uses, so a script's report is
    # greppable beside the CLI's and nothing is printed through two channels.
    setup_logging(level, stdout=True)
    return load_config(ROOT / 'configs' / 'config.yaml')
