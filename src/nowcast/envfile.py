"""Loading `.env` files without ever overriding the real environment.

The rule is the same for the CLI and the operator scripts: a variable already set in the
environment (a Colab secret, a shell export, a CI secret) always wins, and the checked-out
`.env` only fills what is missing. Implemented once here so the two entry points cannot
drift apart.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def load_dotenv_without_overriding(candidates: Iterable[Path]) -> None:
    """Fill unset variables from each existing file, never overriding set ones."""
    from dotenv import load_dotenv

    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(candidate, override=False)
