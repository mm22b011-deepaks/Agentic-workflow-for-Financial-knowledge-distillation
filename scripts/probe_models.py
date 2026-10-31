"""Probe candidate free models with a tiny structured-output request."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from nowcast.config import load_config  # noqa: E402
from nowcast.llm.caller import LLMCaller  # noqa: E402

CANDIDATES = [
    'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free',
    'nvidia/nemotron-3-ultra-550b-a55b:free',
    'google/gemma-4-26b-a4b-it:free',
    'xingchen-agi/xing4.0-29b-a4b:free',
    'poolside/laguna-s-2.1:free',
    'thinkingmachines/inkling-small:free',
    'liquid/lfm-2.5-2.6b:free',
]

PROMPT = 'Return exactly this JSON and nothing else: {"ok": true, "n": 3}'

JSON_INSTR = 'Respond with only a JSON object. No prose, no code fences.'


def main() -> int:
    """Call each candidate once and print latency, ok/fail and reply head."""
    load_dotenv(ROOT / '.env', override=True)
    config = load_config(ROOT / 'configs' / 'config.yaml')
    with LLMCaller(config.llm) as caller:
        for model in CANDIDATES:
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
                try:
                    json.loads(text)
                    shape = 'json-ok'
                except json.JSONDecodeError:
                    shape = 'not-json'
                print(
                    f'OK   {model:52s} {elapsed:5.1f}s tok={result.total_tokens:5d} {shape} | {text}'
                )
            except Exception as exc:
                elapsed = time.monotonic() - started
                print(f'FAIL {model:52s} {elapsed:5.1f}s {type(exc).__name__}: {str(exc)[:120]}')
            time.sleep(1.0)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
