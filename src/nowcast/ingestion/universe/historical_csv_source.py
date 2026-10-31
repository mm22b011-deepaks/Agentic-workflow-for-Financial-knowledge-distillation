"""Membership intervals built from dated member snapshots supplied by the user."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from nowcast.config import Config
from nowcast.errors import DataError
from nowcast.ingestion.universe.base import (
    MembershipSource,
    empty_membership,
    fetch_bytes,
    normalise_ticker,
    to_date,
    user_agent,
)

SNAPSHOT_COLUMNS_HINT = (
    "date plus one column per ticker, or 'date, members' where members is a space/comma list"
)


def _read_source(config: Config, cache_root: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load the historical snapshot file from disk or over HTTP."""
    settings = config.universe
    location = settings.historical_csv_path_or_url
    if not location:
        raise DataError(
            'universe.historical_csv_path_or_url must be set when source is historical_csv'
        )
    if location.startswith(('http://', 'https://')):
        fetched = fetch_bytes(location, cache_root, user_agent(config), settings.refresh)
        frame = pd.read_csv(fetched.cache_path)
        return frame, {'historical_url': location, 'historical_sha256': fetched.sha256}
    path = Path(location)
    if not path.is_file():
        raise DataError(f'historical CSV not found: {path}')
    import hashlib

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pd.read_csv(path), {'historical_path': str(path), 'historical_sha256': digest}


FALSE_TEXT = {'0', '0.0', 'false', 'no', 'n', 'out', '', 'nan', 'none'}


def _is_present(value: object) -> bool:
    """Decide whether a snapshot cell marks the ticker as a member on that date."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return not pd.isna(value) and float(value) != 0.0
    return str(value).strip().lower() not in FALSE_TEXT


def snapshots_to_intervals(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Convert dated member snapshots into open/closed membership intervals."""
    if snapshots.empty:
        return empty_membership()
    frame = snapshots.copy()
    first = frame.columns[0]
    frame[first] = frame[first].map(to_date)
    if frame[first].isna().any():
        raise DataError(
            f'historical CSV has unparseable dates in column {first!r}; expected {SNAPSHOT_COLUMNS_HINT}'
        )
    if 'members' in {str(column).lower() for column in frame.columns}:
        members_column = next(c for c in frame.columns if str(c).lower() == 'members')
        rows: list[tuple[object, str]] = []
        for record in frame.to_dict('records'):
            raw = str(record[members_column])
            for token in raw.replace(';', ',').split(','):
                for ticker in token.split():
                    if ticker.strip():
                        rows.append((record[first], normalise_ticker(ticker)))
        long = pd.DataFrame(rows, columns=['date', 'ticker'])
    else:
        melted = frame.melt(id_vars=[first], var_name='ticker', value_name='present')
        present = melted['present'].map(_is_present)
        melted = melted[present]
        long = pd.DataFrame(
            {
                'date': melted[first].map(to_date),
                'ticker': melted['ticker'].map(normalise_ticker),
            }
        )
    if long.empty:
        return empty_membership()

    if long['ticker'].eq('').any():
        raise DataError(
            'historical CSV has blank ticker headers or empty ticker values; '
            f'expected {SNAPSHOT_COLUMNS_HINT}'
        )
    all_dates: list[date] = sorted(
        {item for item in long['date'].tolist() if isinstance(item, date)}
    )
    intervals: list[dict[str, object]] = []
    for ticker, group in long.groupby('ticker', sort=True):
        present = {item for item in group['date'].tolist() if isinstance(item, date)}
        if not present:
            continue
        present_set = set(present)
        # Consecutive snapshots where the ticker is present form one interval; a ticker
        # that leaves and later rejoins gets separate intervals, not one spanning the gap.
        run_start: date | None = None
        for day in all_dates:
            if day in present_set:
                if run_start is None:
                    run_start = day
            elif run_start is not None:
                intervals.append(
                    {
                        'ticker': ticker,
                        'company_name': '',
                        'effective_from': pd.Timestamp(run_start),
                        'effective_to': pd.Timestamp(day),
                        'cik_hint': None,
                    }
                )
                run_start = None
        if run_start is not None:
            intervals.append(
                {
                    'ticker': ticker,
                    'company_name': '',
                    'effective_from': pd.Timestamp(run_start),
                    'effective_to': None,
                    'cik_hint': None,
                }
            )
    return (
        pd.DataFrame(
            intervals,
            columns=['ticker', 'company_name', 'effective_from', 'effective_to', 'cik_hint'],
        )
        .sort_values(['ticker', 'effective_from'])
        .reset_index(drop=True)
    )


def load_source(config: Config, cache_root: Path) -> MembershipSource:
    """Load the historical CSV and convert snapshots to intervals."""
    snapshots, provenance = _read_source(config, cache_root)
    missing = [c for c in snapshots.columns if not str(c).strip()]
    if missing:
        raise DataError(
            f'historical CSV has blank column headers; expected {SNAPSHOT_COLUMNS_HINT}'
        )
    frame = snapshots_to_intervals(snapshots)
    return MembershipSource(frame=frame, anomalies=[], provenance=provenance)
