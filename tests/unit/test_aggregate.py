"""Tests for index-level aggregation and the privacy guardrail."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nowcast.aggregation.aggregate import (
    aggregate_index,
    assert_index_level_only,
    per_document_metrics,
    season_of,
    winsorize,
)
from nowcast.config import Config, load_config
from nowcast.errors import DataError

REPO = Path(__file__).resolve().parent.parent.parent


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Config:
    """Config bound to a temp data root with one theme and a small guardrail."""
    data = tmp_path / 'data'
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('DATA_DIR', str(data))
    values: dict[str, object] = {
        'data.start_date': '2025-01-01',
        'data.end_date': '2025-12-31',
        'extraction.themes': 'demand',
        'extraction.review_queue_path': 'extractions/review_queue.parquet',
        'aggregation.min_constituents': 2,
        'aggregation.winsorize_pct': 0.05,
        # These tests are about the company guardrail, not the observation guardrail;
        # the observation minimum has its own tests.
        'aggregation.min_observations': 1,
    }
    values.update(overrides)
    return load_config(REPO / 'configs' / 'config.yaml', overrides=values)


def _constituents(tmp_path: Path, count: int = 4) -> Path:
    """Write a constituents file with `count` members active all year."""
    path = tmp_path / 'constituents.csv'
    rows = [
        {
            'ticker': f'T{index:02d}',
            'cik': f'{index + 1:010d}',
            'effective_from': '2024-01-01',
            'effective_to': '',
        }
        for index in range(count)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _extractions(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Build an extraction frame with the columns the aggregator reads."""
    defaults: dict[str, object] = {
        'eps_basis': 'gaap',
        'guidance_direction': None,
        'tone': 'neutral',
        'theme_demand_direction': None,
        'model': 'fake/model:free',
        # consolidate writes this; dedupe keying on a column that does not exist is
        # exactly the defect F5 describes.
        'record_confidence': 0.9,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _compass(**overrides: object) -> dict[str, object]:
    """Return one extraction row with sensible defaults."""
    row: dict[str, object] = {
        'document_id': 'doc-1',
        'cik': '0000000001',
        'report_date': '2025-04-20',
        'reported_eps': 1.0,
        'consensus_eps': 1.0,
        'prior_year_eps': 0.5,
        'guidance_direction': 'raised',
    }
    row.update(overrides)
    return row


def test_beat_tolerance_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A surprise inside the tolerance is inline; outside it is a beat or miss."""
    config = _config(tmp_path, monkeypatch, **{'extraction.eps_tolerance_abs': 0.05})
    tolerance = 0.05
    rows = [
        _compass(document_id='a', reported_eps=1.0 + tolerance),  # exactly at the edge
        _compass(document_id='b', reported_eps=1.0 + tolerance + 0.01),  # just above
        _compass(document_id='c', reported_eps=1.0 - tolerance),  # edge, negative side
        _compass(document_id='d', reported_eps=1.0 - tolerance - 0.01),  # just below
    ]
    metrics = per_document_metrics(config, _extractions(rows))
    beats = metrics.frame.set_index('document_id')['beat']
    assert beats['a'] == 0.0
    assert beats['b'] == 1.0
    assert beats['c'] == 0.0
    assert beats['d'] == -1.0


def test_surprise_requires_known_basis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a recorded basis the surprise is NaN rather than a guessed comparison."""
    config = _config(tmp_path, monkeypatch)
    rows = [
        _compass(document_id='known', eps_basis='gaap', reported_eps=1.2),
        _compass(document_id='unknown', eps_basis=None, reported_eps=1.2),
    ]
    metrics = per_document_metrics(config, _extractions(rows))
    frame = metrics.frame.set_index('document_id')
    assert frame.loc['known', 'surprise'] == pytest.approx(0.2)
    assert pd.isna(frame.loc['unknown', 'surprise'])
    assert pd.isna(frame.loc['unknown', 'beat'])


def test_eps_growth_zero_prior_is_nan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero prior year figure makes growth undefined, never infinite."""
    config = _config(tmp_path, monkeypatch)
    rows = [
        _compass(document_id='zero', prior_year_eps=0.0),
        _compass(document_id='missing', prior_year_eps=None),
        _compass(document_id='fine', prior_year_eps=0.5),
    ]
    metrics = per_document_metrics(config, _extractions(rows))
    growth = metrics.frame.set_index('document_id')['eps_growth']
    assert pd.isna(growth['zero'])
    assert pd.isna(growth['missing'])
    assert growth['fine'] == pytest.approx(1.0)


def test_winsorize_applied() -> None:
    """Both tails are clipped at the requested proportion."""
    values = pd.Series([-100.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0])
    clipped = winsorize(values, 0.1)
    assert clipped.max() < 100.0
    assert clipped.min() > -100.0
    # A proportion of zero leaves the values untouched.
    assert winsorize(values, 0.0).equals(values)


def test_suppressed_below_min_constituents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Too few companies blanks every metric and flags the row as suppressed."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 3})
    constituents = _constituents(tmp_path)
    rows = [
        _compass(document_id='a', cik='0000000001'),
        _compass(document_id='b', cik='0000000002'),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert len(frame) == 1
    assert bool(frame.loc[0, 'suppressed']) is True
    assert frame.loc[0, 'n_reported'] == 2
    for column in (
        'beat_rate',
        'eps_growth_agg',
        'guidance_raise_share',
        'guidance_lower_share',
        'guidance_ratio',
        'tone_score_mean',
        'theme_demand_share',
    ):
        assert pd.isna(frame.loc[0, column]), column
    # Counts are not metrics, so they survive the guardrail.
    assert frame.loc[0, 'n_expected'] == 4


def test_share_reported_nondecreasing_within_season(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Within a season the reported share can only grow as more companies report."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path)
    rows = [
        _compass(document_id=f'doc-{index}', cik=f'{index + 1:010d}', report_date=date)
        for index, date in zip(
            range(4),
            ('2025-04-10', '2025-04-15', '2025-04-20', '2025-04-25'),
            strict=True,
        )
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    shares = frame['share_reported'].tolist()
    assert shares == sorted(shares)
    assert frame['n_reported'].tolist() == [1, 2, 3, 4]
    assert shares[-1] == pytest.approx(1.0)


def test_guidance_ratio_denominator_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No raised and no lowered guidance gives NaN, not a division error."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path)
    rows = [
        _compass(document_id='a', guidance_direction='maintained'),
        _compass(document_id='b', guidance_direction=None),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert pd.isna(frame.loc[0, 'guidance_ratio'])
    assert frame.loc[0, 'guidance_raise_share'] == pytest.approx(0.0)


def test_guidance_ratio_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """guidance_ratio is raised / (raised + lowered)."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path)
    rows = [
        _compass(document_id='a', cik='0000000001', guidance_direction='raised'),
        _compass(document_id='b', cik='0000000002', guidance_direction='raised'),
        _compass(document_id='c', cik='0000000003', guidance_direction='lowered'),
        _compass(document_id='d', cik='0000000004', guidance_direction='lowered'),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'guidance_ratio'] == pytest.approx(0.5)


def test_assert_index_level_only_catches_ticker_in_cell(tmp_path: Path) -> None:
    """A ticker hidden in a cell value fails the guardrail even with clean column names."""
    constituents = pd.read_csv(_constituents(tmp_path), dtype={'cik': str})
    leaky = pd.DataFrame({'as_of_date': ['2025-04-20'], 'note': ['T01']})
    with pytest.raises(DataError, match='constituent identifier'):
        assert_index_level_only(leaky, constituents)

    cik_leak = pd.DataFrame({'as_of_date': ['2025-04-20'], 'note': ['0000000002']})
    with pytest.raises(DataError, match='constituent identifier'):
        assert_index_level_only(cik_leak, constituents)

    forbidden = pd.DataFrame({'ticker': ['AAA'], 'beat_rate': [0.5]})
    with pytest.raises(DataError, match='forbidden column'):
        assert_index_level_only(forbidden)


def test_assert_index_level_only_passes_clean_frames(tmp_path: Path) -> None:
    """A numeric index-level frame passes."""
    constituents = pd.read_csv(_constituents(tmp_path), dtype={'cik': str})
    clean = pd.DataFrame({'as_of_date': ['2025-04-20'], 'beat_rate': [0.5], 'n_reported': [3]})
    assert_index_level_only(clean, constituents)


def test_review_queue_documents_are_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documents flagged for review never enter a metric."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path)
    queue_path = tmp_path / 'data' / 'extractions' / 'review_queue.parquet'
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                'document_id': 'bad',
                'field': 'reported_eps',
                'reason': 'low_confidence',
                'model': 'fake/model:free',
            }
        ]
    ).to_parquet(queue_path, index=False)

    rows = [
        _compass(document_id='bad', cik='0000000001', reported_eps=100.0),
        _compass(document_id='good', cik='0000000002', reported_eps=1.0),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'n_reported'] == 1
    assert frame.loc[0, 'n_review_excluded'] == 1
    # The 100.0 outlier would have wrecked beat_rate had it been counted.
    assert frame.loc[0, 'beat_rate'] == pytest.approx(0.0)


