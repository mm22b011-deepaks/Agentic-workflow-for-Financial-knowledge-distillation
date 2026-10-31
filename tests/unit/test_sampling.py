"""Tests for point-in-time universe sampling and filing selection."""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import Config, load_config
from nowcast.errors import DataError
from nowcast.ingestion.edgar import Disclosure
from nowcast.ingestion.sampling import (
    EXHIBIT_PRIORITY,
    exhibit_priority,
    sample_from_config,
    season_frame,
    season_sample,
    select_filings,
)

REPO = Path(__file__).resolve().parent.parent.parent


def _config(**overrides: object) -> Config:
    """Load the project config with a fixed window and the given overrides."""
    values: dict[str, object] = {
        'data.start_date': '2024-01-01',
        'data.end_date': '2024-12-31',
        'universe.subset_n': 0,
        'universe.subset_seed': 42,
    }
    values.update(overrides)
    return load_config(REPO / 'configs' / 'config.yaml', overrides=values)


def _constituents(count: int = 40, joined: str = '2023-01-01') -> pd.DataFrame:
    """Return `count` members, all active for the whole 2024 window."""
    return pd.DataFrame(
        [
            {
                'ticker': f'T{index:03d}',
                'cik': f'{index:010d}',
                'effective_from': pd.Timestamp(joined),
                'effective_to': pd.NaT,
            }
            for index in range(count)
        ]
    )


def _filing(accession: str, filed: str, exhibit: str = 'EX-99.1') -> Disclosure:
    """Build one exhibit of one filing."""
    return Disclosure(
        cik='0000000001',
        accession=accession,
        filing_date=datetime.date.fromisoformat(filed),
        form='8-K',
        exhibit_type=exhibit,
        document=f'{accession}-{exhibit}.htm',
    )


def test_sample_spreads_across_ciks_not_lowest_first() -> None:
    """A seeded sample is not the alphabetically first companies."""
    frame = _constituents(40)
    sample = season_sample(_config(**{'universe.subset_n': 5}), frame)
    lowest = tuple(f'{index:010d}' for index in range(5))
    assert len(sample.ciks) > 0
    assert sample.ciks != lowest
    # And it is a real subset of members, not an artefact of generation.
    assert set(sample.ciks).issubset(set(frame['cik']))


def test_sample_deterministic_for_seed() -> None:
    """The same seed and window reproduce the same sample exactly."""
    frame = _constituents(40)
    config = _config(**{'universe.subset_n': 7})
    assert season_sample(config, frame).ciks == season_sample(config, frame).ciks
    other = _config(**{'universe.subset_n': 7, 'universe.subset_seed': 7})
    assert season_sample(other, frame).ciks != season_sample(config, frame).ciks


def test_one_release_per_filing_by_priority() -> None:
    """A filing with a release and a supplement contributes its release only."""
    items = [
        _filing('a-1', '2024-01-30', 'EX-99.2'),
        _filing('a-1', '2024-01-30', 'EX-99.1'),
        _filing('a-2', '2024-04-30', 'EX-99.1'),
    ]
    kept, skips = select_filings(items)
    assert [item.exhibit_type for item in kept] == ['EX-99.1', 'EX-99.1']
    assert {item.accession for item in kept} == {'a-1', 'a-2'}
    assert skips['duplicate_exhibit'] == 1
    # The kept exhibit of accession a-1 is the priority one, not the first seen.
    assert next(item for item in kept if item.accession == 'a-1').exhibit_type == 'EX-99.1'


def test_priority_order_is_explicit() -> None:
    """EX-99.1 outranks an unsuffixed EX-99, which outranks a supplement."""
    assert exhibit_priority('EX-99.1') < exhibit_priority('EX-99') < exhibit_priority('EX-99.2')
    # An unknown type still sorts deterministically, after every known one.
    assert exhibit_priority('EX-10') > exhibit_priority(EXHIBIT_PRIORITY[-1])


def test_seasons_covered_per_company() -> None:
    """Four quarterly filings yield four documents, one per season, newest first."""
    items = [
        _filing('q1', '2024-01-25'),
        _filing('q2', '2024-04-25'),
        _filing('q3', '2024-07-25'),
        _filing('q4', '2024-10-25'),
    ]
    kept, skips = select_filings(items)
    assert [item.accession for item in kept] == ['q4', 'q3', 'q2', 'q1']
    assert skips == {}


