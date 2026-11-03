"""Validated public snapshots for the separately selected offline data profile."""

from __future__ import annotations

import json
from typing import TypeVar

from nowcast.config import Config
from nowcast.contracts import Contract
from nowcast.paths import Paths

SNAPSHOTS = ('stages', 'coverage', 'cost', 'bakeoff', 'plan', 'schedule')
PUBLIC_FILES = (
    'config.yaml',
    'manifest.json',
    'aggregates/index_aggregates.parquet',
    'exports/index.json',
    'exports/kpis.json',
    *(f'snapshots/{name}.json' for name in SNAPSHOTS),
)
T = TypeVar('T', bound=Contract)


def saved_snapshot(config: Config, name: str, model: type[T]) -> T | None:
    if name not in (*SNAPSHOTS, 'index', 'kpis'):
        raise ValueError('unknown public snapshot')
    if not config.llm.offline:
        return None
    root = Paths.from_config(config).root
    manifest = root / 'manifest.json'
    if (
        not manifest.is_file()
        or json.loads(manifest.read_text()).get('kind') != 'public-offline-snapshot'
    ):
        return None
    folder = 'exports' if name in {'index', 'kpis'} else 'snapshots'
    path = root / folder / f'{name}.json'
    return model.model_validate_json(path.read_text()) if path.is_file() else None
