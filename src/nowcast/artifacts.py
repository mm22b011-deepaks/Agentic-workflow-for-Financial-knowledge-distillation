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
    }
    return choices.get(stage, [])


def fingerprint_files(files: list[Path]) -> list[dict[str, str]]:
    if not files or any(not path.is_file() for path in files):
        raise ValueError('upstream artifact is missing')
    return [
        {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in files
    ]


def record_artifacts(
    store: JobStore, job_id: str, stage: str, config: Config, config_path: Path
) -> None:
    payload = fingerprint_files(stage_files(config, config_path, stage))
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
            if fingerprint_files([Path(item['path']) for item in files]) != files:
                raise ValueError('upstream artifacts changed; run the workflow again')
