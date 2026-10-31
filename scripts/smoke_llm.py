"""Live smoke test: one tiny call to each configured model through OpenRouter."""

from __future__ import annotations

import argparse
import logging

from _bootstrap import setup

from nowcast.llm.caller import LLMCaller

LOGGER = logging.getLogger('nowcast.scripts.smoke_llm')


def main(argv: list[str] | None = None) -> int:
    """Call every configured model with one short prompt and report the outcome."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--model', action='append', default=[], help='model id to call (repeatable; default: all)'
    )
    args = parser.parse_args(argv)
    config = setup()
    models = args.model or list(config.llm.models)
    failures = 0
    with LLMCaller(config.llm) as caller:
        for model in models:
            try:
                result = caller.complete(
                    model,
                    [
                        {'role': 'system', 'content': 'Reply with the single word: ready'},
                        {'role': 'user', 'content': 'status?'},
                    ],
                )
                LOGGER.info('%s -> %r tokens=%d', model, result.text[:60], result.total_tokens)
            except Exception as exc:
                failures += 1
                LOGGER.error('%s -> %s: %s', model, type(exc).__name__, str(exc)[:300])
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
