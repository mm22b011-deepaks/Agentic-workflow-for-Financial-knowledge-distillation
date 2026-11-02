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

from nowcast.config import Config, manifests_dir, resolve_data_path
from nowcast.errors import DataError
from nowcast.extraction.review_queue import affected_fields, load_queue
from nowcast.ingestion.constituents import active_on, load_constituents

LOGGER = logging.getLogger(__name__)

# Decimal places beyond which a surprise is indistinguishable from its tolerance.
# Without this, a reported 1.05 against a 1.00 consensus differs from the 0.05 tolerance
# by 4e-17 and is graded a beat instead of inline.
SURPRISE_DECIMALS = 10

FORBIDDEN_COLUMNS = ('ticker', 'cik', 'document_id', 'company_name')
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
    # Optional: only computable when a consensus source exists. A release states EPS and
    # revenue, so growth and guidance are what the documents themselves support.
    'beat_rate',
    'eps_growth_agg',
    'revenue_growth_agg',
    'guidance_raise_share',
    'guidance_lower_share',
    'guidance_ratio',
    'tone_score_mean',
)
# Observations behind each metric. A metric with fewer real observations than
# `aggregation.min_observations` is NaN with a status, never computed: with twelve
# companies and one consensus figure, a "beat rate" of 1.0 is that company's result.
OBSERVATION_COLUMNS = (
    'n_obs_beat',
    'n_obs_growth',
    'n_obs_revenue_growth',
    'n_obs_guidance',
    'n_obs_tone',
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
        'n_planned',
        'n_attempted',
        'execution_complete',
        'n_eligible_releases',
        'n_guidance_providers',
        'share_of_cohort',
        'share_of_index',
        *[f'theme_{theme}_share' for theme in config.extraction.themes],
        *BASE_METRICS,
        *OBSERVATION_COLUMNS,
        *[f'n_obs_theme_{theme}' for theme in config.extraction.themes],
        *[f'metric_status_{name}' for name in BASE_METRICS],
        *[f'metric_status_theme_{theme}_share' for theme in config.extraction.themes],
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


def _review_excluded(config: Config, extractions: pd.DataFrame) -> dict[tuple[str, str], set[str]]:
    """Return {(document, model): flagged fields} from the queue.

    `field == 'record'` means the whole record is in question; a named field means only
    that field. Keyed by model too: one model's flag must not remove another model's
    good record of the same filing.
    """
    queue = load_queue(resolve_data_path(config, config.extraction.review_queue_path))
    if queue.empty:
        return {}
    flagged: dict[tuple[str, str], set[str]] = {}
    for row in queue[['document_id', 'model', 'field', 'reason']].dropna().itertuples(index=False):
        key = (str(row.document_id), str(row.model))
        effects = affected_fields(str(row.field), str(row.reason))
        flagged.setdefault(key, set()).update(effects)
    return flagged


def collapse_to_companies(
    frame: pd.DataFrame, rule: str = 'max_confidence', model_priority: tuple[str, ...] = ()
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
    # Confidence first, document id as the tie-break: rows written before `consolidate`
    # recorded a confidence would otherwise all tie at NaN and resolve by id.
    ordered = frame.sort_values(
        [*key, 'confidence', 'document_id'], ascending=[True, True, True, False, True]
    )
    if rule == 'model_priority':
        ordered = frame.assign(
            _priority=frame['model']
            .map({name: rank for rank, name in enumerate(model_priority)})
            .fillna(len(model_priority))
        )
        kept = (
            ordered.sort_values(
                [*key, '_priority', 'report_date', 'document_id'],
                ascending=[True, True, True, True, False, True],
            )
            .drop_duplicates(subset=key)
            .drop(columns='_priority')
        )
    elif rule == 'max_confidence':
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
    if 'stale' in frame.columns:
        # consolidate sets this for a result written under other settings; it answers a
        # different question and must not enter this run's counts.
        frame = frame[~frame['stale'].fillna(False).astype(bool)].copy()
    frame['document_id'] = frame['document_id'].astype(str)
    # CIKs arrive as '2', '0000000002' and sometimes an int; one spelling only, or the
    # same company would be counted as two.
    frame['cik'] = frame['cik'].astype('string').str.strip().str.zfill(10)
    # A queued document is marked, not deleted: an as-of date before the queue existed
    # must not be told that a company was excluded from it.
    model = (
        frame['model'].astype('string')
        if 'model' in frame.columns
        else pd.Series('', index=frame.index, dtype='string')
    )
    frame['in_review'] = [
        (document, str(name)) in queued
        for document, name in zip(frame['document_id'], model, strict=True)
    ]
    frame['blocked'] = [
        'record' in queued.get((document, str(name)), set())
        for document, name in zip(frame['document_id'], model, strict=True)
    ]
    frame['flagged_fields'] = [
        queued.get((document, str(name)), set())
        for document, name in zip(frame['document_id'], model, strict=True)
    ]
    if 'record_confidence' in frame.columns:
        frame['confidence'] = pd.to_numeric(frame['record_confidence'], errors='coerce')
    elif 'confidence' in frame.columns:
        frame['confidence'] = pd.to_numeric(frame['confidence'], errors='coerce')
    elif str(config.aggregation.dedupe_rule) == 'max_confidence':
        # Silently weighting by a column that does not exist is how every duplicate
        # ended up resolved by document id while the config said "highest confidence".
        raise DataError(
            'dedupe_rule is max_confidence but the extractions frame has no '
            'record_confidence column; regenerate it with `extract`'
        )
    else:
        frame['confidence'] = 0.0
    if frame.empty:
        return DocumentMetrics(frame)

    # A field the review queue flagged is withdrawn from its own metric and from
    # nothing else: the company still counts as having reported, and its revenue still
    # counts in a revenue metric. Blocking reasons already removed the row entirely.
    flagged = frame['flagged_fields'] if 'flagged_fields' in frame.columns else None

    def withdraw(column: str | pd.Series, fields: tuple[str, ...]) -> pd.Series:
        values = frame[column] if isinstance(column, str) else column
        if flagged is None:
            return values
        mask = pd.Series(
            [bool(set(fields) & set(item if item is not None else ())) for item in flagged],
            index=frame.index,
        )
        return values.where(~mask)

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
    # Un-winsorised: the clip has to happen inside each as-of snapshot, or an early
    # date's value depends on a document published after it.
    frame['eps_growth'] = (reported - prior) / prior.abs()
    if 'prior_year_basis' in frame.columns:
        prior_basis = frame['prior_year_basis'].astype('string').str.lower().str.strip()
        frame['eps_growth'] = frame['eps_growth'].where(prior_basis.notna() & prior_basis.eq(basis))
    frame.loc[prior.isna() | (prior == 0), 'eps_growth'] = np.nan
    frame['beat'] = withdraw('beat', ('reported_eps', 'consensus_eps'))
    frame['eps_growth'] = withdraw('eps_growth', ('reported_eps', 'prior_year_eps'))
    if 'revenue_yoy_growth_pct' in frame.columns:
        frame['revenue_growth'] = pd.to_numeric(frame['revenue_yoy_growth_pct'], errors='coerce')
    else:
        frame['revenue_growth'] = np.nan
    frame['revenue_growth'] = withdraw('revenue_growth', ('revenue_yoy_growth',))

    direction = frame['guidance_direction'].astype('string').str.lower().str.strip()
    frame['guidance_raised'] = (direction == 'raised').astype(float)
    frame['guidance_lowered'] = (direction == 'lowered').astype(float)
    providers = direction.notna() & direction.ne('not_provided')
    frame['guidance_raised'] = frame['guidance_raised'].where(providers)
    frame['guidance_lowered'] = frame['guidance_lowered'].where(providers)
    presence = frame.get('guidance_presence', pd.Series(index=frame.index, dtype='string'))
    frame['guidance_provider'] = presence.eq('provided') | (presence.isna() & providers)
    frame['guidance_raised'] = withdraw('guidance_raised', ('guidance_direction',))
    frame['guidance_lowered'] = withdraw('guidance_lowered', ('guidance_direction',))
    scores = {str(k).lower(): float(v) for k, v in config.extraction.tone_scores.items()}
    raw_tone = frame['tone'].astype('string').str.lower().str.strip()
    unknown = raw_tone.dropna()
    unknown = unknown[~unknown.isin(scores)]
    if not unknown.empty:
        # Counted, not silently NaN: an unknown tone is a vocabulary drift to fix.
        LOGGER.warning('unknown tone values: %s', dict(unknown.value_counts().head(5)))
    frame['tone_score'] = withdraw(raw_tone.map(scores), ('tone',))

    for theme in config.extraction.themes:
        column = f'theme_{theme}_direction'
        values = frame[column] if column in frame.columns else pd.Series(index=frame.index)
        up = values.astype('string').str.lower().eq('up').astype(float)
        frame[f'theme_{theme}_up'] = withdraw(up, (column, f'theme.{theme}'))

    seasons = [season_of(value) for value in frame['report_date']]
    # These are calendar seasons derived from the filing date, not the company's own
    # fiscal year (which the record also holds): the column name has to say which.
    frame['season_year'] = [item[0] for item in seasons]
    frame['season_quarter'] = [item[1] for item in seasons]
    return DocumentMetrics(frame)


def _directional(raised: pd.Series, lowered: pd.Series) -> int:
    """Return how many companies stated a raise or a lower, the ratio's real denominator."""
    stated = raised.fillna(0.0) + lowered.fillna(0.0)
    return int((stated > 0).sum())


def _cohort_members(config: Config) -> set[str]:
    """Return the CIKs the ingest sampled, from the cohort file; every member if absent."""
    path = manifests_dir(config) / 'cohort.csv'
    if not path.is_file():
        return set()
    frame = pd.read_csv(path, dtype={'cik': str})
    return {str(value).strip().zfill(10) for value in frame['cik']}


def cohort_by_season(config: Config) -> dict[str, set[str]]:
    """Return the sampled cohort per season; {} when no cohort file exists."""
    path = manifests_dir(config) / 'cohort.csv'
    if not path.is_file():
        return {}
    frame = pd.read_csv(path, dtype={'cik': str})
    result: dict[str, set[str]] = {}
    for row in frame.itertuples(index=False):
        result.setdefault(str(row.season), set()).add(str(row.cik).strip().zfill(10))
    return result


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

    frame = frame[
        [
            str(row.cik)
            in set(active_on(constituents, str(row.report_date)).cik.astype(str).str.zfill(10))
            for row in frame.itertuples()
        ]
    ].copy()
    pair_path = manifests_dir(config) / 'pair_outcomes.csv'
    planned_pairs = (
        pd.read_csv(pair_path, dtype={'cik': str}) if pair_path.exists() else pd.DataFrame()
    )
    season_keys = frame[['season_year', 'season_quarter']].dropna().drop_duplicates()
    for year, quarter in season_keys.itertuples(index=False, name=None):
        season = frame[(frame['season_year'] == year) & (frame['season_quarter'] == quarter)]
        for as_of in sorted(season['report_date'].dropna().unique()):
            stamp = pd.Timestamp(as_of)
            reported_docs = season[season['report_date'] <= stamp]
            members = active_on(constituents, stamp)
            # The queue is consulted at this date, so one company excluded later does
            # not appear as excluded from every earlier date in the season.
            excluded = int(reported_docs.loc[reported_docs['in_review'], 'cik'].nunique())
            counted = reported_docs[~reported_docs['blocked']]
            counted, _duplicate_rows = collapse_to_companies(
                counted,
                str(config.aggregation.dedupe_rule),
                tuple(config.aggregation.model_priority or config.llm.models),
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
            # The denominator is the sampled cohort, not all ~500 members: a 100-document
            # run against the whole index reports a share near 0.03 and suppresses
            # everything. Without a cohort file the index is the cohort.
            season_start = pd.Timestamp(year=int(year), month=(int(quarter) - 1) * 3 + 1, day=1)
            interval_members = constituents[
                (constituents.effective_from <= stamp)
                & (constituents.effective_to.isna() | (constituents.effective_to >= season_start))
            ]
            member_ciks = set(interval_members.cik.astype(str).str.zfill(10))
            # The season's own cohort when the ingest recorded one: a company sampled for
            # another quarter did not report this one, and counting it as expected makes
            # share_reported look like a coverage failure instead of a partial season.
            season_key = f'{year}Q{quarter}'
            cohort = cohort_by_season(config).get(season_key)
            if cohort:
                n_expected = len(cohort & member_ciks)
            else:
                cohort = _cohort_members(config)
                n_expected = len(cohort & member_ciks) if cohort else len(member_ciks)
            n_index_members = len(members)
            share = (n_reported / n_expected) if n_expected else float('nan')
            share_of_index = (n_reported / n_index_members) if n_index_members else float('nan')
            if n_expected and n_reported > n_expected:
                raise DataError(
                    f'share_reported would exceed 1 at as_of={stamp.date()}: '
                    f'{n_reported} reported companies against {n_expected} cohort members; '
                    'the cohort file does not cover the reports being aggregated'
                )
            season_pairs = (
                planned_pairs[planned_pairs.season.eq(season_key)]
                if not planned_pairs.empty
                else pd.DataFrame()
            )
            if not season_pairs.empty:
                n_expected = int(season_pairs.outcome.ne('unvisited').sum())
                if n_reported > n_expected:
                    raise DataError('share_reported would exceed 1: reports exceed attempted pairs')
                share = n_reported / n_expected if n_expected else float('nan')
            n_planned = len(season_pairs) if not season_pairs.empty else n_expected
            row: dict[str, object] = {
                'n_planned': n_planned,
                'n_attempted': n_expected,
                'execution_complete': bool(n_expected == n_planned),
                'n_eligible_releases': int(reported_docs.document_id.nunique()),
                'n_guidance_providers': int(counted.guidance_provider.fillna(False).sum()),
                'as_of_date': stamp,
                'season_year': year,
                'season_quarter': quarter,
                'n_reported': n_reported,
                'n_expected': n_expected,
                'share_reported': share,
                'share_of_cohort': share,
                'share_of_index': share_of_index,
                'n_review_excluded': excluded,
            }
            suppressed = n_reported < minimum
            row['suppressed'] = bool(suppressed)

            # Winsorise inside this snapshot only: clipping over the whole season lets a
            # document published later change an earlier as-of value (look-ahead).
            counted = counted.copy()
            counted['eps_growth'] = winsorize(
                counted['eps_growth'], float(config.aggregation.winsorize_pct)
            )
            observations = {
                'beat_rate': counted['beat'].notna().sum(),
                'eps_growth_agg': counted['eps_growth'].notna().sum(),
                'revenue_growth_agg': counted['revenue_growth'].notna().sum(),
                'guidance_raise_share': counted['guidance_raised'].notna().sum(),
                'guidance_lower_share': counted['guidance_lowered'].notna().sum(),
                'guidance_ratio': (
                    _directional(counted['guidance_raised'], counted['guidance_lowered'])
                ),
                'tone_score_mean': counted['tone_score'].notna().sum(),
            }
            row['n_obs_beat'] = int(observations['beat_rate'])
            row['n_obs_growth'] = int(observations['eps_growth_agg'])
            row['n_obs_revenue_growth'] = int(observations['revenue_growth_agg'])
            row['n_obs_guidance'] = int(observations['guidance_ratio'])
            row['n_obs_tone'] = int(observations['tone_score_mean'])
            theme_obs = {
                theme: int(counted[f'theme_{theme}_up'].notna().sum())
                for theme in config.extraction.themes
            }
            for theme, count in theme_obs.items():
                row[f'n_obs_theme_{theme}'] = count

            values: dict[str, float] = {}
            if not suppressed:
                graded = counted['beat']
                graded = graded[graded.notna()]
                values['beat_rate'] = (
                    _weighted_mean((graded > 0).astype(float), weights.loc[graded.index])
                    if not graded.empty
                    else float('nan')
                )
                values['eps_growth_agg'] = _weighted_mean(counted['eps_growth'], weights)
                values['revenue_growth_agg'] = _weighted_mean(counted['revenue_growth'], weights)
                raise_share = _weighted_mean(counted['guidance_raised'], weights)
                lower_share = _weighted_mean(counted['guidance_lowered'], weights)
                values['guidance_raise_share'] = raise_share
                values['guidance_lower_share'] = lower_share
                denominator = (raise_share if pd.notna(raise_share) else 0.0) + (
                    lower_share if pd.notna(lower_share) else 0.0
                )
                values['guidance_ratio'] = (
                    float(raise_share) / denominator if denominator > 0 else float('nan')
                )
                values['tone_score_mean'] = _weighted_mean(counted['tone_score'], weights)
                for theme in config.extraction.themes:
                    values[f'theme_{theme}_share'] = _weighted_mean(
                        counted[f'theme_{theme}_up'], weights
                    )
            else:
                # The guardrail: too few companies to report a share without disclosing one.
                values = dict.fromkeys(
                    (*BASE_METRICS, *[f'theme_{t}_share' for t in config.extraction.themes]),
                    float('nan'),
                )

            # A metric also needs enough observations of its own. Twelve companies and
            # one consensus figure is a beat rate of 1.0: one company's result.
            metric_minimum = int(config.aggregation.min_observations)
            has_consensus = bool(counted['consensus_eps'].notna().any())
            for name in BASE_METRICS:
                count = int(observations[name])
                if name == 'beat_rate' and not has_consensus:
                    # No analyst estimate anywhere in the season: a beat rate would be a
                    # computed number about nothing. Named, not merely absent.
                    row[name] = float('nan')
                    row[f'metric_status_{name}'] = 'no_consensus'
                    continue
                if suppressed or count < metric_minimum:
                    row[name] = float('nan')
                    row[f'metric_status_{name}'] = 'insufficient_observations'
                else:
                    row[name] = values[name]
                    row[f'metric_status_{name}'] = 'ok'
            for theme, count in theme_obs.items():
                key = f'theme_{theme}_share'
                if suppressed or count < metric_minimum:
                    row[key] = float('nan')
                    row[f'metric_status_{key}'] = 'insufficient_observations'
                else:
                    row[key] = values[key]
                    row[f'metric_status_{key}'] = 'ok'
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
