"""Validity, coverage and member-count checks for a universe build."""

from __future__ import annotations

import pandas as pd

from nowcast.config import Config
from nowcast.errors import DataError
from nowcast.ingestion.universe.cik_mapper import UNRESOLVED


def _active_on(intervals: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """Return intervals active on a date."""
    start = pd.to_datetime(intervals['effective_from'])
    end = pd.to_datetime(intervals['effective_to']).fillna(pd.Timestamp('2100-01-01'))
    mask = (start <= day) & (end >= day)
    return intervals[mask]


def member_count_audit(intervals: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Sample dates across the configured window and count active members."""
    start = (
        pd.Timestamp(config.data.start_date)
        if config.data.start_date
        else pd.Timestamp('2010-01-01')
    )
    end = pd.Timestamp(config.data.end_date) if config.data.end_date else pd.Timestamp.today()
    freq = config.universe.as_of_sample_freq
    dates = pd.date_range(start=start, end=end, freq=freq)
    expected = int(config.universe.expected_members)
    tolerance = int(config.universe.member_count_tolerance)
    rows: list[dict[str, object]] = []
    for day in dates:
        count = len(_active_on(intervals, day))
        rows.append(
            {
                'date': day.date().isoformat(),
                'member_count': count,
                'expected': expected,
                'tolerance': tolerance,
                'flagged': abs(count - expected) > tolerance,
            }
        )
    return pd.DataFrame(rows)


def cik_coverage(intervals: pd.DataFrame, config: Config) -> float:
    """Return the share of active membership-days whose CIK resolved."""
    if intervals.empty:
        return 0.0
    start = (
        pd.Timestamp(config.data.start_date)
        if config.data.start_date
        else pd.Timestamp('2010-01-01')
    )
    end = pd.Timestamp(config.data.end_date) if config.data.end_date else pd.Timestamp.today()
    dates = pd.date_range(start=start, end=end, freq=config.universe.as_of_sample_freq)
    if len(dates) == 0:
        return 0.0
    total = 0
    resolved = 0
    for day in dates:
        active = _active_on(intervals, day)
        total += len(active)
        resolved += int((active['cik'] != UNRESOLVED).sum())
    return resolved / total if total else 0.0


def check_coverage(
    intervals: pd.DataFrame, config: Config, unmapped_path: str, unmapped_count: int
) -> float:
    """Fail the build when CIK coverage is below the configured threshold."""
    coverage = cik_coverage(intervals, config)
    threshold = float(config.universe.min_cik_coverage)
    if coverage < threshold:
        raise DataError(
            f'CIK coverage {coverage:.3f} is below the required {threshold:.3f}; '
            f'{unmapped_count} tickers are unmapped. See {unmapped_path} and add overrides '
            'to universe.cik_overrides_csv.'
        )
    return coverage


def check_overlaps(intervals: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Detect overlaps; same-company overlaps are fatal, different companies are anomalies."""
    anomalies: list[dict[str, str]] = []
    fatal: list[dict[str, str]] = []
    if intervals.empty:
        return pd.DataFrame(), anomalies
    for ticker, group in intervals.groupby('ticker'):
        ordered = group.sort_values('effective_from')
        previous_end: pd.Timestamp | None = None
        previous_name = ''
        for record in ordered.to_dict('records'):
            start = pd.Timestamp(record['effective_from'])
            end = (
                pd.Timestamp(record['effective_to'])
                if record.get('effective_to') is not None
                and not pd.isna(record.get('effective_to'))
                else None
            )
            if end is not None and end < start:
                anomalies.append(
                    {
                        'kind': 'invalid_interval',
                        'ticker': str(ticker),
                        'company_name': str(record.get('company_name', '')),
                        'detail': f'effective_to {end.date()} before effective_from {start.date()}',
                    }
                )
            if previous_end is not None and start < previous_end:
                same_company = str(record.get('company_name', '')) == previous_name
                entry = {
                    'kind': 'overlap_same_company' if same_company else 'overlap_different_company',
                    'ticker': str(ticker),
                    'company_name': str(record.get('company_name', '')),
                    'detail': f'starts {start.date()} before previous end {previous_end.date()}',
                }
                (fatal if same_company else anomalies).append(entry)
            previous_end = end if end is not None else pd.Timestamp('2100-01-01')
            previous_name = str(record.get('company_name', ''))
    if fatal:
        raise DataError(
            'overlapping intervals for the same company: '
            + '; '.join(f'{item["ticker"]} ({item["detail"]})' for item in fatal[:5])
        )
    return pd.DataFrame(anomalies), anomalies