def test_two_models_do_not_double_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One company reporting once through two models is still one reported company."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path)
    rows = [
        _compass(document_id='doc-model-a', cik='0000000001', record_confidence=0.6),
        _compass(document_id='doc-model-b', cik='0000000001', record_confidence=0.9),
        _compass(document_id='doc-other', cik='0000000002'),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'n_reported'] == 2
    assert frame.loc[0, 'share_reported'] == pytest.approx(0.5)


def test_two_exhibits_same_filing_count_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two exhibits from one filing describe one quarter of one company."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path)
    rows = [
        _compass(document_id='exhibit-99-1', cik='0000000001', reported_eps=1.0),
        _compass(
            document_id='exhibit-99-2', cik='0000000001', reported_eps=1.0, record_confidence=0.9
        ),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'n_reported'] == 1
    assert frame.loc[0, 'share_reported'] == pytest.approx(0.25)


def test_duplicate_rows_do_not_weight_one_company_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Collapsing is not just counting distinct CIKs: the duplicate row leaves the metrics.

    Counting distinct CIKs alone would still average the duplicate's EPS growth into the
    index, letting one company pull the aggregate toward itself by reporting twice.
    """
    # Winsorising is off here: with three observations a 200% growth is clipped by the
    # as-of clip, which is the correct behaviour but would mask what this test measures.
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.min_constituents': 2, 'aggregation.winsorize_pct': 0.0},
    )
    constituents = _constituents(tmp_path)
    rows = [
        _compass(
            document_id='a1',
            cik='0000000001',
            prior_year_eps=1.0,
            reported_eps=3.0,
            record_confidence=0.9,
        ),
        _compass(
            document_id='a2',
            cik='0000000001',
            prior_year_eps=1.0,
            reported_eps=3.0,
            record_confidence=0.2,
        ),
        _compass(document_id='b1', cik='0000000002', prior_year_eps=1.0, reported_eps=1.0),
        _compass(document_id='c1', cik='0000000003', prior_year_eps=1.0, reported_eps=1.0),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'n_reported'] == 3
    # Three companies growing 200%, 0% and 0% average 2/3. Averaging the four rows
    # instead gives 3/4, which is the duplicate weighting company 1 as heavily as two.
    assert frame.loc[0, 'eps_growth_agg'] == pytest.approx(2.0 / 3.0)


def test_collapse_keeps_the_most_confident_row() -> None:
    """The dedupe rule is applied explicitly, not by row order."""
    from nowcast.aggregation.aggregate import collapse_to_companies

    frame = pd.DataFrame(
        [
            {
                'cik': '0000000001',
                'season_year': 2025,
                'season_quarter': 2,
                'document_id': 'low',
                'confidence': 0.2,
            },
            {
                'cik': '0000000001',
                'season_year': 2025,
                'season_quarter': 2,
                'document_id': 'high',
                'confidence': 0.9,
            },
        ]
    )
    kept, dropped = collapse_to_companies(frame, 'max_confidence')
    assert list(kept['document_id']) == ['high']
    assert dropped == 1


def test_share_reported_never_exceeds_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """More reporting companies than active members is a data error, not a share above 1."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path, count=2)
    rows = [_compass(document_id=f'doc-{index}', cik=f'{index + 1:010d}') for index in range(3)]
    with pytest.raises(DataError, match='share_reported would exceed 1'):
        aggregate_index(config, _extractions(rows), str(constituents))


