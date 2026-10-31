"""Unit tests for universe validation: member counts, coverage and overlaps."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import Config, load_config
from nowcast.errors import DataError
from nowcast.ingestion.universe.cik_mapper import UNRESOLVED
from nowcast.ingestion.universe.validate import (
    check_coverage,
    check_overlaps,
    cik_coverage,
    member_count_audit,
)

REPO = Path(__file__).resolve().parent.parent.parent


def _config(**overrides: object) -> Config:
    """Load the project config with universe/date overrides applied."""
    values = {
        'data.start_date': '2020-01-01',
        'data.end_date': '2024-12-31',
        'universe.as_of_sample_freq': 'YS',
        'universe.expected_members': 10,
        'universe.member_count_tolerance': 2,
    }
    values.update(overrides)
    return load_config(REPO / 'configs' / 'config.yaml', overrides=values)


def _intervals(count: int, cik: str | None = '0000320193') -> pd.DataFrame:
    """Build `count` distinct members that are active for the whole window."""
    return pd.DataFrame(
        {
            'ticker': [f'T{index:03d}' for index in range(count)],
            'company_name': [f'Company {index}' for index in range(count)],
            'effective_from': pd.Timestamp('2019-01-01'),
            'effective_to': pd.NaT,
            'cik': UNRESOLVED if cik is None else cik,
            'cik_source': UNRESOLVED if cik is None else 'sec_map',
        }
    )


def test_member_count_audit_flags_out_of_tolerance() -> None:
    """Dates whose member count is outside the tolerance band are flagged."""
    config = _config()
    audit = member_count_audit(_intervals(10), config)
    assert not audit['flagged'].any()
    assert set(audit['member_count']) == {10}

    too_few = member_count_audit(_intervals(5), config)
    assert too_few['flagged'].all()
    assert set(too_few['member_count']) == {5}
    assert (too_few['expected'] == 10).all()
    assert (too_few['tolerance'] == 2).all()

    # 8 members is exactly at the edge of 10 +/- 2 and must not be flagged.
    edge = member_count_audit(_intervals(8), config)
    assert not edge['flagged'].any()


def test_member_count_audit_uses_configured_frequency() -> None:
    """The audit samples yearly when as_of_sample_freq is YS."""
    config = _config()
    audit = member_count_audit(_intervals(10), config)
    dates = pd.to_datetime(audit['date'])
    assert len(audit) == 5
    assert list(dates.dt.year) == [2020, 2021, 2022, 2023, 2024]


def test_cik_coverage_below_threshold_fails_build(tmp_path: Path) -> None:
    """Coverage under min_cik_coverage raises and says where the unmapped file is."""
    config = _config(**{'universe.min_cik_coverage': 0.98})
    unmapped_path = tmp_path / 'unmapped.csv'
    with pytest.raises(DataError) as excinfo:
        check_coverage(_intervals(10, cik=None), config, str(unmapped_path), 10)
    message = str(excinfo.value)
    assert '0.000' in message
    assert '0.980' in message
    assert '10 tickers are unmapped' in message
    assert 'unmapped.csv' in message

    full = _intervals(10)
    assert check_coverage(full, config, str(unmapped_path), 0) == 1.0


def test_cik_coverage_is_membership_day_weighted() -> None:
    """Coverage weights by active membership-days, not by row count."""
    config = _config(**{'universe.min_cik_coverage': 0.5})
    frame = _intervals(4)
    frame.loc[0, 'cik'] = UNRESOLVED
    # One of four rows unresolved -> 0.75 coverage.
    assert cik_coverage(frame, config) == pytest.approx(0.75)

    short = pd.DataFrame(
        {
            'ticker': ['A', 'B'],
            'company_name': ['A Inc', 'B Inc'],
            # A spans the whole window; B only the last two quarters of 2024.
            'effective_from': [pd.Timestamp('2018-01-01'), pd.Timestamp('2024-06-01')],
            'effective_to': [pd.Timestamp('2024-12-31'), pd.NaT],
            'cik': ['0000000001', UNRESOLVED],
        }
    )
    quarterly = _config(**{'universe.as_of_sample_freq': 'QS'})
    # 20 sampled quarters for A plus 2 for B: one unresolved row but only 2 of 22
    # membership-days missing, so row counts would understate coverage badly.
    coverage = cik_coverage(short, quarterly)
    assert coverage == pytest.approx(20 / 22)
    assert coverage > 0.9


def test_overlap_same_company_fails_build() -> None:
    """Two overlapping intervals for the same company are a fatal build error."""
    frame = pd.DataFrame(
        {
            'ticker': ['AAA', 'AAA'],
            'company_name': ['Alpha Industries', 'Alpha Industries'],
            'effective_from': [pd.Timestamp('2020-01-01'), pd.Timestamp('2022-01-01')],
            'effective_to': [pd.Timestamp('2023-01-01'), None],
        }
    )
    with pytest.raises(DataError) as excinfo:
        check_overlaps(frame)
    assert 'AAA' in str(excinfo.value)
    assert 'same company' in str(excinfo.value)


def test_overlap_different_company_is_an_anomaly_not_fatal() -> None:
    """Ticker reuse by two companies produces an anomaly, not a failure."""
    frame = pd.DataFrame(
        {
            'ticker': ['AAA', 'AAA'],
            'company_name': ['Alpha Industries', 'Delta Aerospace'],
            'effective_from': [pd.Timestamp('2020-01-01'), pd.Timestamp('2022-01-01')],
            'effective_to': [pd.Timestamp('2023-01-01'), None],
        }
    )
    written, anomalies = check_overlaps(frame)
    assert len(anomalies) == 1
    assert anomalies[0]['kind'] == 'overlap_different_company'
    assert not written.empty


def test_invalid_interval_recorded_as_anomaly() -> None:
    """An interval ending before it starts is reported, not silently kept."""
    frame = pd.DataFrame(
        {
            'ticker': ['AAA'],
            'company_name': ['Alpha Industries'],
            'effective_from': [pd.Timestamp('2023-01-01')],
            'effective_to': [pd.Timestamp('2020-01-01')],
        }
    )
    _written, anomalies = check_overlaps(frame)
    assert any(item['kind'] == 'invalid_interval' for item in anomalies)


def test_member_count_audit_counts_open_ended_members() -> None:
    """Current members (blank effective_to) are counted, never dropped as NaT."""
    config = _config()
    audit = member_count_audit(_intervals(10), config)
    assert set(audit['member_count']) == {10}
    assert not audit['flagged'].any()

    # If NaT members were excluded the count would be zero on every sampled date.
    assert int(audit['member_count'].min()) > 0
