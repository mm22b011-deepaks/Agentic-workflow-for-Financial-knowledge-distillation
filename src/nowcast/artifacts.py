"""Fingerprint only known server-owned artifacts for inspector execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from nowcast.config import Config
from nowcast.jobs import JobStore, config_fingerprint, utc_now
from nowcast.paths import Paths

COMPLETION_ACTIONS = {
    'supersede-stale',
    'schedule-plan',
    'schedule-status',
    'schedule-pause',
    'schedule-resume',
}


def stage_files(config: Config, config_path: Path, stage: str) -> list[Path]:
    paths = Paths.from_config(config)
    choices = {
        'validate-config': [config_path],
        'build-constituents': [paths.resolve(config.data.constituents_csv)],
        'ingest': [paths.resolve(config.data.document_index)],
        'rebuild-index': [paths.resolve(config.data.document_index)],
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
    choices.update(
        {
            action: [paths.resolve('manifests/actions/' + action + '.json')]
            for action in COMPLETION_ACTIONS
        }
    )
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
    from nowcast.storage import atomic_bytes, atomic_json

    files = stage_files(config, config_path, stage)
    if stage in COMPLETION_ACTIONS:
        # These actions finish without a data file; the worker calls us only after success.
        atomic_json({'status': 'succeeded', 'completed_at': utc_now(), 'checks': 1}, files[0])
    payload = fingerprint_files(files)

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


def upstream_stages(command: str) -> tuple[str, ...]:
    """Combined and detailed nodes can produce equivalent inputs."""
    from nowcast.inspection import UPSTREAM

    alternatives = {
        'parse': ('download', 'ingest', 'rebuild-index'),
        'extract': ('parse', 'download', 'ingest', 'rebuild-index'),
        'extract-step': ('parse', 'download', 'ingest', 'rebuild-index'),
        'aggregate': ('consolidate', 'extract'),
    }
    primary = UPSTREAM.get(command)
    return alternatives.get(command, (primary,) if primary else ())


def _artifact_matches(files: str) -> bool:
    entries = json.loads(files)
    try:
        return fingerprint_files([Path(item['path']) for item in entries]) == [
            {'path': item['path'], 'sha256': item['sha256']} for item in entries
        ]
    except (OSError, ValueError):
        return False


def latest_upstream(
    store: JobStore, config: Config, command: str, source: str | None = None
) -> tuple[str, str] | None:
    candidates = upstream_stages(command)
    if not candidates:
        return None
    if source in candidates:
        candidates = (source,)
    with store.engine.connect() as connection:
        rows = connection.execute(
            text('SELECT job_id,stage,files,config_fingerprint FROM artifacts ORDER BY rowid DESC')
        ).mappings()
        for row in rows:
            if (
                row['stage'] in candidates
                and row['config_fingerprint'] == config_fingerprint(config)
                and _artifact_matches(row['files'])
            ):
                return row['job_id'], row['stage']
    return None


def validate_command_upstream(store: JobStore, request: Any, config: Config) -> None:
    """Recheck equivalent upstream artifacts at submission and under the worker lock."""
    if not request.node_id:
        return
    candidates = upstream_stages(request.command_id)
    if not candidates:
        return
    if not request.upstream_run_id:
        raise ValueError('inspector requires a validated upstream run')
    with store.engine.connect() as connection:
        rows = list(
            connection.execute(
                text(
                    'SELECT stage,config_fingerprint,files FROM artifacts WHERE job_id=:run ORDER BY rowid DESC'
                ),
                {'run': request.upstream_run_id},
            ).mappings()
        )
    rows = [
        row
        for row in rows
        if row['stage'] in candidates and row['config_fingerprint'] == config_fingerprint(config)
    ]
    if not rows:
        raise ValueError('upstream fingerprint is missing or stale')
    if not any(_artifact_matches(row['files']) for row in rows):
        raise ValueError('upstream artifacts changed')
