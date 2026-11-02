"""Generate private deterministic browser fixtures; never copy production documents."""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import yaml
from _bootstrap import ROOT

from nowcast.config import load_config
from nowcast.extraction.runner import model_slug
from nowcast.extraction.schema import ExtractionRecord, NumField
from nowcast.parsing.html import html_to_text
from nowcast.storage import atomic_json, atomic_parquet


def main() -> None:
    root = ROOT / 'data/ui-verification/canvas'
    root.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load((ROOT / 'configs/config.yaml').read_text())
    data['paths']['project_dir'] = str(ROOT)
    data['scope'] = {'profile': 'custom', 'companies': 0, 'seasons': 0, 'seed': 42}
    data['llm']['offline'] = True
    path = root / 'config.yaml'
    path.write_text(yaml.safe_dump(data))
    config = load_config(path, local=False)
    records = []
    for index in range(3):
        identifier = f'UIR{index + 1}'
        raw = root / f'raw/{identifier}.htm'
        raw.parent.mkdir(exist_ok=True)
        raw.write_text(
            '<table><tr><th>Metric</th><th>2025</th></tr><tr><td>EPS</td><td>1.20</td></tr><tr><td>Other</td><td>9.90</td></tr></table>'
        )
        quote = next(line for line in html_to_text(raw.read_text()).splitlines() if 'EPS' in line)
        record = ExtractionRecord(
            schema_version='v1',
            document_id=identifier,
            fiscal_year=2025,
            fiscal_quarter=1,
            reported_eps=NumField(
                value=9.9 if index == 0 else 1.2, evidence_quote=quote, confidence=0.9
            ),
        )
        folder = root / 'extractions' / model_slug(config.llm.models[0])
        folder.mkdir(parents=True, exist_ok=True)
        atomic_json(
            {
                'document_id': identifier,
                'model': config.llm.models[0],
                'record': record.model_dump(),
            },
            folder / f'{identifier}.json',
        )
        records.append(
            {
                'document_id': identifier,
                'cik': f'{index + 1:010d}',
                'report_date': '2025-04-10',
                'document_type': 'EX-99.1',
                'source': 'local',
                'raw_path': f'raw/{identifier}.htm',
                'sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
                'chars': len(raw.read_text()),
                'items': '2.02',
                'downloaded_at': '2025-04-10',
            }
        )
    atomic_parquet(pd.DataFrame(records), root / config.data.document_index)
    folder = root / 'aggregates'
    folder.mkdir(exist_ok=True)
    atomic_parquet(
        pd.DataFrame(
            [
                {
                    'season_year': 2025,
                    'season_quarter': 1,
                    'as_of_date': '2025-04-10',
                    'n_reported': 3,
                    'n_expected': 3,
                    'n_planned': 3,
                    'n_attempted': 3,
                    'execution_complete': True,
                    'n_obs_growth': 3,
                    'eps_growth_agg': 12.0,
                    'metric_status_eps_growth_agg': 'ok',
                    'suppressed': False,
                }
            ]
        ),
        folder / 'index_aggregates.parquet',
    )
    (root / 'universe').mkdir(exist_ok=True)
    pd.DataFrame(
        [
            {
                'cik': f'{i + 1:010d}',
                'ticker': f'UIT{i + 1}',
                'effective_from': '2024-01-01',
                'effective_to': '',
            }
            for i in range(3)
        ]
    ).to_csv(root / 'universe/constituents.csv', index=False)
    manifest = root / 'manifests'
    manifest.mkdir(exist_ok=True)
    atomic_json({'source': 'synthetic'}, manifest / 'source.json')
    print(
        json.dumps({'documents': 3, 'source': 'synthetic', 'root': 'data/ui-verification/canvas'})
    )


if __name__ == '__main__':
    main()
