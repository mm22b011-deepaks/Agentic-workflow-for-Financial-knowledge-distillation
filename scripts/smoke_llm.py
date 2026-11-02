"""Live smoke test: one tiny call to each configured model through OpenRouter.

Reports where the API key came from (environment, `.env`, or nowhere) and a short
fingerprint of it — never the key itself. A 401 here is almost always an exported key
shadowing the one in `.env`: run `unset OPENROUTER_API_KEY` and try again.
"""

from __future__ import annotations

import argparse
import logging
import os

import httpx
from _bootstrap import ROOT, setup

from nowcast.envfile import key_provenance, load_dotenv_without_overriding
from nowcast.errors import BudgetExceeded
from nowcast.jobs import store_for
from nowcast.llm.throttle import SharedRequestLimiter

LOGGER = logging.getLogger('nowcast.scripts.smoke_llm')


def main(argv: list[str] | None = None) -> int:
    """Call every configured model with one short prompt and report the outcome."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--model', action='append', default=[], help='model id to call (repeatable; default: all)'
    )
    args = parser.parse_args(argv)
    config = setup()
    provenance = key_provenance(config.llm.api_key_env, (ROOT / '.env',))
    LOGGER.info('api key: %s', provenance)
    if provenance['source'] == 'missing':
        return 2
    models = args.model or list(config.llm.models)
    load_dotenv_without_overriding((ROOT / '.env',))
    failures = 0
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('alembic').setLevel(logging.WARNING)
    limiter = SharedRequestLimiter(
        store_for(config),
        config.llm.base_url,
        per_minute=int(config.llm.requests_per_minute),
        per_day=int(config.llm.requests_per_day),
    )
    with httpx.Client(timeout=config.llm.timeout_seconds) as client:
        for model in models:
            if not model.endswith(':free'):
                LOGGER.error('http_status=not_sent')
                failures += 1
                continue
            try:
                limiter.acquire()
                response = client.post(
                    config.llm.base_url.rstrip('/') + '/chat/completions',
                    headers={'Authorization': 'Bearer ' + os.environ[config.llm.api_key_env]},
                    json={
                        'model': model,
                        'max_tokens': 8,
                        'messages': [{'role': 'user', 'content': 'Reply ready'}],
                    },
                )
                LOGGER.info('http_status=%d', response.status_code)
                failures += int(not response.is_success)
            except BudgetExceeded:
                LOGGER.error('http_status=not_sent')
                failures += 1
                break
            except httpx.HTTPError:
                LOGGER.error('http_status=unavailable')
                failures += 1
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
