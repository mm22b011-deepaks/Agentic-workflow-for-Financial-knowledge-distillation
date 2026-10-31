"""Live smoke test: one tiny call to each configured model through OpenRouter."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from nowcast.config import load_config  # noqa: E402
from nowcast.llm.caller import LLMCaller  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def main() -> int:
    """Call every configured model with one short prompt and report the outcome."""
    load_dotenv(ROOT / '.env', override=True)
    config = load_config(ROOT / 'configs' / 'config.yaml')
    failures = 0
    with LLMCaller(config.llm) as caller:
        for model in config.llm.models:
            try:
                result = caller.complete(
                    model,
                    [
                        {'role': 'system', 'content': 'Reply with the single word: ready'},
                        {'role': 'user', 'content': 'status?'},
                    ],
                )
                print(f'OK   {model} -> {result.text[:60]!r} tokens={result.total_tokens}')
            except Exception as exc:
                failures += 1
                print(f'FAIL {model} -> {type(exc).__name__}: {str(exc)[:300]}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
