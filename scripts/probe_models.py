"""Probe candidate free models with a tiny structured-output request.

Candidates come from the command line (`--models a,b`) or from a file (`--models-file`),
never from a list baked into this script: which models are worth probing is a finding,
not a constant.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from _bootstrap import setup

from nowcast.llm.caller import LLMCaller

LOGGER = logging.getLogger('nowcast.scripts.probe_models')
PROMPT = 'Return exactly this JSON and nothing else: {"ok": true, "n": 3}'
JSON_INSTR = 'Respond with only a JSON object. No prose, no code fences.'


def candidates(args: argparse.Namespace) -> list[str]:
    """Return the model ids to probe, from the flag, a file, or the configured models."""
    if args.models:
        return [item.strip() for item in args.models.split(',') if item.strip()]
    if args.models_file:
        path = Path(args.models_file)
        return [
            line.strip()
            for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.strip().startswith('#')
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    """Call each candidate once and report latency, ok/fail and the reply's shape."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', default='', help='comma-separated model ids to probe')
    parser.add_argument('--models-file', default='', help='file with one model id per line')
    args = parser.parse_args(argv)
    config = setup()
    models = candidates(args) or list(config.llm.models)
    if not models:
        LOGGER.error('no models to probe; pass --models or --models-file')
        return 2
    with LLMCaller(config.llm) as caller:
        for model in models:
            started = time.monotonic()
            try:
                result = caller.complete(
                    model,
                    [
                        {'role': 'system', 'content': JSON_INSTR},
                        {'role': 'user', 'content': PROMPT},
                    ],
                )
                elapsed = time.monotonic() - started
                text = result.text.strip().replace('\n', ' ')[:80]
                shape = 'json-ok' if _is_json(text) else 'not-json'
                LOGGER.info(
                    '%s %.1fs tok=%d %s | %s', model, elapsed, result.total_tokens, shape, text
                )
            except Exception as exc:
                elapsed = time.monotonic() - started
                LOGGER.error('%s %.1fs %s: %s', model, elapsed, type(exc).__name__, str(exc)[:120])
            time.sleep(float(config.llm.retry_backoff_seconds))
    return 0


def _is_json(text: str) -> bool:
    """Return whether the reply parses as JSON."""
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


if __name__ == '__main__':
    raise SystemExit(main())
