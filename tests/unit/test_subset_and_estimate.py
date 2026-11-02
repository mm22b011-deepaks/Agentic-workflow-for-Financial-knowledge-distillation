"""Tests for the deterministic subset sampler and the offline estimate-scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

from nowcast.config import Config, load_config
from nowcast.errors import DataError
from nowcast.ingestion.universe.builder import (
    deterministic_subset,
    estimate_scope,
)

REPO = Path(__file__).resolve().parent.parent.parent


def _frame(count: int = 20) -> pd.DataFrame:
    """Build a frame with `count` tickers, each with two intervals."""
    rows: list[dict[str, Any]] = []
    for index in range(count):
        ticker = f'T{index:03d}'
        rows.append(
            {
                'ticker': ticker,
                'company_name': f'Company {index}',
                'effective_from': pd.Timestamp('2020-01-01'),
                'effective_to': pd.Timestamp('2021-01-01'),
                'cik': f'{index:010d}',
                'cik_source': 'sec_map',
            }
        )
        rows.append(
            {
                'ticker': ticker,
                'company_name': f'Company {index}',
                'effective_from': pd.Timestamp('2022-01-01'),
                'effective_to': pd.NaT,
                'cik': f'{index:010d}',
                'cik_source': 'sec_map',
            }
        )
    return pd.DataFrame(rows)


def _config(**overrides: Any) -> Config:
    """Load the project config with the given overrides."""
    values = {
        'data.start_date': '2022-01-01',
        'data.end_date': '2024-12-31',
        'universe.avg_tokens_per_doc_in': '6000',
        'universe.avg_tokens_per_doc_out': '800',
    }
    values.update(overrides)
    return load_config(REPO / 'configs' / 'config.yaml', overrides=values)


def test_subset_is_deterministic_for_same_seed() -> None:
    """The same seed always selects the same companies and keeps all their intervals."""
    frame = _frame()
    first = deterministic_subset(frame, 5, 42)
    second = deterministic_subset(frame, 5, 42)
    assert sorted(first['ticker'].unique()) == sorted(second['ticker'].unique())
    assert len(first['ticker'].unique()) == 5
    # Both intervals of every chosen company are kept, never a dangling half.
    counts = first.groupby('ticker').size()
    assert (counts == 2).all()
    assert len(first) == 10


def test_subset_changes_with_seed() -> None:
    """A different seed selects a different sample, and both are still size n."""
    frame = _frame(count=50)
    seed_a = set(deterministic_subset(frame, 5, 42)['ticker'])
    seed_b = set(deterministic_subset(frame, 5, 7)['ticker'])
    assert len(seed_a) == len(seed_b) == 5
    assert seed_a != seed_b


def test_subset_of_zero_returns_everything() -> None:
    """subset_n = 0 means the full universe, per the config contract."""
    frame = _frame()
    assert len(deterministic_subset(frame, 0, 42)) == len(frame)


def _write_constituents(path: Path, count: int = 3) -> Path:
    """Write a small constituents CSV in the builder's output format."""
    rows = [
        {
            'ticker': f'T{index:03d}',
            'cik': f'{index:010d}',
            'effective_from': '2022-01-01',
            'effective_to': '',
            'company_name': f'Company {index}',
            'cik_source': 'sec_map',
        }
        for index in range(count)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_estimate_scope_makes_no_network_calls(tmp_path: Path) -> None:
    """estimate-scope reads only local files: a transport that raises is never used."""
    path = _write_constituents(tmp_path / 'constituents.csv')
    config = _config()

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f'estimate-scope made a network call to {request.url}')

    # Guard the import path too: httpx is not invoked anywhere in the estimate.
    transport = httpx.MockTransport(explode)
    assert isinstance(transport, httpx.MockTransport)

    estimate = estimate_scope(config, constituents_path=path)
    assert estimate.companies == 3
    assert estimate.documents == 3 * estimate.quarters * len(estimate.document_types)
    assert estimate.input_tokens == estimate.documents * 6000
    assert estimate.output_tokens == estimate.documents * 800
    lines = '\n'.join(estimate.as_lines())
    assert 'ESTIMATE ONLY' in lines
    assert 'not a promise' in lines
    assert '$0.00' in lines


def test_estimate_scope_counts_quarters_in_window(tmp_path: Path) -> None:
    """A 3-year window yields 12 quarters and 3 docs per company-quarter."""
    path = _write_constituents(tmp_path / 'constituents.csv', count=2)
    config = _config(**{'universe.as_of_sample_freq': 'YS'})
    estimate = estimate_scope(config, constituents_path=path)
    assert estimate.quarters == 12
    assert estimate.documents == 2 * 12 * 1
    assert '8-K' in estimate.document_types


def test_estimate_scope_respects_membership_dates(tmp_path: Path) -> None:
    """A company that joined mid-window only counts for its own quarters."""
    rows = [
        {
            'ticker': 'EARLY',
            'cik': '0000000001',
            'effective_from': '2022-01-01',
            'effective_to': '',
            'company_name': 'Early Co',
        },
        {
            'ticker': 'LATE',
            'cik': '0000000002',
            'effective_from': '2024-07-01',
            'effective_to': '',
            'company_name': 'Late Co',
        },
    ]
    path = tmp_path / 'constituents.csv'
    pd.DataFrame(rows).to_csv(path, index=False)
    config = _config()
    estimate = estimate_scope(config, constituents_path=path)
    # The window is 12 quarters; LATE covers only Q3-Q4 2024.
    assert estimate.companies == 2
    assert estimate.quarters == 12
    assert estimate.documents == (12 + 2) * 1


def test_estimate_scope_missing_constituents_names_the_file(tmp_path: Path) -> None:
    """A missing constituents file fails with the path in the message."""
    missing = tmp_path / 'nope.csv'
    config = _config(**{'data.constituents_csv': str(missing)})
    with pytest.raises(DataError) as excinfo:
        estimate_scope(config)
    assert 'nope.csv' in str(excinfo.value)


def test_scope_reports_request_budget_and_configured_reply_ceiling(tmp_path: Path) -> None:
    path = _write_constituents(tmp_path / 'constituents.csv', count=2)
    config = load_config(
        REPO / 'configs/config.yaml',
        overrides={
            'data.start_date': '2025-01-01',
            'data.end_date': '2025-12-31',
            'llm.requests_per_day': '3',
        },
    )
    estimate = estimate_scope(config, constituents_path=path)
    lines = '\n'.join(estimate.as_lines())
    # Eight releases x two models; three attempts per request is the upper plan.
    assert 'base model requests       16' in lines
    assert 'maximum model requests    48' in lines
    assert 'UTC days at configured cap 6..16' in lines
    assert estimate.output_tokens >= estimate.documents * config.llm.max_tokens
    assert 'per model' in lines
