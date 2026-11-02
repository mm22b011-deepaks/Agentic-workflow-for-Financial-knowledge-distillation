"""The published knowledge base is a closed, identifier-free projection of KPIs."""

from __future__ import annotations

import hashlib
import math

from nowcast.config import Config
from nowcast.contracts import KPIKnowledgeBase, KPIObservation
from nowcast.inspection import read_frame
from nowcast.jobs import config_fingerprint
from nowcast.paths import Paths
from nowcast.registry import load_registry
from nowcast.storage import atomic_json


def knowledge_base(config: Config, write: bool = False) -> KPIKnowledgeBase:
    path = Paths.from_config(config).aggregates(config) / 'index_aggregates.parquet'
    frame = read_frame(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ''
    rows = []
    counts = {
        'eps_growth': 'growth',
        'revenue_growth': 'revenue_growth',
        'guidance': 'guidance',
        'tone': 'tone',
    }

    def number(value: object) -> float | None:
        return float(value) if isinstance(value, (float, int)) and math.isfinite(value) else None

    for row in frame.to_dict('records'):
        for kpi in load_registry(config).kpis:
            status = row.get('metric_status_' + kpi.output, 'unavailable')
            if row.get('suppressed'):
                status = 'suppressed'
            n = number(row.get('n_obs_' + counts[kpi.id]))
            expected = number(row.get('n_expected'))
            rows.append(
                KPIObservation.model_validate(
                    {
                        'metric': kpi.id,
                        'season': f'{int(row["season_year"])}Q{int(row["season_quarter"])}',
                        'as_of': str(row['as_of_date'])[:10],
                        'value': number(row.get(kpi.output)) if status == 'ok' else None,
                        'unit': kpi.unit,
                        'n_obs': int(n) if n is not None else None,
                        'n_expected': int(expected) if expected is not None else None,
                        'coverage': n / expected if n is not None and expected else None,
                        'status': status,
                        'source_hash': digest,
                        'config_hash': config_fingerprint(config),
                    }
                )
            )
    result = KPIKnowledgeBase(records=rows)
    if write:
        atomic_json(
            result.model_dump(mode='json'), Paths.from_config(config).resolve('exports/kpis.json')
        )
    return result
