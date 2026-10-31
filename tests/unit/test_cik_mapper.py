"""Unit tests for CIK resolution: priority order, padding, and never guessing."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from nowcast.config import load_config
from nowcast.ingestion.universe.cik_mapper import (
    UNRESOLVED,
    load_overrides,
    map_ciks,
)

FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures' / 'universe'
REPO = Path(__file__).resolve().parent.parent.parent


def _sec_map() -> dict[str, str]:
    """Read the SEC ticker map fixture into a ticker -> CIK mapping."""
    payload = json.loads((FIXTURES / 'sec_ticker_map.json').read_text(encoding='utf-8'))
    return {item['ticker']: str(item['cik_str']).zfill(10) for item in payload.values()}


def _overrides() -> pd.DataFrame:
    """Load the override fixture through the real loader."""
    config = load_config(
        REPO / 'configs' / 'config.yaml',
        overrides={'universe.cik_overrides_csv': str(FIXTURES / 'cik_overrides.csv')},
    )
    return load_overrides(config, FIXTURES)


def _intervals(*rows: dict[str, object]) -> pd.DataFrame:
    """Build a membership frame from row dicts."""
    return pd.DataFrame(
        list(rows),
        columns=['ticker', 'company_name', 'effective_from', 'effective_to', 'cik_hint'],
    )


def test_cik_priority_override_over_hint_over_sec() -> None:
    """An override wins over a hint, and a hint wins over the SEC map."""
    frame = _intervals(
        {
            'ticker': 'BBB',
            'company_name': 'Beta Corp',
            'effective_from': pd.Timestamp('2021-06-01'),
            'effective_to': None,
            'cik_hint': '111111',
        },
        {
            'ticker': 'ZZZ',
            'company_name': 'Omega Systems',
            'effective_from': pd.Timestamp('2023-09-01'),
            'effective_to': None,
            'cik_hint': None,
        },
    )
    overrides = pd.DataFrame(
        [{'ticker': 'BBB', 'cik': '222222', 'effective_from': None, 'effective_to': None}]
    )
    result = map_ciks(frame, overrides, _sec_map())
    sources = dict(zip(result.frame['ticker'], result.frame['cik_source'], strict=True))
    ciks = dict(zip(result.frame['ticker'], result.frame['cik'], strict=True))
    assert sources == {'BBB': 'override', 'ZZZ': 'sec_map'}
    assert ciks['BBB'] == '0000222222'
    assert ciks['ZZZ'] == '0000123456'

    no_override = map_ciks(frame, pd.DataFrame(), _sec_map())
    hint_row = no_override.frame[no_override.frame['ticker'] == 'BBB'].iloc[0]
    assert hint_row['cik_source'] == 'hint'
    assert hint_row['cik'] == '0000111111'


def test_cik_never_fuzzy_matched() -> None:
    """A near-miss company name and a near-miss ticker resolve nothing."""
    frame = _intervals(
        {
            'ticker': 'AAAB',
            'company_name': 'Alpha Industriez',
            'effective_from': pd.Timestamp('2020-01-01'),
            'effective_to': None,
            'cik_hint': None,
        }
    )
    result = map_ciks(frame, pd.DataFrame(), _sec_map())
    assert result.frame.iloc[0]['cik'] == UNRESOLVED
    assert result.frame.iloc[0]['cik_source'] == UNRESOLVED
    assert len(result.unmapped) == 1


def test_cik_zero_padded_10_digits() -> None:
    """Every resolved CIK is a 10-character zero-padded digit string."""
    frame = _intervals(
        {
            'ticker': 'AAA',
            'company_name': 'Alpha Industries',
            'effective_from': pd.Timestamp('2020-01-01'),
            'effective_to': None,
            'cik_hint': '320193',
        }
    )
    result = map_ciks(frame, pd.DataFrame(), _sec_map())
    cik = str(result.frame.iloc[0]['cik'])
    assert cik == '0000320193'
    assert len(cik) == 10
    assert cik.isdigit()


def test_unmapped_written_to_csv(tmp_path: Path) -> None:
    """Unresolved rows carry ticker, company name and dates for a human to review."""
    frame = _intervals(
        {
            'ticker': 'QQQ',
            'company_name': 'Not A Member',
            'effective_from': pd.Timestamp('2021-01-01'),
            'effective_to': pd.Timestamp('2022-01-01'),
            'cik_hint': None,
        }
    )
    result = map_ciks(frame, pd.DataFrame(), _sec_map())
    path = tmp_path / 'unmapped.csv'
    result.unmapped.to_csv(path, index=False)
    written = pd.read_csv(path)
    assert list(written.columns) >= [
        'ticker',
        'company_name',
        'effective_from',
        'effective_to',
    ]
    assert written.iloc[0]['ticker'] == 'QQQ'
    assert written.iloc[0]['company_name'] == 'Not A Member'


def test_override_respects_date_window() -> None:
    """An override only applies inside its own date range."""
    frame = _intervals(
        {
            'ticker': 'CCC',
            'company_name': 'Gamma Holdings',
            'effective_from': pd.Timestamp('2022-03-15'),
            'effective_to': None,
            'cik_hint': None,
        },
        {
            'ticker': 'CCC',
            'company_name': 'Gamma Holdings',
            'effective_from': pd.Timestamp('2019-01-01'),
            'effective_to': None,
            'cik_hint': None,
        },
    )
    result = map_ciks(frame, _overrides(), _sec_map())
    by_start = {
        pd.Timestamp(record['effective_from']).year: record
        for record in result.frame.to_dict('records')
    }
    assert by_start[2022]['cik'] == '0009999999'
    assert by_start[2019]['cik'] == UNRESOLVED
