"""Fingerprint only known server-owned artifacts for inspector execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from nowcast.config import Config
from nowcast.jobs import JobStore, config_fingerprint
from nowcast.paths import Paths


def stage_files(config: Config, config_path: Path, stage: str) -> list[Path]:
    paths = Paths.from_config(config)
    choices = {
        'validate-config': [config_path],
        'build-constituents': [paths.resolve(config.data.constituents_csv)],
        'ingest': [paths.resolve(config.data.document_index)],
        'extract': [paths.extractions(config) / 'extractions.parquet'],
        'aggregate': [paths.aggregates(config) / 'index_aggregates.parquet'],
        'demo': [paths.resolve('demo/verification.json')],
        'freeze-panel': [paths.resolve('manifests/panel.json')],
        'validate-index': [paths.resolve(config.data.document_index)],
        'estimate-scope': [paths.resolve('manifests/estimate-scope.json')],
        'doctor': [paths.resolve('manifests/doctor.json')],
        'export': [paths.resolve('exports/index.json'), paths.resolve('exports/kpis.json')],
        'run-all': [
            paths.aggregates(config) / 'index_aggregates.parquet',
            paths.resolve('exports/kpis.json'),
        ],
        'prepare-labels': [paths.resolve('inputs/label-sheet.json')],
        'quality-summary': [paths.resolve('manifests/quality-summary.json')],
        'report': [paths.resolve(config.reporting.report_path)],
        'model-bakeoff': sorted(
            paths.manifests(config).glob('bakeoff/*/scores.json'),
            key=lambda path: path.stat().st_mtime,
        )[-1:],
    }
    from nowcast.phase_services import PHASES, phase_path

    if stage in PHASES:
        return [phase_path(config, stage)]
    return choices.get(stage, [])


def fingerprint_files(files: list[Path]) -> list[dict[str, str]]:
    if not files or any(not path.is_file() for path in files):
        raise ValueError('upstream artifact is missing')
    return [
        {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in files
    ]


def record_artifacts(
    store: JobStore,
    job_id: str,
    stage: str,
    config: Config,
    config_path: Path,
    parameters: dict[str, Any] | None = None,
) -> None:
    payload = fingerprint_files(stage_files(config, config_path, stage))
    from nowcast.storage import atomic_bytes

    for index, item in enumerate(payload):
        snapshot = (
            store.path.parent
            / 'runs'
            / job_id
            / stage
            / (str(index) + '-' + Path(item['path']).name)
        )
        atomic_bytes(Path(item['path']).read_bytes(), snapshot)
        item['snapshot'] = str(snapshot)
    if stage in {'extract', 'validate'}:
        from nowcast.inspection import capture_evidence
        from nowcast.storage import atomic_json

        snapshot = store.path.parent / 'runs' / job_id / stage / 'evidence.json'
        context = config
        if parameters and parameters.get('set'):
            from nowcast.config import load_config

            context = load_config(
                config_path, overrides=dict(part.split('=', 1) for part in parameters['set'])
            )
        atomic_json(capture_evidence(context), snapshot)
        payload.append(
            {
                'path': str(snapshot),
                'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                'snapshot': str(snapshot),
                'kind': 'evidence',
            }
        )
    with store.engine.begin() as connection:
        connection.execute(
            text(
                'INSERT INTO artifacts(job_id,stage,config_fingerprint,files) VALUES (:id,:stage,:fingerprint,:files) ON CONFLICT(job_id,stage) DO UPDATE SET config_fingerprint=:fingerprint,files=:files'
            ),
            {
                'id': job_id,
                'stage': stage,
                'fingerprint': config_fingerprint(config),
                'files': json.dumps(payload),
            },
        )


def validate_upstream(
    store: JobStore, request: Any, config: Config, workflow: Any, registry: Any
) -> None:
    if not request.node_id:
        return
    node = next((n for n in registry.nodes if n.id == request.node_id), None)
    if node is None or request.node_id not in workflow.nodes or node.capability != 'executable':
        raise ValueError('inspector node is not executable in this workflow')
    upstream = [left for left, right in workflow.edges if right == request.node_id]
    if not upstream:
        return
    if not request.upstream_run_id:
        raise ValueError('inspector requires a run containing validated upstream artifacts')
    with store.engine.connect() as connection:
        for stage in upstream:
            row = (
                connection.execute(
                    text(
                        'SELECT config_fingerprint,files FROM artifacts WHERE job_id=:id AND stage=:stage'
                    ),
                    {'id': request.upstream_run_id, 'stage': stage},
                )
                .mappings()
                .first()
            )
            if not row or row['config_fingerprint'] != config_fingerprint(config):
                raise ValueError('upstream fingerprint is missing or stale')
            files = json.loads(row['files'])
            original = [{'path': item['path'], 'sha256': item['sha256']} for item in files]
            if fingerprint_files([Path(item['path']) for item in files]) != original:
                raise ValueError('upstream artifacts changed; run the workflow again')


def validate_command_upstream(store: JobStore, request: Any, config: Config) -> None:
    """An inspector step consumes one known, unchanged server-owned artifact version."""
    if not request.node_id:
        return
    from nowcast.inspection import UPSTREAM

    stage = UPSTREAM.get(request.command_id)
    if not stage:
        return
    if not request.upstream_run_id:
        raise ValueError('inspector requires a validated upstream run')
    with store.engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    'SELECT config_fingerprint,files FROM artifacts WHERE job_id=:run AND stage=:stage'
                ),
                {'run': request.upstream_run_id, 'stage': stage},
            )
            .mappings()
            .first()
        )
    if row is None or row['config_fingerprint'] != config_fingerprint(config):
        raise ValueError('upstream fingerprint is missing or stale')
    files = json.loads(row['files'])
    if fingerprint_files([Path(item['path']) for item in files]) != [
        {'path': item['path'], 'sha256': item['sha256']} for item in files
    ]:
        raise ValueError('upstream artifacts changed')
