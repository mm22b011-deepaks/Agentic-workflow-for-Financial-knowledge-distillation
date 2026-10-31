"""Unit tests for the Wikipedia membership reconstruction."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.errors import DataError
from nowcast.ingestion.universe.wikipedia_source import (
    parse_changes_table,
    parse_current_table,
    reconstruct_membership,
)

FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures' / 'universe'


def _html(name: str) -> str:
    """Read a universe fixture file."""
    return (FIXTURES / name).read_text(encoding='utf-8')


def _membership() -> tuple[pd.DataFrame, list]:
    """Reconstruct membership from the two fixtures."""
    current = parse_current_table(_html('current_table.html'))
    changes = parse_changes_table(_html('changes_table.html'))
    return reconstruct_membership(current, changes)


def test_wikipedia_tables_located_by_column_name() -> None:
    """Tables are found by header names even after an unrelated table is prepended."""
    original = _html('current_table.html')
    header = original[original.index('<table') :]
    padded = (
        '<html><body><table><tr><th>Fruit</th><th>Quantity</th></tr>'
        '<tr><td>apple</td><td>3</td></tr></table>' + header + '</body></html>'
    )
    frame = parse_current_table(padded)
    assert set(frame['ticker']) == {'AAA', 'BBB', 'ZZZ'}


def test_wikipedia_missing_columns_raises_with_columns_found() -> None:
    """A table with wrong headers raises DataError naming the columns found."""
    bad = (
        '<html><body><table><tr><th>Fruit</th><th>Quantity</th></tr>'
        '<tr><td>apple</td><td>3</td></tr></table></body></html>'
    )
    with pytest.raises(DataError) as excinfo:
        parse_current_table(bad)
    message = str(excinfo.value)
    assert 'fruit' in message.lower()
    assert 'quantity' in message.lower()


def test_backward_walk_reconstructs_known_membership() -> None:
    """Undoing two swaps yields the exact original intervals."""
    frame, anomalies = _membership()
    rows = (
        frame.assign(
            effective_from=pd.to_datetime(frame['effective_from']).dt.date,
            effective_to=pd.to_datetime(frame['effective_to']).dt.date,
        )
        .sort_values(['ticker', 'effective_from'])
        .to_dict('records')
    )
    by_ticker: dict[str, list[tuple[object, object]]] = {}
    for row in rows:
        end = None if pd.isna(row['effective_to']) else row['effective_to']
        by_ticker.setdefault(row['ticker'], []).append((row['effective_from'], end))

    assert by_ticker['CCC'] == [
        (pd.Timestamp('2022-03-15').date(), pd.Timestamp('2023-09-01').date())
    ]
    assert by_ticker['DDD'] == [
        (pd.Timestamp('2021-06-01').date(), pd.Timestamp('2022-03-15').date())
    ]
    assert by_ticker['ZZZ'] == [(pd.Timestamp('2023-09-01').date(), None)]
    assert by_ticker['BBB'] == [(pd.Timestamp('2021-06-01').date(), None)]
    assert by_ticker['AAA'] == [
        (pd.Timestamp('2020-01-01').date(), pd.Timestamp('2023-06-01').date()),
        (pd.Timestamp('2023-06-01').date(), None),
    ]
    assert anomalies == []


def test_reused_ticker_different_company_not_merged() -> None:
    """A ticker that names two different companies keeps two separate intervals."""
    frame, _anomalies = _membership()
    aaa = frame[frame['ticker'] == 'AAA'].sort_values('effective_from')
    assert len(aaa) == 2
    assert set(aaa['company_name']) == {'Alpha Industries', 'Delta Aerospace'}
    pairs = list(zip(aaa['effective_from'], aaa['effective_to'], aaa['company_name'], strict=True))
    assert pairs[0][2] == 'Alpha Industries'
    assert pairs[1][2] == 'Delta Aerospace'
    # The two companies share a ticker and hand over on the same day, never merging.
    assert pairs[0][1] == pairs[1][0]


def test_event_anomalies_written_not_dropped() -> None:
    """An event that undoes a non-member is recorded as an anomaly, not dropped silently."""
    current = parse_current_table(_html('current_table.html'))
    changes = parse_changes_table(_html('changes_table.html'))
    broken = pd.concat(
        [
            changes,
            pd.DataFrame(
                [
                    {
                        'event_date': pd.Timestamp('2021-01-01').date(),
                        'added_ticker': 'QQQ',
                        'added_name': 'Not A Member',
                        'removed_ticker': '',
                        'removed_name': '',
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    _frame, anomalies = reconstruct_membership(current, broken)
    kinds = {anomaly.kind for anomaly in anomalies}
    assert 'remove_missing' in kinds
    assert any(anomaly.ticker == 'QQQ' for anomaly in anomalies)


def test_unparseable_date_recorded() -> None:
    """A change row with an unreadable date is reported, not dropped."""
    current = parse_current_table(_html('current_table.html'))
    changes = pd.DataFrame(
        [
            {
                'event_date': None,
                'added_ticker': 'NEW',
                'added_name': 'New Co',
                'removed_ticker': '',
                'removed_name': '',
            }
        ]
    )
    _frame, anomalies = reconstruct_membership(current, changes)
    assert any(anomaly.kind == 'unparseable_date' for anomaly in anomalies)