def test_review_excluded_is_per_asof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A document queued for review is excluded only from the dates on or after it."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path)
    queue_path = tmp_path / 'data' / 'extractions' / 'review_queue.parquet'
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                'document_id': 'late',
                'field': 'reported_eps',
                'reason': 'low_confidence',
                'model': 'fake/model:free',
            }
        ]
    ).to_parquet(queue_path, index=False)

    rows = [
        _compass(document_id='early', cik='0000000001', report_date='2025-04-15'),
        _compass(document_id='late', cik='0000000002', report_date='2025-04-20'),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents)).reset_index(drop=True)
    assert frame['as_of_date'].tolist() == [pd.Timestamp('2025-04-15'), pd.Timestamp('2025-04-20')]
    # On 2025-04-15 the queued document had not even reported; it is not excluded from it.
    assert frame['n_review_excluded'].tolist() == [0, 1]
    assert frame['n_reported'].tolist() == [1, 1]


def test_season_column_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The season columns say `season_`, because they are calendar seasons."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    frame = aggregate_index(config, _extractions([_compass()]), str(_constituents(tmp_path)))
    assert {'season_year', 'season_quarter'}.issubset(frame.columns)
    assert not {'fiscal_year', 'fiscal_quarter'}.intersection(frame.columns)
    assert frame.loc[0, 'season_year'] == 2025
    assert frame.loc[0, 'season_quarter'] == 2


