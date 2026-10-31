"""Index-level aggregation of per-document extractions, with a privacy guardrail.

Every metric here is computed in code from facts the model reported. The model never
computes a surprise, a growth rate or a share, and nothing in the output names a
company: outputs are index-level, and `assert_index_level_only` enforces that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from nowcast.config import Config, resolve_data_path
from nowcast.errors import DataError
from nowcast.extraction.review_queue import load_queue
from nowcast.ingestion.constituents import active_on, load_constituents

LOGGER = logging.getLogger(__name__)

# Decimal places beyond which a surprise is indistinguishable from its tolerance.
# Without this, a reported 1.05 against a 1.00 consensus differs from the 0.05 tolerance
# by 4e-17 and is graded a beat instead of inline.
SURPRISE_DECIMALS = 10

FORBIDDEN_COLUMNS = ('ticker', 'cik', 'document_id', 'company_name')
TONE_SCORES = {'confident': 1.0, 'neutral': 0.0, 'cautious': -1.0}
SUMMARY_COLUMNS = (
    'as_of_date',
    'season_year',
    'season_quarter',
    'n_reported',
    'n_expected',
    'share_reported',
    'n_review_excluded',
)
BASE_METRICS = (
    'beat_rate',
    'eps_growth_agg',
    'guidance_raise_share',
    'guidance_lower_share',
    'guidance_ratio',
    'tone_score_mean',
)


@dataclass(frozen=True)
class DocumentMetrics:
    """Per-document metrics, with review-queue membership carried as a column.

    Rows are kept rather than dropped so the exclusion can be counted per as-of date;
    dropping them here would make one number describe every date in the season.
    """

    frame: pd.DataFrame


def output_columns(config: Config) -> list[str]:
    """Return the aggregate frame's column order."""
    return [
        *SUMMARY_COLUMNS,
        *BASE_METRICS,
        *[f'theme_{theme}_share' for theme in config.extraction.themes],
        'suppressed',
    ]


def load_weights(config: Config) -> pd.DataFrame:
    """Load and validate market-cap weights, requiring unique tickers and positive values."""
    path = resolve_data_path(config, config.aggregation.weights_csv)
    if not path.is_file():
        raise DataError(
            f'aggregation.weights_csv is set to {config.aggregation.weights_csv!r} but '
            f'{path} does not exist; remove the key for equal weighting or supply the file'
        )
    frame = pd.read_csv(path, dtype={'ticker': str})
    missing = [column for column in ('ticker', 'weight') if column not in frame.columns]
    if missing:
        raise DataError(f'weights file {path} is missing required columns: {", ".join(missing)}')
    frame['ticker'] = frame['ticker'].str.strip().str.upper()
    frame['weight'] = pd.to_numeric(frame['weight'], errors='coerce')
    if frame['weight'].isna().any() or (frame['weight'] <= 0).any():
        raise DataError(f'weights file {path} has missing, non-numeric or non-positive weights')
    duplicated = frame['ticker'][frame['ticker'].duplicated()].unique().tolist()
    if duplicated:
        raise DataError(f'weights file {path} has duplicate tickers: {sorted(duplicated)[:5]}')
    return frame[['ticker', 'weight']]


