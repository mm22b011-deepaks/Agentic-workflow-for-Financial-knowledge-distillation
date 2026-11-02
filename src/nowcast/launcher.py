"""Dedicated child launcher: load private dotenv without overriding the shell."""

from __future__ import annotations

import runpy
from pathlib import Path

from nowcast.envfile import load_dotenv_without_overriding


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    load_dotenv_without_overriding((root / '.env',))
    runpy.run_module('nowcast.app', run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    main()