def test_season_of_uses_calendar_quarters() -> None:
    """Report dates map to the calendar quarter they fall in."""
    assert season_of('2025-01-15') == (2025, 1)
    assert season_of('2025-03-31') == (2025, 1)
    assert season_of('2025-04-01') == (2025, 2)
    assert season_of('2025-12-31') == (2025, 4)
    assert season_of(None) == (None, None)


def test_empty_input_returns_typed_empty_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No extractions gives an empty frame with the full column set, not a crash."""
    config = _config(tmp_path, monkeypatch)
    frame = aggregate_index(config, pd.DataFrame())
    assert frame.empty
    assert 'theme_demand_share' in frame.columns
    assert 'suppressed' in frame.columns


def test_market_cap_weights_are_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With market-cap weighting a large weight moves the aggregate."""
    weights_path = tmp_path / 'weights.csv'
    pd.DataFrame({'ticker': ['T00', 'T01'], 'weight': [9.0, 1.0]}).to_csv(weights_path, index=False)
    config = _config(
        tmp_path,
        monkeypatch,
        **{
            'aggregation.weighting': 'market_cap',
            'aggregation.weights_csv': str(weights_path),
            'aggregation.min_constituents': 1,
        },
    )
    constituents = _constituents(tmp_path)
    rows = [
        _compass(document_id='big', cik='0000000001', guidance_direction='raised'),
        _compass(document_id='small', cik='0000000002', guidance_direction='lowered'),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    # 9/10 weight raised, so the share is 0.9 rather than the equal-weighted 0.5.
    assert frame.loc[0, 'guidance_raise_share'] == pytest.approx(0.9)
    assert frame.loc[0, 'guidance_lower_share'] == pytest.approx(0.1)


def test_missing_weights_file_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured but absent weights file is a DataError naming the path."""
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.weighting': 'market_cap', 'aggregation.weights_csv': 'nope.csv'},
    )
    constituents = _constituents(tmp_path)
    rows = [_compass(document_id='a', cik='0000000001'), _compass(document_id='b', cik='2')]
    with pytest.raises(DataError, match='does not exist'):
        aggregate_index(config, _extractions(rows), str(constituents))


def test_duplicate_and_negative_weights_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Weights must be unique tickers with positive numbers."""
    from nowcast.aggregation.aggregate import load_weights

    bad = tmp_path / 'weights.csv'
    pd.DataFrame({'ticker': ['T00', 'T00'], 'weight': [1.0, 2.0]}).to_csv(bad, index=False)
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.weighting': 'market_cap', 'aggregation.weights_csv': str(bad)},
    )
    with pytest.raises(DataError, match='duplicate tickers'):
        load_weights(config)

    negative = tmp_path / 'negative.csv'
    pd.DataFrame({'ticker': ['T00'], 'weight': [-1.0]}).to_csv(negative, index=False)
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.weighting': 'market_cap', 'aggregation.weights_csv': str(negative)},
    )
    with pytest.raises(DataError, match='non-positive'):
        load_weights(config)


