"""Read-only node inspection; public projections never contain document identifiers."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import hmac
import io
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from sqlalchemy import text

from nowcast.config import Config
from nowcast.contracts import (
    ChartPoint,
    EvidenceField,
    EvidenceResponse,
    FieldProfile,
    LabelRequest,
    LabelResponse,
    MetricSnapshot,
    PaneResponse,
    StageSnapshot,
    StageState,
)
from nowcast.errors import DataError
from nowcast.jobs import JobStore, config_fingerprint
from nowcast.paths import Paths
from nowcast.storage import atomic_bytes, file_lock
from nowcast.workflow_registry import canvas_registry

_PANE_TOKEN_KEY = secrets.token_bytes(32)


def index_rows(config: Config, frame: pd.DataFrame) -> pd.DataFrame:
    """Present one KPI per quarter without changing the stored aggregate artifact."""
    if not {'season_year', 'season_quarter'}.issubset(frame):
        return frame
    from nowcast.registry import load_registry

    rows = []
    count_keys = {
        'eps_growth': 'growth',
        'revenue_growth': 'revenue_growth',
        'guidance': 'guidance',
        'tone': 'tone',
    }
    for row in frame.to_dict('records'):
        for kpi in load_registry(config).kpis:
            n = row.get('n_obs_' + count_keys[kpi.id])
            expected = row.get('n_expected')
            rows.append(
                {
                    'metric': kpi.label,
                    'season': f'{int(row["season_year"])}Q{int(row["season_quarter"])}',
                    'metric_value': row.get(kpi.output),
                    'metric_unit': kpi.unit,
                    'n_reported': n,
                    'n_expected': expected,
                    'coverage': n / expected if n is not None and expected else None,
                    'threshold': config.aggregation.min_observations / expected
                    if expected
                    else None,
                    'pass': row.get('metric_status_' + kpi.output) == 'ok'
                    and not row.get('suppressed', True),
                    'suppressed': row.get('suppressed'),
                }
            )
    return pd.DataFrame(rows)


def public_frame(frame: pd.DataFrame, models: tuple[str, ...] = ()) -> pd.DataFrame:
    """Allow only typed, non-identifying attributes; never forward text or quotes."""
    if 'filing_date' in frame and 'report_date' not in frame:
        frame = frame.rename(columns={'filing_date': 'report_date'})
    currencies = (
        'USD',
        'EUR',
        'GBP',
        'CAD',
        'JPY',
        'AUD',
        'CHF',
        'CNY',
        'HKD',
        'INR',
        'SEK',
        'NOK',
        'DKK',
        'SGD',
        'NZD',
        'BRL',
        'MXN',
        'ZAR',
        'KRW',
        'TWD',
    )
    public = pd.DataFrame(index=frame.index)
    for source, target in [
        ('cik', 'member_token'),
        ('document_id', 'release_token'),
        ('accession', 'release_token'),
    ]:
        if source in frame and target not in public:
            public[target] = frame[source].map(
                lambda value: hmac.new(
                    _PANE_TOKEN_KEY, str(value).encode(), hashlib.sha256
                ).hexdigest()
            )
    dates = {
        'joined',
        'left',
        'start_date',
        'end_date',
        'effective_from',
        'effective_to',
        'report_date',
        'downloaded_at',
        'completed_at',
    }
    numeric = {
        'chars',
        'chars_sent',
        'bytes',
        'size_bytes',
        'confidence',
        'record_confidence',
        'flagged',
        'truncated',
        'issues',
        'mapped',
        'season_year',
        'season_quarter',
        'n_reported',
        'n_expected',
        'coverage',
        'suppressed',
        'companies',
        'quarters',
        'releases',
        'requests',
        'days',
        'base_requests',
        'expected_requests',
        'model_days',
        'eps_growth_agg',
        'revenue_growth_agg',
        'quote_check',
        'number_check',
        'scale_check',
        'row_check',
        'period_check',
        'checks',
        'metric_value',
        'threshold',
        'pass',
        'reported_eps',
        'revenue',
        'company_quarters',
    }
    for column in frame:
        if column in numeric:
            public[column] = pd.to_numeric(frame[column], errors='coerce')
        elif column in dates:
            public[column] = pd.to_datetime(frame[column], errors='coerce', utc=True).dt.strftime(
                '%Y-%m-%d'
            )
        elif column == 'season':
            public[column] = frame[column].where(
                frame[column].astype(str).str.fullmatch(r'\d{4}Q[1-4]')
            )
        elif column == 'items':
            public[column] = frame[column].where(
                frame[column].astype(str).str.fullmatch(r'[0-9.,; ]+')
            )
        elif column == 'outcome':
            public[column] = frame[column].where(
                frame[column].isin(['downloaded', 'no_release', 'failed', 'unvisited'])
            )
    for column, allowed in {
        'reason': [
            'empty_extraction',
            'eps_missing',
            'low_confidence',
            'null_reason_missing',
            'doc_truncated',
            'validation_issues',
            'quote_missing',
            'quote_too_long',
            'quote_not_found',
            'number_not_in_quote',
            'number_not_in_source',
            'period_not_near_filing',
            'period_invalid',
            'basis_missing',
            'vocab_invalid',
        ],
        'metric': [
            'EPS growth proxy',
            'Revenue growth proxy',
            'Guidance direction',
            'Tone score',
            'eps_growth',
            'revenue_growth',
            'guidance',
            'tone',
        ],
        'metric_unit': ['fraction', 'percent', 'score'],
        'format': ['Index snapshot', 'KPI records', 'Report'],
        'currency': currencies,
        'tone': ['confident', 'neutral', 'cautious', 'mixed', 'positive', 'negative'],
        'guidance_presence': ['provided', 'not_provided', 'yes', 'no'],
        'status': [
            'succeeded',
            'failed',
            'ok',
            'suppressed',
            'unavailable',
            'insufficient_observations',
            'no_consensus',
        ],
    }.items():
        if column in frame:
            public[column] = frame[column].where(frame[column].isin(allowed))
    if 'model' in frame:
        public['model'] = frame.model.where(frame.model.isin([*models, 'synthetic:free']))
    for column in [
        'parse_success_rate',
        'empty_completion_rate',
        'latency_p95_seconds',
        'nonempty_extractions',
        'tokens',
    ]:
        if column in frame:
            public[column] = pd.to_numeric(frame[column], errors='coerce')
    if 'reason' in public:
        public['flagged'] = True
        if 'field' in frame:
            public['review_field'] = frame.field.where(frame.field.isin((*FIELDS, 'record')))
    if 'seasons' in frame:
        public['seasons'] = frame.seasons.map(
            lambda value: (
                len(value)
                if isinstance(value, list)
                else len(json.loads(value))
                if isinstance(value, str) and value.startswith('[')
                else value
                if isinstance(value, (int, float))
                else None
            )
        )
    if 'cik' in frame:
        public['mapped'] = frame.cik.notna() & frame.cik.astype(str).str.fullmatch(r'\d{1,10}')
    if 'report_date' in public:
        public['season'] = pd.to_datetime(public.report_date).dt.to_period('Q').astype(str)
    if {'n_reported', 'n_expected'}.issubset(public):
        public['coverage'] = public.n_reported.div(public.n_expected.where(public.n_expected.gt(0)))
    if {'field', 'value'}.issubset(frame):
        public['setting'] = frame.field.where(
            frame.field.astype(str).str.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*')
        )
        public['setting_value'] = frame.value.map(
            lambda v: v if isinstance(v, (bool, int, float)) else None
        )
        public['kind'] = frame.value.map(
            lambda v: (
                'Boolean'
                if isinstance(v, bool)
                else 'Number'
                if isinstance(v, (int, float))
                else 'Names hidden'
            )
        )
    if 'record' in frame:
        records = frame.record.map(
            lambda value: json.loads(value) if isinstance(value, str) else value
        )
        public['currency'] = records.map(
            lambda record: record.get('currency') if isinstance(record, dict) else None
        )
        public['currency'] = public.currency.where(public.currency.isin(currencies))
        fiscal_seasons = records.map(
            lambda record: (
                f'{record.get("fiscal_year")}Q{record.get("fiscal_quarter")}'
                if isinstance(record, dict)
                and record.get('fiscal_year')
                and record.get('fiscal_quarter') in [1, 2, 3, 4]
                else None
            )
        )
        public['season'] = (
            fiscal_seasons.fillna(public.get('season')) if 'season' in public else fiscal_seasons
        )
        for key in ['reported_eps', 'revenue', 'guidance_presence', 'tone']:
            name = {'reported_eps': 'eps', 'guidance_presence': 'guidance'}.get(key, key)
            public[name + '_confidence'] = [
                record.get(key, {}).get('confidence') if isinstance(record, dict) else None
                for record in records
            ]
            public[name + '_status'] = [
                'Present'
                if isinstance(record, dict) and record.get(key, {}).get('value') is not None
                else 'Not stated'
                for record in records
            ]
            public[key] = [
                record.get(key, {}).get('value') if isinstance(record, dict) else None
                for record in records
            ]
            if key in {'reported_eps', 'revenue'}:
                public[key] = pd.to_numeric(public[key], errors='coerce')
            else:
                public[key] = public[key].where(
                    public[key].isin(
                        [
                            'positive',
                            'negative',
                            'neutral',
                            'confident',
                            'cautious',
                            'mixed',
                            'yes',
                            'no',
                            'provided',
                            'not_provided',
                            'raised',
                            'lowered',
                            'maintained',
                        ]
                    )
                )
    return public.reset_index(drop=True)


UPSTREAM = {
    'validate-config': None,
    'build-constituents': 'validate-config',
    'estimate-scope': 'build-constituents',
    'cohort': 'build-constituents',
    'ingest': 'estimate-scope',
    'discover': 'cohort',
    'download': 'discover',
    'parse': 'download',
    'extract': 'parse',
    'extract-step': 'parse',
    'validate': 'extract',
    'review': 'validate',
    'consolidate': 'validate',
    'aggregate': 'consolidate',
    'gate': 'aggregate',
    'publish': 'gate',
    'suppressed': 'gate',
    'nowcast': 'publish',
    'model-bakeoff': 'parse',
}
PRIVATE_STAGES = {
    'demo-ingest',
    'demo-parse',
    'demo-extract',
    'demo-validate',
    'build-constituents',
    'cohort',
    'discover',
    'download',
    'ingest',
    'parse',
    'extract',
    'extract-step',
    'validate',
    'review',
    'consolidate',
    'prepare-labels',
    'freeze-panel',
    'rebuild-index',
    'validate-index',
}
FIELDS = (
    'reported_eps',
    'prior_year_eps',
    'consensus_eps',
    'revenue',
    'revenue_yoy_growth',
    'eps_basis',
    'prior_year_basis',
    'guidance_presence',
    'guidance_direction',
    'guidance_metric',
    'tone',
)


def read_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    if path.suffix == '.parquet':
        return pd.read_parquet(path)
    if path.suffix == '.csv':
        return pd.read_csv(path, dtype={'cik': str})
    if path.suffix == '.json':
        raw = json.loads(path.read_text())
        if isinstance(raw, dict):
            raw = raw.get('snapshots', raw.get('records', [raw]))
        if isinstance(raw, list):
            return pd.DataFrame(raw)
    return pd.DataFrame()


def source_files(config: Config, config_path: Path, node: str) -> list[Path]:
    from nowcast.artifacts import stage_files
    from nowcast.phase_services import phase_path

    paths = Paths.from_config(config)
    if node in {'demo-ingest', 'demo-parse'}:
        return [paths.resolve('demo') / config.data.document_index]
    if node in {'demo-extract', 'demo-validate'}:
        return [paths.resolve('demo/extractions/extractions.parquet')]
    if node == 'demo-aggregate':
        return [paths.resolve('demo/index.json')]
    phase = phase_path(config, node)
    if phase.is_file():
        return [phase]
    if node == 'cohort':
        return [paths.resolve('manifests/pair_outcomes.csv')]
    if node in {'download', 'parse', 'ingest', 'validate-index', 'rebuild-index'}:
        return [paths.resolve(config.data.document_index)]
    if node in {'extract-step', 'validate', 'consolidate', 'extract'}:
        return [paths.extractions(config) / 'extractions.parquet']
    if node == 'review':
        return [paths.resolve(config.extraction.review_queue_path)]
    if node == 'publish' and paths.resolve('exports/kpis.json').is_file():
        return [paths.resolve('exports/kpis.json')]
    if node in {'gate', 'publish', 'suppressed'}:
        return [paths.aggregates(config) / 'index_aggregates.parquet']
    return stage_files(config, config_path, node)


def frame_for(
    config: Config, config_path: Path, store: JobStore, node: str, run: str | None = None
) -> pd.DataFrame:
    if run:
        with store.engine.connect() as connection:
            value = connection.execute(
                text('SELECT files FROM artifacts WHERE job_id=:run AND stage=:stage'),
                {'run': run, 'stage': node},
            ).scalar_one_or_none()
        if not value:
            raise DataError('run artifact unavailable')
        files = [Path(item['snapshot']) for item in json.loads(value) if item.get('snapshot')]
        if not files or any(not p.is_relative_to(store.path.parent / 'runs') for p in files):
            raise DataError('run snapshot unavailable')
    else:
        files = source_files(config, config_path, node)
    if node in {'export', 'report', 'doctor', 'quality-summary'}:
        frames = [
            pd.DataFrame(
                [
                    {
                        'format': 'Report'
                        if node != 'export'
                        else 'KPI records'
                        if path.name.endswith('kpis.json')
                        else 'Index snapshot',
                        'size_bytes': path.stat().st_size,
                        'completed_at': datetime.fromtimestamp(
                            path.stat().st_mtime, timezone.utc
                        ).isoformat(),
                        'status': 'succeeded',
                        'checks': 1,
                    }
                    for path in files
                    if path.is_file()
                ]
            )
        ]
    elif node == 'model-bakeoff':
        # The report also contains a private sample keyed by company identifier.
        frames = [
            pd.DataFrame(json.loads(path.read_text()).get('models', []))
            for path in files
            if path.is_file()
        ]
    else:
        frames = [
            read_frame(path) for path in files if path.suffix in {'.parquet', '.csv', '.json'}
        ]
    frames = [f for f in frames if not f.empty]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if node == 'freeze-panel' and not frame.empty:
        frame = pd.DataFrame(
            [
                {
                    'companies': len(row['companies'])
                    if isinstance(row.get('companies'), list)
                    else row.get('companies'),
                    'seasons': len(row['seasons'])
                    if isinstance(row.get('seasons'), list)
                    else row.get('seasons'),
                    'company_quarters': len(row['pairs'])
                    if isinstance(row.get('pairs'), list)
                    else None,
                    'checks': 1,
                    'status': 'succeeded',
                }
                for row in frame.to_dict('records')
            ]
        )
    if node == 'demo' and not frame.empty:
        frame = pd.DataFrame(
            [
                {
                    'status': 'ok' if row.get('pandas_agreement') else 'failed',
                    'checks': 1,
                    'companies': row.get('companies'),
                    'seasons': row.get('seasons'),
                    'releases': row.get('documents'),
                }
                for row in frame.to_dict('records')
            ]
        )
    if node == 'model-bakeoff' and frame.empty and not run:
        from nowcast.offline import saved_snapshot

        saved = saved_snapshot(config, 'bakeoff', MetricSnapshot)
        if saved:
            scores: dict[str, dict[str, Any]] = {}
            for point in saved.series:
                scores.setdefault(point.metric, {'model': point.metric})[point.season] = point.value
            frame = pd.DataFrame(scores.values())
    if node == 'estimate-scope' and frame.empty and not run:
        from nowcast.offline import saved_snapshot

        saved = saved_snapshot(config, 'plan', MetricSnapshot)
        if saved:
            values = {point.metric: point.value for point in saved.series}
            companies = values.get('companies')
            releases = values.get('releases')
            frame = pd.DataFrame(
                [
                    {
                        'scope_plan': {
                            **values,
                            'seasons': list(range(int(releases / companies)))
                            if companies and releases
                            else [],
                        }
                    }
                ]
            )
    panel_path = Paths.from_config(config).resolve('manifests/panel.json')
    if (
        not run
        and not node.startswith('demo-')
        and {'cik', 'report_date'}.issubset(frame.columns)
        and panel_path.is_file()
    ):
        panel = json.loads(panel_path.read_text())
        pairs = {(p['cik'], p['season']) for p in panel['pairs']}
        seasons = pd.to_datetime(frame.report_date, errors='coerce').dt.to_period('Q').astype(str)
        frame = frame[
            [
                (str(cik).zfill(10), season) in pairs
                for cik, season in zip(frame.cik, seasons, strict=True)
            ]
        ]
    if node == 'estimate-scope' and not frame.empty:
        import math

        plans = []
        for row in frame.to_dict('records'):
            plan = row.get('scope_plan')
            plan = json.loads(plan) if isinstance(plan, str) else plan
            if isinstance(plan, dict):
                plans.append({**plan, 'seasons': len(plan.get('seasons', []))})
            else:
                releases = row.get('documents', 0)
                requests = releases * max(1, len(row.get('models', [])))
                capacity = row.get('requests_per_day', 0)
                plans.append(
                    {
                        'companies': row.get('companies'),
                        'seasons': row.get('quarters'),
                        'releases': releases,
                        'base_requests': requests,
                        'model_days': math.ceil(requests / capacity) if capacity else None,
                    }
                )
        frame = pd.DataFrame(plans)
    if node == 'gate' and {'metric', 'season'}.issubset(frame):
        from nowcast.registry import load_registry

        labels = {k.id: k.label for k in load_registry(config).kpis}
        frame['metric'] = frame.metric.map(lambda value: labels.get(value, value))
        aggregate = read_frame(
            Paths.from_config(config).aggregates(config) / 'index_aggregates.parquet'
        )
        details = index_rows(config, aggregate)
        if not details.empty:
            attributes = [key for key in details if key not in frame or key in {'metric', 'season'}]
            frame = frame.merge(details[attributes], on=['metric', 'season'], how='left')
    if node in {'aggregate', 'publish', 'suppressed', 'demo-aggregate'}:
        frame = index_rows(config, frame)
    return frame


def results(config: Config) -> list[dict[str, Any]]:
    from nowcast.extraction.runner import model_slug

    paths = Paths.from_config(config)
    output: dict[str, dict[str, Any]] = {}
    for model in config.llm.models:
        for path in sorted((paths.extractions(config) / model_slug(model)).rglob('*.json')):
            raw = json.loads(path.read_text())
            if raw.get('document_id') and isinstance(raw.get('record'), dict):
                output.setdefault(raw['document_id'], raw)
    return list(output.values())


def pane(
    config: Config,
    config_path: Path,
    store: JobStore,
    node: str,
    side: Literal['input', 'output'],
    *,
    trace: bool = False,
    run: str | None = None,
    upstream: str | None = None,
    offset: int = 0,
    limit: int = 50,
    search: str = '',
    flagged: bool | None = None,
    reason: str = '',
    field: str = '',
    season: str = '',
    sample: int = 0,
    seed: int = 42,
) -> PaneResponse:
    from nowcast.artifacts import latest_upstream, upstream_stages

    definitions = canvas_registry()
    sources = {n.id: n.io.source for n in definitions.nodes}
    if node not in {n.id for n in definitions.nodes}:
        raise DataError('unknown node')
    incoming = [e.source for e in definitions.edges if e.target == node and not e.sub]
    incoming = list(
        dict.fromkeys(
            [name for name in [sources.get(node), *upstream_stages(node), *incoming] if name]
        )
    )
    execution_input = latest_upstream(store, config, node, upstream) if side == 'input' else None
    selected = node
    if side == 'input':
        selected = upstream or sources.get(node) or (incoming[0] if incoming else node)
        definition = next(item for item in definitions.nodes if item.id == node)
        if not upstream and not sources.get(node) and definition.io.takes.noun == 'settings':
            selected = 'validate-config'
            incoming = [] if node == 'validate-config' else ['validate-config']
        if not upstream and selected in upstream_stages(node) and execution_input:
            selected = execution_input[1]
            incoming = [selected, *(name for name in incoming if name != selected)]
        if upstream and upstream not in [*incoming, sources.get(node)]:
            raise DataError('invalid upstream')
    frame = frame_for(config, config_path, store, selected, run)
    if node == 'review' and side == 'input' and not run:
        frame = read_frame(Paths.from_config(config).resolve(config.extraction.review_queue_path))
    if (
        selected in {'extract', 'extract-step', 'validate', 'consolidate'}
        and frame.empty
        and not run
    ):
        frame = pd.DataFrame(
            [
                {
                    'document_id': p['document_id'],
                    'record': json.dumps(p['record']),
                    'confidence': sum(
                        v.get('confidence', 0) for v in p['record'].values() if isinstance(v, dict)
                    )
                    / max(1, sum(isinstance(v, dict) for v in p['record'].values())),
                }
                for p in results(config)
            ]
        )
    if selected == 'validate-config':
        frame = pd.DataFrame(
            [
                {
                    'field': section + '.' + key,
                    'value': json.dumps(value) if isinstance(value, (dict, list, tuple)) else value,
                }
                for section, values in dataclasses.asdict(config).items()
                if isinstance(values, dict)
                for key, value in values.items()
                if not any(word in key for word in ('secret', 'password', 'api_key'))
            ]
        )
    if node == 'validate-config' and side == 'input':
        import os

        frame = pd.DataFrame(
            [
                {'field': 'config', 'value': config_path.name},
                {'field': 'provider', 'value': bool(os.environ.get(config.llm.api_key_env))},
                {'field': 'SEC', 'value': bool(os.environ.get(config.data.sec_user_agent_env))},
            ]
        )
    if selected in {'publish', 'suppressed'} and 'suppressed' in frame:
        frame = frame[frame.suppressed.eq(selected == 'suppressed')]
    private = selected in PRIVATE_STAGES
    if not trace:
        frame = public_frame(frame, config.llm.models)
    elif private:
        if search and 'document_id' in frame:
            frame = frame[frame.document_id.astype(str).str.contains(search, regex=False)]
        queue = read_frame(Paths.from_config(config).resolve(config.extraction.review_queue_path))
        ids = set(queue.document_id) if 'document_id' in queue else set()
        if flagged is not None and 'document_id' in frame:
            frame = frame[frame.document_id.isin(ids).eq(flagged)]
        for column, value in [('reason', reason), ('field', field), ('season', season)]:
            if value and column in frame:
                frame = frame[frame[column].eq(value)]
        if reason and not queue.empty and 'document_id' in frame:
            frame = frame[frame.document_id.isin(queue.loc[queue.reason.eq(reason), 'document_id'])]
        if field and 'record' in frame:
            frame = frame[
                frame.record.map(
                    lambda x: (
                        (json.loads(x) if isinstance(x, str) else x).get(field, {}).get('value')
                        is not None
                    )
                )
            ]
        if season and 'report_date' in frame:
            frame = frame[
                pd.to_datetime(frame.report_date).dt.to_period('Q').astype(str).eq(season)
            ]
    if sample:
        frame = frame.sample(n=min(sample, len(frame)), random_state=seed)
    with store.engine.connect() as connection:
        versions = list(
            connection.execute(
                text('SELECT job_id FROM artifacts WHERE stage=:stage ORDER BY rowid DESC'),
                {'stage': selected},
            ).scalars()
        )
    if side == 'input' and upstream_stages(node):
        versions = [execution_input[0]] if execution_input else []
    profiles = []
    for field_key in frame:
        column = str(field_key)
        series = frame[field_key]
        present = series.dropna()
        kinds = set()
        for value in present:
            value = value.item() if hasattr(value, 'item') else value
            kinds.add(
                'boolean'
                if isinstance(value, bool)
                else 'number'
                if isinstance(value, (int, float))
                else 'string'
            )
        example = present.iloc[0] if len(present) else None
        if example is not None and hasattr(example, 'item'):
            example = example.item()
        if isinstance(example, (dict, list, tuple)):
            example = json.dumps(example, default=str)
        if example is not None and not isinstance(example, (str, int, float, bool)):
            example = str(example)
        profiles.append(
            FieldProfile.model_validate(
                {
                    'field': str(column),
                    'inferred_type': next(iter(kinds))
                    if len(kinds) == 1
                    else 'mixed'
                    if kinds
                    else 'null',
                    'null_rate': float(series.isna().mean()) if len(series) else None,
                    'example': example,
                }
            )
        )
    total = (
        1
        if selected == 'validate-config'
        else (
            int(frame.releases.sum())
            if selected == 'estimate-scope' and 'releases' in frame
            else len(frame)
        )
    )
    values = frame.iloc[offset : offset + limit].copy()
    for value_column in values:
        values[value_column] = values[value_column].map(
            lambda value: (
                json.dumps(value, default=str) if isinstance(value, (dict, list, tuple)) else value
            )
        )
    rows = json.loads(values.to_json(orient='records', date_format='iso'))
    return PaneResponse(
        node=node,
        profiles=profiles,
        view='trace' if private and trace else 'index',
        side=side,
        status='private' if private and not trace else 'available' if total else 'unavailable',
        total=total,
        offset=offset,
        columns=list(values.columns),
        rows=rows,
        runs=versions,
        upstream=incoming,
        config_hash=config_fingerprint(config)[:8],
        run=run,
    )


def stages(config: Config, config_path: Path, store: JobStore) -> StageSnapshot:
    latest = store.list_runs()
    sources = {n.id: n.io.source for n in canvas_registry().nodes}
    nodes = []
    cache = {}
    for node in canvas_registry().nodes:
        if node.capability == 'planned':
            nodes.append(StageState(id=node.id, status='planned'))
            continue
        files = source_files(config, config_path, node.id)
        present = any(p.is_file() for p in files)
        status = 'done' if present else 'idle'
        command = '-'.join(node.command) or node.id
        job = next(
            (r for r in latest if r.stage in {node.id, command} or r.workflow_id == node.id), None
        )
        duration = None
        if job:
            status = {
                'succeeded': 'done',
                'failed': 'error',
                'interrupted': 'attention',
                'cancelled': 'attention',
                'queued': 'running',
                'running': 'running',
            }[job.status]
            events = store.events(job.id)
            if len(events) > 1 and job.status not in {'queued', 'running'}:
                duration = max(
                    0,
                    (
                        datetime.fromisoformat(events[-1]['created_at'])
                        - datetime.fromisoformat(events[0]['created_at'])
                    ).total_seconds(),
                )
        try:
            frame = frame_for(config, config_path, store, node.id)
            out = len(frame) if present else None
        except (ValueError, OSError):
            out = None
        if node.id == 'validate-config':
            out = 1 if present and (not job or job.status == 'succeeded') else None
        if node.id == 'estimate-scope' and present:
            out = int(frame.releases.sum()) if 'releases' in frame else None
        if node.id == 'extract' and not out:
            from nowcast.extraction.runner import load_documents
            from nowcast.ingestion.rebuild import index_path
            from nowcast.scope import select_documents

            try:
                ids = {
                    d.document_id
                    for d in select_documents(config, load_documents(config, index_path(config)))
                }
                out = sum(p['document_id'] in ids for p in results(config)) or None
            except DataError:
                out = None
        cache[node.id] = out
        nodes.append(
            StageState.model_validate(
                {
                    'id': node.id,
                    'status': status,
                    'out_count': out,
                    'duration': duration,
                    'last_run': job.id if job else None,
                }
            )
        )
    report = Paths.from_config(config).resolve('manifests/ingest_report.json')
    skipped = json.loads(report.read_text()).get('skip_reasons', {}) if report.exists() else {}
    for state in nodes:
        state.in_count = cache.get(sources.get(state.id) or '')
        if state.id in {'ingest', 'download', 'discover'}:
            state.skipped_by_reason = skipped
    return StageSnapshot(nodes=nodes)


def evidence(
    config: Config, record_id: str, store: JobStore | None = None, run: str | None = None
) -> EvidenceResponse:
    from nowcast.extraction.runner import load_documents, prepare_text
    from nowcast.extraction.schema import ExtractionRecord
    from nowcast.extraction.validators import (
        NUMERIC_FIELDS,
        evidence_span,
        number_in_quote,
        validate_record,
    )
    from nowcast.ingestion.rebuild import index_path

    if (
        not run
        and not any(p['document_id'] == record_id for p in results(config))
        and Paths.from_config(config).resolve('demo/document_index.v2.parquet').is_file()
    ):
        config = demo_config(config)
    payload = next((p for p in results(config) if p['document_id'] == record_id), None)
    source = None
    report_date = None
    if run:
        if store is None:
            raise DataError('run unavailable')
        with store.engine.connect() as connection:
            artifacts = connection.execute(
                text('SELECT files FROM artifacts WHERE job_id=:run'), {'run': run}
            ).scalars()
            files = [
                item
                for value in artifacts
                for item in json.loads(value)
                if item.get('kind') == 'evidence'
            ]
        snapshot = next(
            (
                Path(item['snapshot'])
                for item in files
                if Path(item['snapshot']).is_relative_to(store.path.parent / 'runs')
            ),
            None,
        )
        if snapshot is None:
            raise DataError('evidence snapshot unavailable')
        frozen = json.loads(snapshot.read_text()).get('records', {}).get(record_id)
        if not frozen:
            raise DataError('record version unavailable')
        payload = frozen['payload']
        source = frozen['source']
        report_date = frozen['report_date']
        settings = json.loads(snapshot.read_text()).get('extraction')
        if settings:
            config = dataclasses.replace(
                config, extraction=dataclasses.replace(config.extraction, **settings)
            )
    if payload is None:
        raise DataError('record unavailable')
    if source is None:
        document = next(
            (d for d in load_documents(config, index_path(config)) if d.document_id == record_id),
            None,
        )
        if document is None:
            raise DataError('source unavailable')
        source = prepare_text(config, document).source_text
        report_date = document.report_date
    record = ExtractionRecord.model_validate(payload['record'])
    issues, _ = validate_record(
        record.model_copy(deep=True), source, config, report_date=report_date
    )
    fields = []
    for name in FIELDS:
        fact = getattr(record, name)
        quote = fact.evidence_quote or ''
        span = evidence_span(quote, source, record.fiscal_year, record.fiscal_quarter)
        start = source.lower().find(quote.lower()) if quote else -1
        number = (
            number_in_quote(
                float(fact.value),
                span.matched_text,
                unit_context=span.unit_context if name == 'revenue' else '',
                percent=name == 'revenue_yoy_growth',
            )
            if name in NUMERIC_FIELDS and fact.value is not None and span
            else None
        )
        fields.append(
            EvidenceField(
                field=name,
                value=fact.value,
                unit=record.units,
                confidence=fact.confidence,
                quote=quote or None,
                start=start if start >= 0 else None,
                end=start + len(quote) if start >= 0 else None,
                row_start=span.start if span else None,
                row_end=span.end if span else None,
                number_present=number,
                issues=[i.code for i in issues if i.field == name],
            )
        )
    path = Paths.from_config(config).resolve('inputs/labels.csv')
    verdicts = {}
    if path.exists():
        with path.open(newline='') as stream:
            verdicts = {
                r['field']: r['verdict']
                for r in csv.DictReader(stream)
                if r['record_id'] == record_id
            }
    return EvidenceResponse.model_validate(
        {
            'record_id': record_id,
            'source': source,
            'fields': [f.model_dump() for f in fields],
            'verdicts': verdicts,
        }
    )


def save_label(config: Config, request: LabelRequest) -> LabelResponse:
    if (
        not any(p['document_id'] == request.record_id for p in results(config))
        and Paths.from_config(config).resolve('demo/document_index.v2.parquet').is_file()
    ):
        config = demo_config(config)
    record = evidence(config, request.record_id)
    fact = next((f for f in record.fields if f.field == request.field), None)
    if request.field != 'record' and (fact is None or fact.value != request.value):
        raise DataError('field value changed')
    path = Paths.from_config(config).resolve('inputs/labels.csv')
    with file_lock(path):
        rows = []
        if path.exists():
            with path.open(newline='') as stream:
                rows = list(csv.DictReader(stream))
        rows = [
            r for r in rows if (r['record_id'], r['field']) != (request.record_id, request.field)
        ]
        rows.append({**request.model_dump(), 'timestamp': datetime.now(timezone.utc).isoformat()})
        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output, fieldnames=['record_id', 'field', 'value', 'verdict', 'timestamp']
        )
        writer.writeheader()
        writer.writerows(rows)
        atomic_bytes(output.getvalue().encode(), path)
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        counts.setdefault(row['field'], {'correct': 0, 'wrong': 0, 'unsure': 0})[
            row['verdict']
        ] += 1
    return LabelResponse(
        checked=len({r['record_id'] for r in rows}), total=len(results(config)), fields=counts
    )


def coverage(config: Config) -> MetricSnapshot:
    from nowcast.registry import load_registry

    paths = Paths.from_config(config)
    aggregate = read_frame(paths.aggregates(config) / 'index_aggregates.parquet')
    points = []
    if not aggregate.empty:
        latest = (
            aggregate.sort_values('as_of_date').groupby(['season_year', 'season_quarter']).tail(1)
        )
        mapping = {
            'eps_growth': 'growth',
            'revenue_growth': 'revenue_growth',
            'guidance': 'guidance',
            'tone': 'tone',
        }
        for row in latest.to_dict('records'):
            for kpi in load_registry(config).kpis:
                n = row.get('n_obs_' + mapping[kpi.id])
                den = row.get('n_expected')
                points.append(
                    ChartPoint(
                        category='coverage',
                        metric=kpi.id,
                        season=f'{row["season_year"]}Q{row["season_quarter"]}',
                        value=n / den if n is not None and den else None,
                        denominator=den,
                        status=row.get('metric_status_' + kpi.output, 'unavailable'),
                    )
                )
    queue = read_frame(paths.resolve(config.extraction.review_queue_path))
    if not queue.empty:
        for grouped in (
            queue.groupby(['field', 'reason']).size().reset_index(name='count').to_dict('records')
        ):
            field, reason, count = grouped['field'], grouped['reason'], grouped['count']
            points.append(
                ChartPoint(
                    category='reasons',
                    metric=field + ':' + reason,
                    value=int(count),
                    status='measured',
                )
            )
    from nowcast.extraction.review_queue import affected_fields
    from nowcast.extraction.runner import consolidate, load_documents
    from nowcast.ingestion.rebuild import index_path
    from nowcast.scope import select_documents

    documents = load_documents(config, index_path(config))
    eligible = {d.document_id for d in select_documents(config, documents)} if documents else set()
    usable = consolidate(config, list(config.llm.models))
    if not usable.empty:
        usable = usable[usable.document_id.isin(eligible)].drop_duplicates('document_id')
    effects: dict[str, set[str]] = {}
    for issue in queue.to_dict('records'):
        effects.setdefault(issue['document_id'], set()).update(
            affected_fields(issue['field'], issue['reason'])
        )
    for name in FIELDS:
        column = 'revenue_yoy_growth_pct' if name == 'revenue_yoy_growth' else name
        present = 0
        for record in usable.to_dict('records'):
            invalid = effects.get(record['document_id'], set())
            if (
                record.get('verification_status') == 'verified'
                and 'record' not in invalid
                and name not in invalid
                and pd.notna(record.get(column))
            ):
                present += 1
        points.append(
            ChartPoint(
                category='fields',
                metric=name,
                value=present / len(eligible) if eligible else None,
                denominator=len(eligible) or None,
                status='measured' if eligible else 'unavailable',
            )
        )
    pairs = read_frame(paths.resolve('manifests/pair_outcomes.csv'))
    if not pairs.empty:
        for grouped in (
            pairs.groupby(['season', 'outcome']).size().reset_index(name='count').to_dict('records')
        ):
            season, outcome, count = grouped['season'], grouped['outcome'], grouped['count']
            points.append(
                ChartPoint(
                    category='cohort',
                    metric=outcome,
                    season=season,
                    value=int(count),
                    status='measured',
                )
            )
    return MetricSnapshot(
        metrics={
            'gate': config.aggregation.min_constituents,
            'minimum_observations': config.aggregation.min_observations,
        },
        series=points,
    )


def cost(config: Config, store: JobStore) -> MetricSnapshot:
    paths = Paths.from_config(config)
    files = [
        paths.resolve(config.budget.ledger_path),
        *paths.manifests(config).glob('bakeoff/*/*.ledger.parquet'),
    ]
    frames = [read_frame(file) for file in files if file.is_file()]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    metrics: dict[str, float | None] = dict.fromkeys(
        [
            'p50',
            'p95',
            'prompt',
            'reasoning',
            'content',
            'cache',
            'calls',
            'retries',
            'truncations',
            '429',
            'calls_per_document',
            'xbrl_saved_calls',
        ]
    )
    if not frame.empty:
        kinds = frame.get('request_kind', pd.Series('completion', index=frame.index)).fillna(
            'completion'
        )
        completions = frame[kinds.eq('completion')]
        for target, column in [
            ('prompt', 'prompt_tokens'),
            ('reasoning', 'reasoning_tokens'),
            ('content', 'content_tokens'),
        ]:
            values = pd.to_numeric(
                completions.get(column, pd.Series(dtype=float)), errors='coerce'
            ).dropna()
            metrics[target] = float(values.sum()) if len(values) else None
        latency = pd.to_numeric(
            completions.get('latency_seconds', pd.Series(dtype=float)), errors='coerce'
        ).dropna()
        metrics['p50'] = float(latency.median()) if len(latency) else None
        metrics['p95'] = float(latency.quantile(0.95)) if len(latency) else None
        kinds = frame.get('request_kind', pd.Series('completion', index=frame.index)).fillna(
            'completion'
        )
        metrics['cache'] = int(kinds.eq('cache').sum())
        metrics['calls'] = int(kinds.eq('completion').sum())
        metrics['truncations'] = int(
            frame.get('outcome', pd.Series(dtype=str)).eq('truncated').sum()
        )
        if 'status_code' in frame:
            metrics['429'] = int(frame.status_code.eq(429).sum())
        if 'retry_number' in completions:
            retry_numbers = pd.to_numeric(completions.retry_number, errors='coerce').dropna()
            metrics['retries'] = float(retry_numbers.gt(0).sum()) if len(retry_numbers) else None
            metrics['retry_measured_attempts'] = float(len(retry_numbers))
        if 'document_id' in frame:
            known = completions[completions.document_id.notna()]
            documents = known.document_id.nunique()
            metrics['calls_per_document'] = len(known) / documents if documents else None
            metrics['document_measured_attempts'] = float(len(known))
    day = datetime.now(timezone.utc).date().isoformat()
    with store.engine.connect() as connection:
        used = connection.execute(
            text('SELECT count(*) FROM reservations WHERE scope=:scope AND utc_day=:day'),
            {'scope': config.llm.base_url, 'day': day},
        ).scalar_one()
    metrics.update(used=float(used), limit=float(config.llm.requests_per_day))
    return MetricSnapshot(metrics=metrics)


def plan(config: Config) -> MetricSnapshot:
    from nowcast.scope import scope_summary

    forecast = scope_summary(config)
    points = [
        ChartPoint(category='plan', metric=name, value=forecast.get(name), status='estimated')
        for name in ['companies', 'releases', 'base_requests', 'expected_requests', 'model_days']
    ]
    return MetricSnapshot(series=points)


def bakeoff(config: Config) -> MetricSnapshot:
    files = sorted(
        Paths.from_config(config).manifests(config).glob('bakeoff/*/scores.json'),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        return MetricSnapshot()
    raw = json.loads(files[-1].read_text())
    points = []
    for row in raw.get('models', []):
        for name in [
            'parse_success_rate',
            'empty_completion_rate',
            'latency_p95_seconds',
            'nonempty_extractions',
            'tokens',
        ]:
            value = row.get(name)
            points.append(
                ChartPoint(
                    category='bakeoff',
                    metric=row['model'],
                    season=name,
                    value=value if isinstance(value, (float, int)) else None,
                    status='measured' if isinstance(value, (float, int)) else 'unavailable',
                )
            )
    return MetricSnapshot(series=points)


def capture_evidence(config: Config) -> dict[str, Any]:
    """Freeze facts and normalized source privately, before another run can replace facts."""
    import os

    from nowcast.extraction.runner import load_documents, prepare_text
    from nowcast.ingestion.rebuild import index_path

    documents = {d.document_id: d for d in load_documents(config, index_path(config))}
    records = {}
    for payload in results(config):
        identifier = payload['document_id']
        if identifier in documents:
            document = documents[identifier]
            records[identifier] = {
                'payload': payload,
                'source': prepare_text(config, document).source_text,
                'report_date': document.report_date,
            }
    result = {
        'version': 'v1',
        'extraction': dataclasses.asdict(config.extraction),
        'records': records,
    }
    key = os.environ.get(config.llm.api_key_env, '')
    if key and key in json.dumps(result):
        raise DataError('credential in evidence refused')
    return result


def demo_config(config: Config) -> Config:
    from nowcast.config import ScopeConfig

    return dataclasses.replace(
        config,
        paths=dataclasses.replace(
            config.paths, data_dir=str(Paths.from_config(config).resolve('demo'))
        ),
        runtime=dataclasses.replace(config.runtime, data_dir_env='TRESATA_DEMO_INSPECTION_ROOT'),
        llm=dataclasses.replace(config.llm, models=('synthetic:free',)),
        scope=ScopeConfig(),
        extraction=dataclasses.replace(config.extraction, pack_phrases=()),
    )
