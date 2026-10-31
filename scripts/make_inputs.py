"""Build the constituents CSV for a list of tickers, resolving CIKs from EDGAR.

The ticker list is an input, not part of the code: pass a file with one ticker per line
(`--tickers`), or leave it out to use `inputs/tickers.txt` under the data root. Nothing
here contains a ticker, a CIK or a URL.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import httpx
import pandas as pd
from _bootstrap import setup

from nowcast.config import Config, resolve_data_path

LOGGER = logging.getLogger('nowcast.scripts.make_inputs')


def read_tickers(path: Path) -> list[str]:
    """Read tickers from a text or CSV file, one per line, blanks and comments dropped."""
    if not path.is_file():
        raise FileNotFoundError(f'ticker list not found: {path}')
    tickers: list[str] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        value = line.split(',')[0].strip().upper()
        if value and not value.startswith('#'):
            tickers.append(value)
    return tickers


def ticker_to_cik(payload: dict[str, dict[str, object]]) -> dict[str, str]:
    """Map uppercase ticker to a ten-digit CIK from EDGAR's company_tickers payload."""
    mapping: dict[str, str] = {}
    for item in payload.values():
        mapping[str(item['ticker']).upper()] = str(item['cik_str']).zfill(10)
    return mapping


def build_rows(config: Config, tickers: list[str], client: httpx.Client) -> tuple[list[dict], list]:
    """Return constituent rows for the tickers EDGAR knows, plus the ones it does not."""
    response = client.get(config.universe.sec_ticker_map_url)
    response.raise_for_status()
    mapping = ticker_to_cik(json.loads(response.text))
    missing = [ticker for ticker in tickers if ticker not in mapping]
    rows = [
        {
            'ticker': ticker,
            'cik': mapping[ticker],
            'effective_from': config.data.start_date or '2020-01-01',
            'effective_to': config.data.end_date or '',
            'weight': 1.0,
        }
        for ticker in tickers
        if ticker in mapping
    ]
    return rows, missing


def main(argv: list[str] | None = None) -> int:
    """Write the constituents CSV for a given ticker list."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--tickers', default='', help='ticker list file (default: inputs/tickers.txt)'
    )
    parser.add_argument('--out', default='', help='output CSV (default: data.constituents_csv)')
    args = parser.parse_args(argv)
    config = setup()
    # Default lives beside the constituents file under DATA_DIR, not in the checkout:
    # the data root is the one place the operator keeps inputs.
    tickers_path = (
        Path(args.tickers) if args.tickers else resolve_data_path(config, 'inputs/tickers.txt')
    )
    out = Path(args.out) if args.out else resolve_data_path(config, config.data.constituents_csv)
    tickers = read_tickers(tickers_path)
    with httpx.Client(
        headers={'User-Agent': _user_agent(config)}, timeout=float(config.llm.timeout_seconds)
    ) as client:
        rows, missing = build_rows(config, tickers, client)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    LOGGER.info('wrote %s rows=%d missing=%s', out, len(rows), missing)
    return 0


def _user_agent(config: Config) -> str:
    """Return the configured SEC user agent, failing clearly when it is absent."""
    value = os.environ.get(config.data.sec_user_agent_env, '')
    if not value:
        raise SystemExit(
            f'environment variable {config.data.sec_user_agent_env!r} is not set; '
            'SEC requires a User-Agent with a contact address'
        )
    return value


if __name__ == '__main__':
    raise SystemExit(main())
