"""Durable single-workstation jobs and ordered events, stored through SQLAlchemy."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text

from nowcast.config import Config
from nowcast.contracts import RunRequest, RunStatus
from nowcast.paths import Paths
from nowcast.registry import load_registry

TERMINAL = frozenset({'succeeded', 'failed', 'cancelled', 'interrupted'})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def config_fingerprint(config: Config) -> str:
    return hashlib.sha256(
        json.dumps(
            {'config': dataclasses.asdict(config), 'registry': load_registry(config).model_dump()},
            sort_keys=True,
        ).encode()
    ).hexdigest()


def process_identity(pid: int) -> str:
    """Linux process birth time guards against PID reuse after a restart."""
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return ''


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine('sqlite:///' + str(self.path), connect_args={'timeout': 30})
        # Migration locking is per database, including across independently starting processes.
        import fcntl

        with self.path.with_suffix('.migration.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            cfg = AlembicConfig()
            cfg.set_main_option('script_location', str(Path(__file__).parent / 'migrations'))
            with self.engine.begin() as connection:
                cfg.attributes['connection'] = connection
                command.upgrade(cfg, 'head')

    @contextmanager
    def transaction(self) -> Any:
        with self.engine.connect() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(text('SELECT * FROM jobs WHERE id=:id'), {'id': job_id})
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def list_runs(self) -> list[RunStatus]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100')
            ).mappings()
            return [self.public(dict(row)) for row in rows]

    @staticmethod
    def public(row: dict[str, Any]) -> RunStatus:
        return RunStatus.model_validate(
            {name: row[name] for name in RunStatus.model_fields if name != 'version'}
        )

    def create(
        self,
        request: RunRequest,
        config: Config,
        config_path: Path,
        schedule_task: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        registry = load_registry(config)
        workflow = next((w for w in registry.workflows if w.id == request.workflow_id), None)
        if request.command_id:
            from nowcast.cli_registry import command_argv

            command_argv(request.command_id, request.parameters, config_path)
            from nowcast.workflow_registry import canvas_registry

            node = next((n for n in canvas_registry().nodes if n.id == request.command_id), None)
            if node is None or node.capability != 'executable':
                raise ValueError('command requires a terminal')
            order = [request.command_id]
            if request.command_id == 'run-all':
                from nowcast.phase_services import RUN_ALL_STAGES

                order = list(RUN_ALL_STAGES)
        elif workflow is None:
            raise ValueError('unknown workflow')
        else:
            order = registry.execution_order(workflow)
        from nowcast.artifacts import validate_upstream

        if request.command_id:
            from nowcast.artifacts import validate_command_upstream

            validate_command_upstream(self, request, config)
        if not request.command_id:
            validate_upstream(self, request, config, workflow, registry)
        if request.command_id and request.node_id and request.command_id != request.node_id:
            raise ValueError('CLI node and command must match')
        if request.node_id:
            order = [request.node_id]
        with self.transaction() as connection:
            existing = (
                connection.execute(
                    text('SELECT * FROM jobs WHERE submission_id=:key'),
                    {'key': request.submission_id},
                )
                .mappings()
                .first()
            )
            if existing:
                if existing['workflow_id'] != request.workflow_id or (
                    existing['request_json']
                    and RunRequest.model_validate_json(existing['request_json']).model_dump()
                    != request.model_dump()
                ):
                    raise ValueError('submission identifier already names a different workflow')
                return dict(existing), False
            # A workstation data directory has one writer. Concurrent submissions are rejected,
            # rather than letting parquet writers race over the same extraction artifacts.
            active = connection.execute(
                text("SELECT count(*) FROM jobs WHERE status IN ('queued','running')")
            ).scalar_one()
            if active:
                raise ValueError('another job is active for this workstation')
            job_id = uuid.uuid4().hex
            values = {
                'id': job_id,
                'submission_id': request.submission_id,
                'workflow_id': request.workflow_id,
                'status': 'queued',
                'stage': None,
                'completed': 0,
                'total': len(order),
                'cancel_requested': False,
                'created_at': utc_now(),
                'config_path': str(config_path.resolve()),
                'fingerprint': config_fingerprint(config),
                'stages': json.dumps(order),
                'pid': os.getpid(),
                'identity': process_identity(os.getpid()),
                'request_json': request.model_dump_json(),
            }
            connection.execute(
                text(
                    'INSERT INTO jobs ('
                    + ','.join(values)
                    + ') VALUES ('
                    + ','.join(':' + key for key in values)
                    + ')'
                ),
                values,
            )
            if schedule_task:
                connection.execute(
                    text(
                        "UPDATE schedule_tasks SET last_job=:job,status='running',attempts=attempts+1 WHERE task_key=:task"
                    ),
                    {'job': job_id, 'task': schedule_task},
                )
        self.event(job_id, None, 'queued')
        return values, True

    def launch(self, job_id: str) -> None:
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    '-m',
                    'nowcast.worker',
                    '--database',
                    str(self.path),
                    '--job',
                    job_id,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            self.update(job_id, status='failed')
            self.event(job_id, None, 'worker_start_failed')
            raise
        self.update(job_id, pid=process.pid, identity=process_identity(process.pid))

    def event(self, job_id: str, stage: str | None, kind: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    'INSERT INTO events (job_id,stage,kind,created_at) VALUES (:id,:stage,:kind,:time)'
                ),
                {'id': job_id, 'stage': stage, 'kind': kind, 'time': utc_now()},
            )

    def events(self, job_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    'SELECT sequence,job_id,stage,kind,created_at FROM events WHERE job_id=:id AND sequence>:after ORDER BY sequence LIMIT 1000'
                ),
                {'id': job_id, 'after': after},
            ).mappings()
            return [dict(row) for row in rows]

    def cancel(self, job_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE jobs SET cancel_requested=1 WHERE id=:id AND status IN ('queued','running')"
                ),
                {'id': job_id},
            )

    def reconcile(self) -> None:
        with self.engine.connect() as connection:
            rows = list(
                connection.execute(
                    text("SELECT id,pid,identity FROM jobs WHERE status IN ('queued','running')")
                ).mappings()
            )
        for row in rows:
            if not row['pid'] or process_identity(row['pid']) != row['identity']:
                self.update(row['id'], status='interrupted')
                self.event(row['id'], None, 'interrupted')

    def update(self, job_id: str, **values: Any) -> None:
        if not values or set(values) - {
            'status',
            'stage',
            'completed',
            'pid',
            'identity',
            'cancel_requested',
        }:
            raise ValueError('unsupported job update')
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    'UPDATE jobs SET '
                    + ','.join(key + '=:' + key for key in values)
                    + ' WHERE id=:job_id'
                ),
                {**values, 'job_id': job_id},
            )

    def claim(self, job_id: str) -> bool:
        pid = os.getpid()
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE jobs SET status='running',pid=:pid,identity=:identity WHERE id=:id AND status='queued'"
                ),
                {'pid': pid, 'identity': process_identity(pid), 'id': job_id},
            )
            return bool(result.rowcount)

    def resume(self, job_id: str, config: Config) -> None:
        with self.transaction() as connection:
            row = (
                connection.execute(text('SELECT * FROM jobs WHERE id=:id'), {'id': job_id})
                .mappings()
                .first()
            )
            if not row or row['status'] not in {'interrupted', 'failed', 'cancelled'}:
                raise ValueError('only interrupted, failed or cancelled jobs can resume')
            if row['fingerprint'] != config_fingerprint(config):
                raise ValueError('configuration fingerprint changed; create a new run')
            active = connection.execute(
                text("SELECT count(*) FROM jobs WHERE status IN ('queued','running')")
            ).scalar_one()
            if active:
                raise ValueError('another job is active')
            connection.execute(
                text(
                    "UPDATE jobs SET status='queued',cancel_requested=0,pid=:pid,identity=:identity,completed=0 WHERE id=:id"
                ),
                {'id': job_id, 'pid': os.getpid(), 'identity': process_identity(os.getpid())},
            )
        self.event(job_id, None, 'resumed')


def store_for(config: Config) -> JobStore:
    return JobStore(Paths.from_config(config).resolve('jobs.sqlite3'))


class JobCancelled(Exception):
    pass


def check_cancelled() -> None:
    """Workers check cancellation between items; ordinary CLI runs have no job overhead."""
    path, job_id = os.environ.get('NOWCAST_JOB_DATABASE'), os.environ.get('NOWCAST_JOB_ID')
    if path and job_id:
        store = JobStore.__new__(JobStore)
        store.engine = create_engine('sqlite:///' + path)
        try:
            row = store.get(job_id)
            if row and row['cancel_requested']:
                raise JobCancelled()
        finally:
            store.engine.dispose()
