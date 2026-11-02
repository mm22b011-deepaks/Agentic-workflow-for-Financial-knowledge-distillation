"""Fixed point-in-time panels and a shared request-budget forecast."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import math
import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nowcast.extraction.runner import Document

import pandas as pd

from nowcast.config import Config
from nowcast.errors import DataError
from nowcast.paths import Paths
from nowcast.storage import atomic_json, file_lock

LOGGER = logging.getLogger(__name__)
PRESETS = {'small': (20, 4), 'standard': (40, 4), 'large': (100, 4)}


def dimensions(config: Config) -> tuple[int, int]:
    return PRESETS.get(config.scope.profile, (config.scope.companies, config.scope.seasons))


def completed_seasons(count: int, now: datetime | None = None) -> list[str]:
    moment = now or datetime.now(timezone.utc)
    current = pd.Period(moment.date(), freq='Q')
    return [str(period) for period in pd.period_range(current - count, current - 1, freq='Q')]


def daily_capacity(config: Config) -> int:
    return max(
        0,
        math.floor(config.llm.requests_per_day * (1 - config.scheduler.safety_margin))
        - config.scheduler.retry_reserve,
    )


def scope_summary(config: Config, now: datetime | None = None) -> dict[str, Any]:
    companies, seasons = dimensions(config)
    releases = companies * seasons
    capacity = daily_capacity(config)
    days = (
        math.ceil((releases + config.scheduler.bakeoff_requests) / capacity)
        if capacity and releases
        else None
    )
    reserve = config.scheduler.retry_reserve * days if days is not None else None
    return {
        'version': 'v1',
        'profile': config.scope.profile,
        'companies': companies,
        'seasons': completed_seasons(seasons, now) if seasons else [],
        'seed': config.scope.seed,
        'releases': releases or None,
        'base_requests': releases or None,
        'bakeoff_requests': config.scheduler.bakeoff_requests,
        'retry_reserve': reserve,
        'expected_requests': releases + config.scheduler.bakeoff_requests + reserve
        if reserve is not None
        else None,
        'daily_capacity': capacity,
        'daily_limit': config.llm.requests_per_day,
        'model_days': days,
        'allowance_status': 'unverified',
    }


def _freeze_scope(
    config: Config, frame: pd.DataFrame, now: datetime | None = None
) -> dict[str, Any]:
    """Refuse changed specifications and universe inputs rather than silently redraw."""
    companies, count = dimensions(config)
    if companies < 1 or count < 1:
        raise DataError('a frozen panel needs positive scope.companies and scope.seasons')
    seasons = completed_seasons(count, now)
    canonical = (
        frame[['ticker', 'cik', 'effective_from', 'effective_to']]
        .sort_values(['cik', 'effective_from'])
        .to_json(orient='records', date_format='iso')
    )
    universe_hash = hashlib.sha256(canonical.encode()).hexdigest()
    spec = {
        'companies': companies,
        'seasons': seasons,
        'seed': config.scope.seed,
        'universe_hash': universe_hash,
    }
    signature = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    target = Paths.from_config(config).resolve('manifests/panel.json')
    if target.exists():
        body = json.loads(target.read_text())
        if body.get('signature') != signature:
            raise DataError(
                'frozen panel differs; preserve/archive it and explicitly choose a new data root or panel before changing scope'
            )
        check = {key: value for key, value in body.items() if key != 'hash'}
        if hashlib.sha256(json.dumps(check, sort_keys=True).encode()).hexdigest() != body.get(
            'hash'
        ):
            raise DataError('frozen panel hash mismatch')
        return body
    valid = frame.cik.astype(str).str.fullmatch(r'[0-9]{10}') & frame.cik.ne('0000000000')
    eligible: set[str] | None = None
    for label in seasons:
        period = pd.Period(label, freq='Q')
        overlap = frame[
            valid
            & (pd.to_datetime(frame.effective_from) <= period.end_time)
            & (
                pd.to_datetime(frame.effective_to).isna()
                | (pd.to_datetime(frame.effective_to) >= period.start_time)
            )
        ]
        present = set(overlap.cik.astype(str))
        eligible = present if eligible is None else eligible & present
    candidates = sorted(eligible or set())
    if len(candidates) < companies:
        raise DataError(
            f'scope needs {companies} companies in every season; only {len(candidates)} eligible'
        )
    chosen = sorted(random.Random(config.scope.seed).sample(candidates, companies))
    body = {
        'version': 'v1',
        'signature': signature,
        'spec': spec,
        'companies': chosen,
        'seasons': seasons,
        'pairs': [
            {'cik': cik, 'season': season, 'outcome': 'unvisited'}
            for season in seasons
            for cik in chosen
        ],
        'unmapped_intervals': int((~valid).sum()),
    }
    body['hash'] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(body, target)
    return body


def scoped_membership(
    config: Config, frame: pd.DataFrame, now: datetime | None = None
) -> tuple[Config, pd.DataFrame]:
    companies, count = dimensions(config)
    if not companies and not count:
        return config, frame
    panel = freeze_scope(config, frame, now)
    first, last = (
        pd.Period(panel['seasons'][0], freq='Q'),
        pd.Period(panel['seasons'][-1], freq='Q'),
    )
    local = dataclasses.replace(
        config,
        data=dataclasses.replace(
            config.data, start_date=str(first.start_time.date()), end_date=str(last.end_time.date())
        ),
        universe=dataclasses.replace(config.universe, subset_n=0),
    )
    return local, frame[frame.cik.isin(panel['companies'])].copy()


def freeze_scope(
    config: Config, frame: pd.DataFrame, now: datetime | None = None
) -> dict[str, Any]:
    target = Paths.from_config(config).resolve('manifests/panel.json')
    with file_lock(target):
        panel = _freeze_scope(config, frame, now)
    if len(panel['companies']) < config.aggregation.min_observations:
        for label in panel['seasons']:
            LOGGER.warning(
                'scope observations %s: %d < %d',
                label,
                len(panel['companies']),
                config.aggregation.min_observations,
            )
    return panel


def select_documents(config: Config, documents: list[Document]) -> list[Document]:
    if not any(dimensions(config)):
        return documents
    from nowcast.extraction.selection import season_of_date
    from nowcast.ingestion.constituents import load_constituents

    members = load_constituents(Paths.from_config(config).resolve(config.data.constituents_csv))
    panel = freeze_scope(config, members)
    pairs = {(row['cik'], row['season']) for row in panel['pairs']}
    return [
        doc
        for doc in documents
        if (str(doc.cik).zfill(10), season_of_date(doc.report_date)) in pairs
    ]
