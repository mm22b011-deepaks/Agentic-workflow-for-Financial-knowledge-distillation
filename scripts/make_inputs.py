"""Build the constituents CSV by discovering large-cap CIKs from EDGAR's company_tickers file."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from dotenv import load_dotenv  # noqa: E402

from nowcast.config import load_config  # noqa: E402

TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
WANTED_TICKERS = [
    'AAPL',
    'MSFT',
    'NVDA',
    'AMZN',
    'GOOGL',
    'META',
    'TSLA',
    'AVGO',
    'BRK-B',
    'LLY',
    'JPM',
    'V',
    'UNH',
    'XOM',
    'MA',
    'COST',
    'HD',
    'PG',
    'JNJ',
    'WMT',
    'NFLX',
    'ABBV',
    'BAC',
    'CRM',
    'ORCL',
    'CVX',
    'MRK',
    'KO',
    'PEP',
    'AMD',
    'TMO',
    'ADBE',
    'CSCO',
    'ACN',
    'LIN',
    'MCD',
    'ABT',
    'DHR',
    'WFC',
    'TXN',
    'INTU',
    'QCOM',
    'PM',
    'CAT',
    'IBM',
    'GE',
    'AMGN',
    'NOW',
    'UBER',
    'SPGI',
]


def main() -> int:
    """Write inputs/constituents.csv from the EDGAR ticker file."""
    load_dotenv(ROOT / '.env', override=True)
    config = load_config(ROOT / 'configs' / 'config.yaml')
    agent = os.environ[config.data.sec_user_agent_env]
    response = httpx.get(TICKERS_URL, headers={'User-Agent': agent}, timeout=60.0)
    response.raise_for_status()
    payload = json.loads(response.text)
    by_ticker = {}
    for item in payload.values():
        ticker = str(item['ticker']).upper()
        if ticker in WANTED_TICKERS:
            by_ticker[ticker] = str(item['cik_str']).zfill(10)
    missing = [ticker for ticker in WANTED_TICKERS if ticker not in by_ticker]
    rows = [
        {
            'ticker': ticker,
            'cik': by_ticker[ticker],
            'effective_from': '2020-01-01',
            'effective_to': '2035-12-31',
            'weight': 1.0,
        }
        for ticker in WANTED_TICKERS
        if ticker in by_ticker
    ]
    out = ROOT / 'inputs' / 'constituents.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f'wrote {out} rows={len(rows)} missing={missing}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