def test_output_columns_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The output carries exactly the columns the spec names, in order."""
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.min_constituents': 1, 'extraction.themes': 'demand,pricing'},
    )
    constituents = _constituents(tmp_path)
    frame = aggregate_index(config, _extractions([_compass()]), str(constituents))
    assert list(frame.columns) == [
        'as_of_date',
        'season_year',
        'season_quarter',
        'n_reported',
        'n_expected',
        'share_reported',
        'n_review_excluded',
        'share_of_cohort',
        'share_of_index',
        'theme_demand_share',
        'theme_pricing_share',
        'beat_rate',
        'eps_growth_agg',
        'guidance_raise_share',
        'guidance_lower_share',
        'guidance_ratio',
        'tone_score_mean',
        'n_obs_beat',
        'n_obs_growth',
        'n_obs_guidance',
        'n_obs_tone',
        'n_obs_theme_demand',
        'n_obs_theme_pricing',
        'metric_status_beat_rate',
        'metric_status_eps_growth_agg',
        'metric_status_guidance_raise_share',
        'metric_status_guidance_lower_share',
        'metric_status_guidance_ratio',
        'metric_status_tone_score_mean',
        'metric_status_theme_demand_share',
        'metric_status_theme_pricing_share',
        'suppressed',
    ]


def test_tone_score_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Confident is +1, neutral 0, cautious -1."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path)
    rows = [
        _compass(document_id='a', cik='0000000001', tone='confident'),
        _compass(document_id='b', cik='0000000002', tone='cautious'),
        _compass(document_id='c', cik='0000000003', tone='neutral'),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'tone_score_mean'] == pytest.approx(0.0)


def test_equal_weighting_ignores_missing_weights_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equal weighting never reads weights, so a blank path is harmless."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    assert config.aggregation.weighting == 'equal'
    assert np.isfinite(
        aggregate_index(config, _extractions([_compass()]), str(_constituents(tmp_path))).loc[
            0, 'beat_rate'
        ]
    )


def test_metric_suppressed_when_few_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twelve companies and one consensus figure is not a beat rate."""
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.min_constituents': 2, 'aggregation.min_observations': 5},
    )
    constituents = _constituents(tmp_path, count=12)
    rows = [
        _compass(
            document_id=f'doc-{index}',
            cik=f'{index + 1:010d}',
            consensus_eps=1.0 if index == 0 else None,
        )
        for index in range(12)
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'n_reported'] == 12
    assert frame.loc[0, 'n_obs_beat'] == 1
    assert pd.isna(frame.loc[0, 'beat_rate'])
    assert frame.loc[0, 'metric_status_beat_rate'] == 'insufficient_observations'
    # Growth is observed by all twelve, so it is computed.
    assert frame.loc[0, 'n_obs_growth'] == 12
    assert pd.notna(frame.loc[0, 'eps_growth_agg'])
    assert frame.loc[0, 'metric_status_eps_growth_agg'] == 'ok'