def season_of(report_date: object) -> tuple[int | None, int | None]:
    """Return the calendar (fiscal) year and quarter a report date falls in."""
    try:
        moment = pd.Timestamp(report_date)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, None
    if pd.isna(moment):
        return None, None
    return int(moment.year), int((moment.month - 1) // 3 + 1)


def winsorize(series: pd.Series, proportion: float) -> pd.Series:
    """Clip both tails of a numeric series at the given proportion."""
    values = pd.to_numeric(series, errors='coerce')
    if proportion <= 0 or values.notna().sum() < 3:
        return values
    lower = float(values.quantile(proportion))
    upper = float(values.quantile(1.0 - proportion))
    return values.clip(lower=lower, upper=upper)


def _review_excluded(config: Config, extractions: pd.DataFrame) -> set[str]:
    """Return the document ids the review queue marked for human attention."""
    queue = load_queue(resolve_data_path(config, config.extraction.review_queue_path))
    if queue.empty:
        return set()
    return {str(value) for value in queue['document_id'].dropna()}


def collapse_to_companies(
    frame: pd.DataFrame, rule: str = 'max_confidence'
) -> tuple[pd.DataFrame, int]:
    """Return one row per (cik, season), collapsing duplicate reports.

    `frame` must already carry `season_year`, `season_quarter` and `confidence`.
    Two models extracting the same document, or two exhibits from one filing, are two
    rows describing one company's one quarter; counting both inflates `n_reported` and
    lets a single company pull a printed share toward itself. The surviving row is
    chosen by the configured rule, never by row order.

    Returns the collapsed frame and how many rows were dropped as duplicates.
    """
    if frame.empty:
        return frame, 0
    key = ['cik', 'season_year', 'season_quarter']
    ordered = frame.sort_values(
        [*key, 'confidence', 'document_id'], ascending=[True, True, True, False, True]
    )
    if rule == 'max_confidence':
        kept = ordered.drop_duplicates(subset=key, keep='first')
    elif rule == 'first_document':
        kept = ordered.drop_duplicates(subset=key, keep='last')
    else:
        raise DataError(f'unknown aggregation.dedupe_rule {rule!r}')
    return kept.reset_index(drop=True), int(len(frame) - len(kept))


def per_document_metrics(config: Config, extractions: pd.DataFrame) -> DocumentMetrics:
    """Compute per-document surprise, growth, guidance and tone, in code."""
    if extractions.empty:
        return DocumentMetrics(pd.DataFrame(columns=['document_id']))

    if 'cik' not in extractions.columns:
        raise DataError(
            'extractions must carry a cik column: the company count and the '
            '(company, season) collapse both key on it'
        )
    queued = _review_excluded(config, extractions)
    frame = extractions.copy()
    frame['document_id'] = frame['document_id'].astype(str)
    # CIKs arrive as '2', '0000000002' and sometimes an int; one spelling only, or the
    # same company would be counted as two.
    frame['cik'] = frame['cik'].astype('string').str.strip().str.zfill(10)
    # A queued document is marked, not deleted: an as-of date before the queue existed
    # must not be told that a company was excluded from it.
    frame['in_review'] = frame['document_id'].isin(queued)
    frame['confidence'] = pd.to_numeric(
        frame['confidence'] if 'confidence' in frame.columns else 0.0, errors='coerce'
    )
    if frame.empty:
        return DocumentMetrics(frame)

    frame['report_date'] = pd.to_datetime(frame['report_date'], errors='coerce')
    reported = pd.to_numeric(frame['reported_eps'], errors='coerce')
    consensus = pd.to_numeric(frame['consensus_eps'], errors='coerce')
    basis = (
        frame['eps_basis'].astype('string').str.lower().str.strip()
        if 'eps_basis' in frame.columns
        else pd.Series('', index=frame.index, dtype='string')
    )
    # A surprise is only meaningful when both figures exist and the basis is known;
    # comparing an adjusted figure to a GAAP consensus manufactures beats.
    comparable = reported.notna() & consensus.notna() & basis.notna() & (basis != '')
    frame['surprise'] = (reported - consensus).where(comparable)
    tolerance = float(config.extraction.eps_tolerance_abs)
    # Compare on a rounded surprise so binary residue cannot push an exact-tolerance
    # figure across the boundary it is meant to sit on.
    graded = frame['surprise'].round(SURPRISE_DECIMALS)
    frame['beat'] = np.select(
        [graded > tolerance, graded < -tolerance],
        [1.0, -1.0],
        default=0.0,
    )
    frame.loc[frame['surprise'].isna(), 'beat'] = np.nan

    prior = pd.to_numeric(frame['prior_year_eps'], errors='coerce')
    frame['eps_growth'] = (reported - prior) / prior.abs()
    frame.loc[prior.isna() | (prior == 0), 'eps_growth'] = np.nan
    frame['eps_growth'] = winsorize(frame['eps_growth'], float(config.aggregation.winsorize_pct))

    direction = frame['guidance_direction'].astype('string').str.lower().str.strip()
    frame['guidance_raised'] = (direction == 'raised').astype(float)
    frame['guidance_lowered'] = (direction == 'lowered').astype(float)
    frame['tone_score'] = frame['tone'].astype('string').str.lower().str.strip().map(TONE_SCORES)

    for theme in config.extraction.themes:
        column = f'theme_{theme}_direction'
        values = frame[column] if column in frame.columns else pd.Series(index=frame.index)
        frame[f'theme_{theme}_up'] = values.astype('string').str.lower().eq('up').astype(float)

    seasons = [season_of(value) for value in frame['report_date']]
    # These are calendar seasons derived from the filing date, not the company's own
    # fiscal year (which the record also holds): the column name has to say which.
    frame['season_year'] = [item[0] for item in seasons]
    frame['season_quarter'] = [item[1] for item in seasons]
    return DocumentMetrics(frame)


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    """Return a weight-weighted mean, NaN when no observation is present."""
    mask = values.notna() & weights.notna()
    if not mask.any():
        return float('nan')
    total = float(weights[mask].sum())
    if total <= 0:
        return float('nan')
    return float((values[mask] * weights[mask]).sum() / total)


def _row_weights(config: Config, frame: pd.DataFrame, tickers: pd.Series) -> pd.Series:
    """Return one weight per row: equal, or market cap for that row's ticker."""
    if config.aggregation.weighting == 'equal':
        return pd.Series(1.0, index=frame.index)
    weights = load_weights(config)
    mapping = dict(zip(weights['ticker'], weights['weight'], strict=True))
    resolved = tickers.astype('string').str.upper().map(mapping)
    missing = int(resolved.isna().sum())
    if missing:
        LOGGER.warning('no market-cap weight for %d documents; they are dropped', missing)
    return resolved.astype(float)


def aggregate_index(
    config: Config,
    extractions: pd.DataFrame,
    constituents_path: str | None = None,
) -> pd.DataFrame:
    """Return one index-level row per (season_year, season_quarter, as_of_date)."""
    columns = output_columns(config)
    if extractions.empty:
        return pd.DataFrame({column: pd.Series(dtype='object') for column in columns})

    metrics = per_document_metrics(config, extractions)
    frame = metrics.frame
    if frame.empty:
        return pd.DataFrame({column: pd.Series(dtype='object') for column in columns})

    constituents = load_constituents(
        resolve_data_path(config, constituents_path or config.data.constituents_csv)
    )
    minimum = int(config.aggregation.min_constituents)
    rows: list[dict[str, object]] = []

    season_keys = frame[['season_year', 'season_quarter']].dropna().drop_duplicates()
    for year, quarter in season_keys.itertuples(index=False, name=None):
        season = frame[(frame['season_year'] == year) & (frame['season_quarter'] == quarter)]
        for as_of in sorted(season['report_date'].dropna().unique()):
            stamp = pd.Timestamp(as_of)
            reported_docs = season[season['report_date'] <= stamp]
            members = active_on(constituents, stamp)
            # The queue is consulted at this date, so one company excluded later does
            # not appear as excluded from every earlier date in the season.
            excluded = int(reported_docs['in_review'].sum())
            counted = reported_docs[~reported_docs['in_review']]
            counted, _duplicate_rows = collapse_to_companies(
                counted, str(config.aggregation.dedupe_rule)
            )

            # Identifiers are used here only to join weights; they never reach the output.
            if config.aggregation.weighting == 'equal':
                weights = pd.Series(1.0, index=counted.index)
            else:
                ticker_by_cik = dict(
                    zip(
                        members['cik'].astype(str).str.zfill(10),
                        members['ticker'].astype(str),
                        strict=True,
                    )
                )
                tickers = counted['cik'].astype(str).str.zfill(10).map(ticker_by_cik)
                weights = _row_weights(config, counted, tickers)

            # One company reports one quarter once, so the company count, not the row
            # count, is what a share can legitimately be printed against.
            n_reported = int(counted['cik'].nunique())
            n_expected = len(members)
            share = (n_reported / n_expected) if n_expected else float('nan')
            if n_expected and n_reported > n_expected:
                raise DataError(
                    f'share_reported would exceed 1 at as_of={stamp.date()}: '
                    f'{n_reported} reported companies against {n_expected} members; '
                    'the constituents file does not cover the reports being aggregated'
                )
            row: dict[str, object] = {
                'as_of_date': stamp,
                'season_year': year,
                'season_quarter': quarter,
                'n_reported': n_reported,
                'n_expected': n_expected,
                'share_reported': share,
                'n_review_excluded': excluded,
            }
            suppressed = n_reported < minimum
            row['suppressed'] = bool(suppressed)

            if suppressed:
                # The guardrail: too few companies to report a share without disclosing one.
                row.update({name: float('nan') for name in BASE_METRICS})
                row.update({f'theme_{t}_share': float('nan') for t in config.extraction.themes})
            else:
                beats = counted['beat']
                graded = beats[beats.notna()]
                row['beat_rate'] = (
                    _weighted_mean((graded > 0).astype(float), weights.loc[graded.index])
                    if not graded.empty
                    else float('nan')
                )
                row['eps_growth_agg'] = _weighted_mean(counted['eps_growth'], weights)
                raise_share = _weighted_mean(counted['guidance_raised'], weights)
                lower_share = _weighted_mean(counted['guidance_lowered'], weights)
                row['guidance_raise_share'] = raise_share
                row['guidance_lower_share'] = lower_share
                denominator = (raise_share if pd.notna(raise_share) else 0.0) + (
                    lower_share if pd.notna(lower_share) else 0.0
                )
                row['guidance_ratio'] = (
                    float(raise_share) / denominator if denominator > 0 else float('nan')
                )
                row['tone_score_mean'] = _weighted_mean(counted['tone_score'], weights)
                for theme in config.extraction.themes:
                    row[f'theme_{theme}_share'] = _weighted_mean(
                        counted[f'theme_{theme}_up'], weights
                    )
            rows.append(row)

    return pd.DataFrame(rows, columns=columns).sort_values('as_of_date').reset_index(drop=True)


def assert_index_level_only(frame: pd.DataFrame, constituents: pd.DataFrame | None = None) -> None:
    """Raise DataError if the frame carries an identifier, by column name or by value."""
    lowered = {str(column).lower() for column in frame.columns}
    present = sorted(lowered.intersection(FORBIDDEN_COLUMNS))
    if present:
        raise DataError(
            f'aggregate output must be index-level: forbidden column(s) {", ".join(present)}'
        )
    if constituents is None or frame.empty:
        return
    identifiers: set[str] = set()
    for column in ('ticker', 'cik'):
        if column in constituents.columns:
            identifiers.update(str(value).strip().upper() for value in constituents[column])
    identifiers.discard('')
    if not identifiers:
        return
    for column in frame.columns:
        for value in frame[column].dropna().astype(str):
            if value.strip().upper() in identifiers:
                raise DataError(
                    f'aggregate output must be index-level: column {column!r} holds a '
                    'constituent identifier'
                )
