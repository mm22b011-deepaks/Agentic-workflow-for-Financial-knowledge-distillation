"""Unit tests for the historical snapshot universe source."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import load_config
from nowcast.errors import DataError
from nowcast.ingestion.universe.historical_csv_source import (
    load_source,
    snapshots_to_intervals,
)

FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures' / 'universe'


def _snapshots() -> pd.DataFrame:
    """Read the historical snapshot fixture."""
    return pd.read_csv(FIXTURES / 'historical.csv')


def _by_ticker(frame: pd.DataFrame) -> dict[str, list[tuple[object, object]]]:
    """Group a membership frame into per-ticker (start, end) pairs, dates as dates."""
    grouped: dict[str, list[tuple[object, object]]] = {}
    for record in frame.sort_values(['ticker', 'effective_from']).to_dict('records'):
        end = (
            None if pd.isna(record['effective_to']) else pd.Timestamp(record['effective_to']).date()
        )
        grouped.setdefault(str(record['ticker']), []).append(
            (pd.Timestamp(record['effective_from']).date(), end)
        )
    return grouped


def _day(text: str) -> object:
    """Parse a fixture date string into a date."""
    return pd.Timestamp(text).date()


def test_historical_snapshots_to_intervals() -> None:
    """A ticker's interval opens at its first snapshot and closes after its last."""
    frame = snapshots_to_intervals(_snapshots())
    pairs = _by_ticker(frame)
    # CCC joins at 2022-07-01, is still present at 2023-01-01, and is gone by
    # 2023-07-01, so it gets one interval bounded by the first snapshot it misses.
    assert pairs['CCC'] == [(_day('2022-07-01'), _day('2023-07-01'))]
    # AAA is present in every snapshot, so it stays open.
    assert pairs['AAA'] == [(_day('2022-01-01'), None)]
    # BBB leaves at 2023-01-01 and rejoins at 2023-07-01: two intervals, never one
    # interval spanning the absence.
    assert pairs['BBB'] == [
        (_day('2022-01-01'), _day('2023-01-01')),
        (_day('2023-07-01'), None),
    ]
    assert list(frame.columns) == [
        'ticker',
        'company_name',
        'effective_from',
        'effective_to',
        'cik_hint',
    ]


def test_historical_bad_format_message() -> None:
    """An unparseable date column fails with a message naming the expected format."""
    broken = pd.DataFrame({'as_of': ['not-a-date', '2022-07-01'], 'AAA': [1, 1]})
    with pytest.raises(DataError) as excinfo:
        snapshots_to_intervals(broken)
    message = str(excinfo.value)
    assert 'as_of' in message
    assert 'date' in message.lower()


def test_historical_members_column_accepted() -> None:
    """The alternative 'date, members' layout is split into one row per ticker."""
    snapshots = pd.DataFrame(
        {
            'date': ['2022-01-01', '2022-07-01'],
            'members': ['AAA, BBB', 'AAA'],
        }
    )
    frame = snapshots_to_intervals(snapshots)
    assert set(frame['ticker']) == {'AAA', 'BBB'}
    bbb = frame[frame['ticker'] == 'BBB'].iloc[0]
    assert pd.Timestamp(bbb['effective_from']).date() == pd.Timestamp('2022-01-01').date()
    assert pd.Timestamp(bbb['effective_to']).date() == pd.Timestamp('2022-07-01').date()


def test_historical_load_source_hashes_local_file(tmp_path: Path) -> None:
    """Loading a local file records its hash and path in the provenance."""
    config = load_config(
        Path(__file__).resolve().parent.parent.parent / 'configs' / 'config.yaml',
        overrides={
            'universe.source': 'historical_csv',
            'universe.historical_csv_path_or_url': str(FIXTURES / 'historical.csv'),
        },
    )
    source = load_source(config, tmp_path)
    assert source.provenance['historical_path'].endswith('historical.csv')
    assert len(str(source.provenance['historical_sha256'])) == 64
    assert not source.frame.empty