def test_no_metric_computed_from_fewer_than_min(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No metric value exists without at least min_observations observations behind it."""
    minimum = 4
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.min_constituents': 2, 'aggregation.min_observations': minimum},
    )
    constituents = _constituents(tmp_path, count=8)
    rows = [
        _compass(
            document_id=f'doc-{index}',
            cik=f'{index + 1:010d}',
            consensus_eps=1.0 if index < 2 else None,
            guidance_direction='raised' if index < 2 else None,
        )
        for index in range(8)
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    for name in ('beat_rate', 'guidance_raise_share', 'guidance_ratio'):
        assert pd.isna(frame.loc[0, name]), name
        assert frame.loc[0, f'metric_status_{name}'] == 'insufficient_observations'


def test_winsorize_uses_only_documents_public_by_asof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later document must not change an earlier as-of value."""
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.min_constituents': 1, 'aggregation.winsorize_pct': 0.2},
    )
    constituents = _constituents(tmp_path, count=6)
    rows = [
        _compass(
            document_id='a',
            cik='0000000001',
            report_date='2025-04-10',
            prior_year_eps=1.0,
            reported_eps=2.0,
        ),
        _compass(
            document_id='b',
            cik='0000000002',
            report_date='2025-04-10',
            prior_year_eps=1.0,
            reported_eps=2.0,
        ),
        _compass(
            document_id='c',
            cik='0000000003',
            report_date='2025-04-10',
            prior_year_eps=1.0,
            reported_eps=2.5,
        ),
    ]
    early = aggregate_index(config, _extractions(rows), str(constituents))
    later = [
        *rows,
        _compass(
            document_id='late',
            cik='0000000004',
            report_date='2025-04-20',
            prior_year_eps=1.0,
            reported_eps=100.0,
        ),
    ]
    full = aggregate_index(config, _extractions(later), str(constituents))
    first = early.iloc[0]['eps_growth_agg']
    same_date = full[full['as_of_date'] == early.iloc[0]['as_of_date']].iloc[0]['eps_growth_agg']
    assert first == pytest.approx(same_date)


def test_asof_value_unchanged_by_later_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Appending a later outlier leaves every earlier row byte-identical."""
    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.min_constituents': 1, 'aggregation.min_observations': 1},
    )
    constituents = _constituents(tmp_path, count=6)
    rows = [
        _compass(document_id=f'doc-{index}', cik=f'{index + 1:010d}', report_date='2025-04-10')
        for index in range(3)
    ]
    before = aggregate_index(config, _extractions(rows), str(constituents))
    after = aggregate_index(
        config,
        _extractions(
            [
                *rows,
                _compass(
                    document_id='outlier',
                    cik='0000000006',
                    report_date='2025-04-20',
                    reported_eps=99.0,
                    prior_year_eps=0.5,
                ),
            ]
        ),
        str(constituents),
    )
    earlier = after[after['as_of_date'] == before['as_of_date'].iloc[0]].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        before.reset_index(drop=True).drop(columns=['share_of_cohort', 'share_of_index']),
        earlier.drop(columns=['share_of_cohort', 'share_of_index']),
    )


def test_share_reported_uses_sampled_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The share is measured against the sampled cohort, not all ~500 members."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path, count=8)
    manifests = tmp_path / 'data' / 'manifests'
    manifests.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({'cik': ['0000000001', '0000000002'], 'season': ['2025Q2', '2025Q2']}).to_csv(
        manifests / 'cohort.csv', index=False
    )
    rows = [
        _compass(document_id='a', cik='0000000001'),
        _compass(document_id='b', cik='0000000002'),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'n_expected'] == 2
    assert frame.loc[0, 'share_reported'] == pytest.approx(1.0)
    assert frame.loc[0, 'share_of_index'] == pytest.approx(2 / 8)


def test_one_model_flag_does_not_exclude_other_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queue row about one model must not remove another model's good record."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    _constituents(tmp_path)
    queue_path = tmp_path / 'data' / 'extractions' / 'review_queue.parquet'
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                'document_id': 'doc-1',
                'field': 'record',
                'reason': 'low_confidence',
                'model': 'bad/model:free',
            }
        ]
    ).to_parquet(queue_path, index=False)
    rows = [
        _compass(document_id='doc-1', cik='0000000001', model='bad/model:free'),
        _compass(
            document_id='doc-1', cik='0000000001', model='good/model:free', record_confidence=0.99
        ),
    ]
    metrics = per_document_metrics(config, _extractions(rows))
    flags = metrics.frame.set_index('model')['in_review']
    assert bool(flags['bad/model:free']) is True
    assert bool(flags['good/model:free']) is False


def test_zeroed_confidence_falls_back_to_highest_document_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no confidence at all, every duplicate ties and the id decides, not row order."""
    from nowcast.aggregation.aggregate import collapse_to_companies

    config = _config(
        tmp_path,
        monkeypatch,
        **{'aggregation.dedupe_rule': 'max_confidence', 'aggregation.min_constituents': 1},
    )
    _constituents(tmp_path)
    rows = [
        _compass(
            document_id='zzz',
            cik='0000000001',
            prior_year_eps=1.0,
            reported_eps=3.0,
            record_confidence=0.0,
        ),
        _compass(
            document_id='aaa',
            cik='0000000001',
            prior_year_eps=1.0,
            reported_eps=1.0,
            record_confidence=0.0,
        ),
    ]
    metrics = per_document_metrics(config, _extractions(rows))
    kept, dropped = collapse_to_companies(metrics.frame, 'max_confidence')
    # Identical confidence: the tie-break is deterministic, not whichever row came first.
    assert dropped == 1
    assert list(kept['document_id']) == ['aaa']


