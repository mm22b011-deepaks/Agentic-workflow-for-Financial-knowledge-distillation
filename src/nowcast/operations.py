"""Small CLI services shared by standalone commands, workers and scheduling."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from nowcast.config import Config
from nowcast.contracts import IndexSnapshot
from nowcast.errors import DataError
from nowcast.paths import Paths
from nowcast.storage import atomic_json


def contact_ready(value: str) -> bool:
    match = re.fullmatch(r'.+\s+([^\s@]+@[^\s@]+\.[^\s@]+)', value.strip())
    return bool(
        match
        and match[1].split('@')[-1].lower()
        not in {'example.com', 'example.invalid', 'example.org', 'yourdomain.com'}
    )


def doctor(config: Config) -> dict[str, Any]:
    from sqlalchemy import text

    from nowcast.jobs import store_for
    from nowcast.setup_wizard import metadata

    paths = Paths.from_config(config)
    key = os.environ.get(config.llm.api_key_env, '')
    proof = paths.resolve('manifests/setup.json')
    verified = json.loads(proof.read_text()) if proof.exists() else {}
    active = metadata(key)
    checked = bool(
        key
        and active['sha8'] == verified.get('sha8')
        and verified.get('verification', {}).get('authenticated')
    )
    day = datetime.now(timezone.utc).date().isoformat()
    store = store_for(config)
    with store.engine.connect() as connection:
        used = connection.execute(
            text('SELECT count(*) FROM reservations WHERE scope=:scope AND utc_day=:day'),
            {'scope': config.llm.base_url, 'day': day},
        ).scalar_one()
    location = paths.root
    while not location.exists():
        location = location.parent
    return {
        'version': 'v1',
        'key': {'present': bool(key), 'verified': checked, **active},
        'sec_contact': contact_ready(os.environ.get(config.data.sec_user_agent_env, '')),
        'free_only': all(model.endswith(':free') for model in config.llm.models),
        'offline': config.llm.offline,
        'disk_free': shutil.disk_usage(location).free,
        'utc_day': day,
        'requests_used': used,
        'configured_limit': config.llm.requests_per_day,
        'quota_left': max(0, config.llm.requests_per_day - used),
        'pending_human': ['labels-30', 'spot-check-5', 'nda'],
        'model_gate': 'pending human',
    }


def export_index(config: Config) -> dict[str, Any]:
    paths = Paths.from_config(config)
    source = paths.aggregates(config) / 'index_aggregates.parquet'
    if source.is_file():
        frame = pd.read_parquet(source)
        snapshot = IndexSnapshot(
            snapshots=json.loads(frame.to_json(orient='records', date_format='iso'))
        )
    else:
        snapshot = IndexSnapshot(status='unavailable', snapshots=[])
    result = snapshot.model_dump(mode='json')
    atomic_json(result, paths.resolve('exports/index.json'))
    return {'rows': len(snapshot.snapshots), 'status': snapshot.status}


def prepare_labels(config: Config) -> dict[str, Any]:
    from nowcast.extraction.runner import consolidate

    paths = Paths.from_config(config)
    target = paths.resolve('inputs/label-sheet.json')
    if target.exists():
        return {
            'prepared': len(json.loads(target.read_text()).get('records', [])),
            'preserved': True,
        }
    frame = consolidate(config, list(config.llm.models))
    if not frame.empty:
        panel = paths.resolve('manifests/panel.json')
        if panel.exists():
            frame = frame[
                frame.cik.astype(str).str.zfill(10).isin(json.loads(panel.read_text())['companies'])
            ]
        frame = frame.sample(n=min(30, len(frame)), random_state=config.scope.seed)
    rows = json.loads(frame.to_json(orient='records', date_format='iso')) if not frame.empty else []
    atomic_json({'version': 'v1', 'seed': config.scope.seed, 'target': 30, 'records': rows}, target)
    return {'prepared': len(rows), 'target': 30, 'scored': 0}


def execute(name: str, config: Config, args: argparse.Namespace) -> int:
    paths = Paths.from_config(config)
    result: dict[str, Any] = {}
    if name == 'doctor':
        result = doctor(config)
    elif name == 'freeze-panel':
        from nowcast.ingestion.constituents import load_constituents
        from nowcast.scope import freeze_scope

        panel = freeze_scope(config, load_constituents(paths.resolve(config.data.constituents_csv)))
        result = {
            'companies': len(panel['companies']),
            'pairs': len(panel['pairs']),
            'hash': panel['hash'],
        }
    elif name == 'validate-index':
        from nowcast.ingestion.doc_index import load_index
        from nowcast.ingestion.rebuild import (
            index_path,
            validate_index_contents,
            validate_index_rows,
        )

        source = getattr(args, 'source', None) or index_path(config)
        from pathlib import Path

        source = Path(source)
        if not source.is_file():
            raise DataError('index file not found')
        frame = load_index(source)
        problems = validate_index_rows(frame, config) + validate_index_contents(frame, config)
        print(f'{len(frame)} rows checked; {len(problems)} failures')
        return int(bool(problems))
    elif name == 'supersede-stale':
        from nowcast.extraction.runner import supersede_stale

        result = {'superseded': len(supersede_stale(config, list(config.llm.models)))}
    elif name == 'demo':
        from nowcast.verification import synthetic_demo

        result = synthetic_demo(config, paths.resolve('demo'))
    elif name == 'serve':
        import uvicorn

        from nowcast.api import create_app

        uvicorn.run(create_app(args.config), host='0.0.0.0', port=args.port, access_log=False)
        return 0
    elif name == 'export':
        result = export_index(config)
    elif name == 'prepare-labels':
        result = prepare_labels(config)
    elif name in {'quality-summary', 'report'}:
        from nowcast.extraction.review_queue import load_queue

        queue = load_queue(paths.resolve(config.extraction.review_queue_path))
        result = {
            'version': 'v1',
            'review_records': int(queue.document_id.nunique()) if not queue.empty else 0,
            'gate_r0': 'failed',
            'human_labels': 'pending',
        }
        if name == 'report':
            from nowcast.storage import atomic_bytes

            atomic_bytes(
                ('# Quality\n\n' + json.dumps(result, indent=2) + '\n').encode(),
                paths.resolve(config.reporting.report_path),
            )
    else:
        raise DataError('unsupported operation')
    atomic_json(result, paths.resolve('manifests/' + name + '.json'))
    print(json.dumps(result, sort_keys=True))
    return 0