def test_two_filings_in_one_season_keep_one() -> None:
    """A later 8-K in the same quarter does not give that season two documents."""
    items = [
        _filing('first', '2024-04-25'),
        _filing('later', '2024-05-30'),
        _filing('prior', '2024-01-25'),
    ]
    kept, skips = select_filings(items)
    # Newest first, so the later filing of the season is the one kept; either way the
    # season contributes one document, which is the property that matters.
    assert [item.accession for item in kept] == ['later', 'prior']
    assert skips == {'duplicate_season': 1}


def test_only_members_active_in_window(tmp_path: Path) -> None:
    """A company that left before the window is not sampled."""
    rows = [
        {
            'ticker': 'OLD',
            'cik': '0000000001',
            'effective_from': '2020-01-01',
            'effective_to': '2021-01-01',
        },
        {
            'ticker': 'NEW',
            'cik': '0000000002',
            'effective_from': '2024-01-01',
            'effective_to': '',
        },
    ]
    path = tmp_path / 'constituents.csv'
    pd.DataFrame(rows).to_csv(path, index=False)
    config = _config(**{'data.constituents_csv': str(path)})
    sample = sample_from_config(config)
    assert sample.ciks == ('0000000002',)


def test_member_joining_mid_window_is_sampled_from_its_first_season(tmp_path: Path) -> None:
    """Membership is tested per season, so a mid-year joiner is not credited to Q1."""
    path = tmp_path / 'constituents.csv'
    pd.DataFrame(
        [
            {
                'ticker': 'LATE',
                'cik': '0000000003',
                'effective_from': '2024-07-01',
                'effective_to': '',
            }
        ]
    ).to_csv(path, index=False)
    config = _config(**{'data.constituents_csv': str(path)})
    frame = pd.read_csv(path, dtype={'cik': str})
    quarters = dict(season_frame(config))
    sample = season_sample(config, frame)
    # Still selected — it is a member for Q3 and Q4 — but the sample records that Q1
    # and Q2 had no members rather than inventing one.
    assert sample.ciks == ('0000000003',)
    assert 'no_members:2024Q1' in sample.skipped
    assert 'no_members:2024Q2' in sample.skipped
    assert 'no_members:2024Q3' not in sample.skipped
    assert quarters['2024Q3'] == pd.Timestamp('2024-07-01')


def test_cap_is_seeded_not_a_sorted_tail() -> None:
    """Capping the walk drops companies in seeded order, not the highest CIKs."""
    frame = _constituents(40)
    config = _config()
    sample = season_sample(config, frame, limit=10)
    everything = sorted(str(value) for value in frame['cik'])
    assert len(sample.ciks) == 10
    assert sample.skipped['left_out_by_cap'] == 30
    assert sample.ciks != tuple(everything[:10])
    # The cap does not introduce non-determinism.
    assert season_sample(config, frame, limit=10).ciks == sample.ciks


def test_walk_order_is_not_the_sorted_cik_list() -> None:
    """The full sample keeps every member, but visiting order is seeded, not sorted."""
    frame = _constituents(40)
    sample = season_sample(_config(), frame)
    sorted_ciks = tuple(f'{index:010d}' for index in range(40))
    assert sorted(sample.ciks) == list(sorted_ciks)
    assert sample.ciks != sorted_ciks


def test_each_member_appears_once_across_seasons() -> None:
    """A member active in all four seasons is walked once, not four times."""
    sample = season_sample(_config(), _constituents(5))
    assert len(sample.ciks) == len(set(sample.ciks)) == 5


def test_window_is_required() -> None:
    """Sampling by season refuses to guess a window from the wall clock."""
    with pytest.raises(DataError, match='start_date'):
        season_frame(_config(**{'data.start_date': '', 'data.end_date': ''}))


def test_sample_serialises_for_the_manifest() -> None:
    """The sample records companies, seed and seasons so the manifest can state them."""
    config = _config(**{'universe.subset_n': 3, 'universe.subset_seed': 11})
    sample = season_sample(config, _constituents(10))
    payload = sample.as_dict()
    assert payload['companies'] == len(sample.ciks)
    assert payload['seed'] == 11
    assert payload['seasons'] == ['2024Q1', '2024Q2', '2024Q3', '2024Q4']
    assert isinstance(payload['skipped'], dict)