def test_missing_confidence_column_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """max_confidence dedupe without a confidence column is an error, not a silent id sort."""
    config = _config(tmp_path, monkeypatch)
    frame = _extractions([_compass()]).drop(columns=['record_confidence'])
    with pytest.raises(DataError, match='record_confidence'):
        per_document_metrics(config, frame)


def test_unknown_tone_is_counted_not_silently_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A tone outside the vocabulary is logged by value, and scores NaN."""
    config = _config(tmp_path, monkeypatch)
    with caplog.at_level('WARNING'):
        metrics = per_document_metrics(config, _extractions([_compass(tone='ecstatic')]))
    assert pd.isna(metrics.frame.loc[0, 'tone_score'])
    assert any('unknown tone' in record.getMessage() for record in caplog.records)


def test_cohort_is_per_season(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A company sampled for another quarter is not expected to have reported this one."""
    config = _config(tmp_path, monkeypatch, **{'aggregation.min_constituents': 1})
    constituents = _constituents(tmp_path, count=8)
    manifests = tmp_path / 'data' / 'manifests'
    manifests.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {'cik': '0000000001', 'season': '2025Q2'},
            {'cik': '0000000002', 'season': '2025Q2'},
            # Two more sampled only for a different season.
            {'cik': '0000000003', 'season': '2025Q3'},
            {'cik': '0000000004', 'season': '2025Q3'},
        ]
    ).to_csv(manifests / 'cohort.csv', index=False)
    rows = [
        _compass(document_id='a', cik='0000000001', report_date='2025-04-20'),
        _compass(document_id='b', cik='0000000002', report_date='2025-04-20'),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'n_expected'] == 2
    assert frame.loc[0, 'share_reported'] == pytest.approx(1.0)


def test_dedupe_uses_confidence_when_duplicates_disagree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two documents for one company with different figures: the confident one wins.

    The other duplicate tests give both rows the same numbers, so they pass whichever
    row survives. Here the surviving row is observable in the aggregate.
    """
    config = _config(
        tmp_path,
        monkeypatch,
        **{
            'aggregation.min_constituents': 1,
            'aggregation.min_observations': 1,
            'aggregation.winsorize_pct': 0.0,
        },
    )
    constituents = _constituents(tmp_path)
    rows = [
        # Low confidence says a miss; high confidence says a beat. The aggregate reports
        # whichever survived the collapse, so this distinguishes the two rules.
        # Ids chosen so the id tie-break would pick the WRONG row: 'aaa' sorts first and
        # carries the low-confidence miss, 'zzz' carries the confident beat.
        _compass(
            document_id='aaa-miss',
            cik='0000000001',
            reported_eps=0.5,
            consensus_eps=1.0,
            record_confidence=0.2,
        ),
        _compass(
            document_id='zzz-beat',
            cik='0000000001',
            reported_eps=2.0,
            consensus_eps=1.0,
            record_confidence=0.9,
        ),
    ]
    frame = aggregate_index(config, _extractions(rows), str(constituents))
    assert frame.loc[0, 'n_reported'] == 1
    # The high-confidence row is a beat; the low-confidence one is a miss.
    assert frame.loc[0, 'beat_rate'] == pytest.approx(1.0)
