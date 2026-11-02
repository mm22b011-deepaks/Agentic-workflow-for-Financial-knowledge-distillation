"""Quota-aware planning metadata; actual work uses the existing jobs and workers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from nowcast.config import Config
from nowcast.contracts import RunRequest
from nowcast.errors import DataError
from nowcast.jobs import JobStore, store_for
from nowcast.paths import Paths
from nowcast.scope import daily_capacity, scope_summary
from nowcast.storage import atomic_bytes, atomic_json, file_lock

DAY_ZERO = [
    ('doctor', 'doctor', []),
    ('members', 'build-constituents', ['doctor']),
    ('panel', 'freeze-panel', ['members']),
    ('ingest', 'ingest', ['panel']),
    ('index', 'validate-index', ['ingest']),
    ('xbrl', '', ['index']),
    ('estimate', 'estimate-scope', ['index']),
]


class Scheduler:
    def __init__(
        self,
        config: Config,
        config_path: Path,
        clock: Callable[[], float] = time.time,
        execute: Callable[[JobStore, str], None] | None = None,
    ):
        self.config = config
        self.config_path = config_path.resolve()
        self.store = store_for(config)
        self.clock = clock
        self.execute = execute

    def state(self, key: str, default: Any = None) -> Any:
        with self.store.engine.connect() as connection:
            value = connection.execute(
                text('SELECT value FROM schedule_state WHERE key=:key'), {'key': key}
            ).scalar_one_or_none()
        return json.loads(value) if value is not None else default

    def set_state(self, key: str, value: Any) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                text(
                    'INSERT INTO schedule_state(key,value) VALUES (:key,:value) ON CONFLICT(key) DO UPDATE SET value=:value'
                ),
                {'key': key, 'value': json.dumps(value)},
            )

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    def used(self, day: str | None = None) -> int:
        with self.store.engine.connect() as connection:
            return int(
                connection.execute(
                    text('SELECT count(*) FROM reservations WHERE scope=:scope AND utc_day=:day'),
                    {
                        'scope': self.config.llm.base_url,
                        'day': day or self.now().date().isoformat(),
                    },
                ).scalar_one()
            )

    def total_reservations(self) -> int:
        with self.store.engine.connect() as connection:
            return int(
                connection.execute(
                    text('SELECT count(*) FROM reservations WHERE scope=:scope'),
                    {'scope': self.config.llm.base_url},
                ).scalar_one()
            )

    def ensure_plan(self) -> None:
        start = self.now().date()
        rows = []
        for key, command, deps in DAY_ZERO:
            rows.append((key, command, deps, 0, 0, False))
        rows.extend(
            [
                (
                    'bakeoff',
                    'model-bakeoff',
                    ['estimate'],
                    1,
                    self.config.scheduler.bakeoff_requests,
                    False,
                ),
                (
                    'extract',
                    'extract',
                    ['bakeoff'],
                    1,
                    scope_summary(self.config, now=self.now())['releases'] or 0,
                    False,
                ),
                ('aggregate', 'aggregate', ['extract'], 1, 0, False),
                ('export', 'export', ['aggregate'], 1, 0, False),
                ('labels', 'prepare-labels', ['extract'], 1, 0, False),
                ('quality', 'quality-summary', ['extract'], 1, 0, False),
                ('report', 'report', ['quality'], 1, 0, False),
                ('labels-30', '', [], 0, 0, True),
                ('spot-check-5', '', [], 0, 0, True),
                ('nda', '', [], 0, 0, True),
            ]
        )
        with self.store.transaction() as connection:
            if (
                connection.execute(
                    text("SELECT value FROM schedule_state WHERE key='start_day'")
                ).scalar_one_or_none()
                is not None
            ):
                connection.execute(
                    text(
                        "INSERT OR IGNORE INTO schedule_tasks(task_key,command,dependencies,earliest_day,quota_cost,status,attempts,next_eligible,human,parameters) VALUES ('xbrl','','[\"index\"]',:day,0,'pending',0,0,0,'{}')"
                    ),
                    {'day': start.isoformat()},
                )
                return
            for key, value in {
                'start_day': start.isoformat(),
                'paused': False,
                'models_confirmed': False,
                'auth_blocked': False,
                'forecast': scope_summary(self.config, now=self.now()),
            }.items():
                connection.execute(
                    text('INSERT INTO schedule_state(key,value) VALUES (:key,:value)'),
                    {'key': key, 'value': json.dumps(value)},
                )
            for key, command, deps, offset, cost, human in rows:
                values = {
                    'key': key,
                    'command': command,
                    'deps': json.dumps(deps),
                    'day': (start + timedelta(days=offset)).isoformat(),
                    'cost': cost,
                    'human': human,
                    'parameters': '{}',
                }
                connection.execute(
                    text(
                        "INSERT OR IGNORE INTO schedule_tasks(task_key,command,dependencies,earliest_day,quota_cost,status,attempts,next_eligible,human,parameters) VALUES (:key,:command,:deps,:day,:cost,'pending',0,0,:human,:parameters)"
                    ),
                    values,
                )

    def tasks(self) -> list[dict[str, Any]]:
        with self.store.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    text('SELECT * FROM schedule_tasks ORDER BY rowid')
                ).mappings()
            ]

    def update(self, key: str, **values: Any) -> None:
        if set(values) - {'status', 'last_error', 'next_eligible', 'parameters'}:
            raise ValueError('invalid task update')
        with self.store.transaction() as connection:
            connection.execute(
                text(
                    'UPDATE schedule_tasks SET '
                    + ','.join(name + '=:' + name for name in values)
                    + ' WHERE task_key=:task'
                ),
                {**values, 'task': key},
            )

    def snapshot(self) -> dict[str, Any]:
        self.ensure_plan()
        now = self.now()
        forecast = self.state('forecast', {})
        if forecast.get('daily_limit') != self.config.llm.requests_per_day or forecast.get(
            'daily_capacity'
        ) != daily_capacity(self.config):
            forecast = scope_summary(
                self.config,
                now=datetime.fromisoformat(self.state('start_day')).replace(tzinfo=timezone.utc),
            )
            self.set_state('forecast', forecast)
        start = date.fromisoformat(self.state('start_day'))
        model_offset = max(
            0,
            (
                date.fromisoformat(
                    self.state('model_start_day', (start + timedelta(days=1)).isoformat())
                )
                - start
            ).days,
        )
        count = min(
            self.config.scheduler.max_days, int(forecast.get('model_days') or 1) + model_offset
        )
        days = []
        remaining = int(forecast.get('releases') or 0)
        bakeoff = self.config.scheduler.bakeoff_requests
        for offset in range(count):
            day = start + timedelta(days=offset)
            hour, minute = map(int, self.config.schedule.run_at_utc.split(':'))
            instant = datetime.combine(day, datetime.min.time(), timezone.utc).replace(
                hour=hour, minute=minute
            )
            planned_bakeoff = (
                min(bakeoff, daily_capacity(self.config)) if offset >= model_offset else 0
            )
            planned_extract = (
                min(remaining, max(0, daily_capacity(self.config) - planned_bakeoff))
                if offset >= model_offset
                else 0
            )
            bakeoff -= planned_bakeoff
            remaining -= planned_extract
            days.append(
                {
                    'utc_day': day.isoformat(),
                    'local_time': instant.astimezone().isoformat(),
                    'used': self.used(day.isoformat()),
                    'budget': daily_capacity(self.config),
                    'configured_limit': self.config.llm.requests_per_day,
                    'today': day == now.date(),
                    'planned_requests': planned_bakeoff + planned_extract,
                    'retry_reserve': self.config.scheduler.retry_reserve
                    if offset >= model_offset
                    else 0,
                    'planned_by_task': {'bakeoff': planned_bakeoff, 'extract': planned_extract},
                }
            )
        tasks = []
        current_states = {row['task_key']: row['status'] for row in self.tasks()}
        for row in self.tasks():
            status = row['status']
            if (
                status == 'pending'
                and not row['human']
                and row['earliest_day'] <= now.date().isoformat()
                and row['next_eligible'] <= self.clock()
                and all(
                    current_states.get(key) == 'done' for key in json.loads(row['dependencies'])
                )
            ):
                status = 'due'
            tasks.append(
                {
                    'id': row['task_key'],
                    'status': status,
                    'earliest_day': row['earliest_day'],
                    'quota_cost': row['quota_cost'],
                    'attempts': row['attempts'],
                    'last_error': row['last_error'],
                    'next_eligible': row['next_eligible'] or None,
                    'human': bool(row['human']),
                    'capability': 'human'
                    if row['human']
                    else 'planned'
                    if not row['command']
                    else 'executable',
                }
            )
        hour, minute = map(int, self.config.schedule.run_at_utc.split(':'))
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        result = {
            'version': 'v1',
            'utc_day': now.date().isoformat(),
            'local_time': now.astimezone().isoformat(),
            'paused': self.state('paused', False),
            'models_confirmed': self.state('models_confirmed', False),
            'auth_blocked': self.state('auth_blocked', False),
            'next_run_utc': next_run.isoformat(),
            'next_run_local': next_run.astimezone().isoformat(),
            'forecast': forecast,
            'days': days,
            'tasks': tasks,
        }
        atomic_json(result, Paths.from_config(self.config).resolve('manifests/schedule.json'))
        return result

    def _job(self, row: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        current = self.store.get(row['last_job']) if row['last_job'] else None
        if current and current['status'] in {'queued', 'running'}:
            pass
        elif current and current['status'] in {'interrupted', 'failed', 'cancelled'}:
            previous = json.loads(current.get('request_json') or '{}')
            old_parameters = previous.get('parameters', {})

            def semantic(value: dict[str, Any]) -> dict[str, Any]:
                return {
                    **value,
                    'set': [
                        item
                        for item in value.get('set', [])
                        if not item.startswith('llm.requests_per_day=')
                    ],
                }

            if semantic(old_parameters) != semantic(parameters):
                raise ValueError('execution parameters changed')
            if old_parameters != parameters:
                previous['parameters'] = parameters
                with self.store.transaction() as connection:
                    connection.execute(
                        text('UPDATE jobs SET request_json=:request WHERE id=:id'),
                        {
                            'request': json.dumps(previous, separators=(',', ':')),
                            'id': current['id'],
                        },
                    )
                self.store.event(current['id'], None, 'quota_allocation_updated')
            self.store.resume(current['id'], self.config)
        else:
            submission = (
                'schedule-'
                + row['task_key']
                + '-'
                + hashlib.sha256(
                    (self.state('start_day') + str(row['attempts'])).encode()
                ).hexdigest()[:16]
            )
            current, _ = self.store.create(
                RunRequest(
                    workflow_id='command',
                    submission_id=submission,
                    command_id=row['command'],
                    parameters=parameters,
                ),
                self.config,
                self.config_path,
                schedule_task=row['task_key'],
            )
        assert current is not None
        if self.execute:
            self.execute(self.store, current['id'])
        elif (self.store.get(current['id']) or {}).get('status') == 'queued':
            self.store.launch(current['id'])
        while True:
            value = self.store.get(current['id'])
            if value and value['status'] not in {'queued', 'running'}:
                return value
            self.store.reconcile()
            time.sleep(0.25)

    def start_models(self) -> None:
        self.ensure_plan()
        if not self.state('models_confirmed', False) or self.state('models_hold'):
            raise DataError('model approval and acceptance checks required')
        day_zero = {key for key, command, _ in DAY_ZERO if command}
        if any(t['status'] != 'done' for t in self.tasks() if t['task_key'] in day_zero):
            raise DataError('Day 0 must finish before model work')
        today = self.now().date().isoformat()
        with self.store.transaction() as connection:
            connection.execute(
                text(
                    "UPDATE schedule_tasks SET earliest_day=:day WHERE task_key IN ('bakeoff','extract','aggregate','export','labels','quality','report') AND earliest_day>:day"
                ),
                {'day': today},
            )
        self.set_state('model_start_day', today)

    def run_once(self, automatic: bool = False) -> dict[str, Any]:
        self.ensure_plan()
        if self.state('paused', False):
            return self.snapshot()
        now = self.now()
        if automatic:
            hour, minute = map(int, self.config.schedule.run_at_utc.split(':'))
            if (now.hour, now.minute) < (hour, minute) or self.state(
                'automatic_day'
            ) == now.date().isoformat():
                return self.snapshot()
        if (
            now.date() - date.fromisoformat(self.state('start_day'))
        ).days >= self.config.scheduler.max_days:
            self.set_state('paused', True)
            return self.snapshot()
        try:
            with file_lock(Paths.from_config(self.config).root / '.schedule-run', blocking=False):
                self.store.reconcile()
                for original in self.tasks():
                    if self.state('paused', False):
                        break
                    row = next(
                        item for item in self.tasks() if item['task_key'] == original['task_key']
                    )
                    if row['status'] == 'running' and row['last_job']:
                        job = self.store.get(row['last_job'])
                        if job and job['status'] == 'succeeded':
                            self.update(row['task_key'], status='done', last_error=None)
                        elif job and job['status'] in {'failed', 'interrupted', 'cancelled'}:
                            self.update(row['task_key'], status='pending')
                        row = next(
                            item for item in self.tasks() if item['task_key'] == row['task_key']
                        )
                    if (
                        row['human']
                        or row['status'] == 'done'
                        or row['earliest_day'] > now.date().isoformat()
                        or row['next_eligible'] > self.clock()
                    ):
                        continue
                    states = {item['task_key']: item['status'] for item in self.tasks()}
                    if any(states.get(key) != 'done' for key in json.loads(row['dependencies'])):
                        continue
                    if not row['command']:
                        self.update(row['task_key'], status='blocked', last_error='planned')
                        continue
                    model = row['quota_cost'] > 0
                    if model and self.state('models_hold'):
                        self.update(
                            row['task_key'], status='blocked', last_error=self.state('models_hold')
                        )
                        continue
                    if model and (
                        not self.state('models_confirmed', False)
                        or self.state('auth_blocked', False)
                    ):
                        self.update(
                            row['task_key'],
                            status='blocked',
                            last_error='pending human'
                            if not self.state('models_confirmed', False)
                            else 'needs attention',
                        )
                        continue
                    from nowcast.operations import doctor

                    if (
                        row['command'] in {'build-constituents', 'ingest'}
                        and not doctor(self.config)['sec_contact']
                    ):
                        self.update(
                            row['task_key'], status='blocked', last_error='SEC contact required'
                        )
                        continue
                    if row['task_key'] == 'extract' and self.state('bakeoff_unusable', False):
                        self.update(
                            row['task_key'], status='blocked', last_error='no usable measured model'
                        )
                        continue
                    if model and self.config.llm.offline:
                        self.update(row['task_key'], status='blocked', last_error='offline')
                        continue
                    if model and self.used() >= daily_capacity(self.config):
                        self.update(
                            row['task_key'],
                            status='pending',
                            last_error='quota exhausted',
                            next_eligible=(
                                now.replace(hour=0, minute=0, second=0, microsecond=0)
                                + timedelta(days=1)
                            ).timestamp(),
                        )
                        continue
                    parameters: dict[str, Any] = {}
                    if model:
                        cap = daily_capacity(self.config)
                        if row['task_key'] == 'bakeoff':
                            anchor = self.state('bakeoff_reservation_anchor')
                            if anchor is None:
                                anchor = self.total_reservations()
                                self.set_state('bakeoff_reservation_anchor', anchor)
                            left = max(
                                0,
                                self.config.scheduler.bakeoff_requests
                                - (self.total_reservations() - anchor),
                            )
                            if not left:
                                self.update(
                                    row['task_key'],
                                    status='done',
                                    last_error='budget-limited comparison',
                                )
                                self.choose_model()
                                continue
                            cap = min(cap, self.used() + left)
                        parameters = {
                            'set': [
                                f'llm.requests_per_day={cap}',
                                'llm.retry_attempts=1',
                                'runtime.max_concurrency=1',
                                'runtime.durable_requests=true',
                            ]
                        }
                        if row['task_key'] == 'extract' and self.state('selected_model'):
                            parameters['set'].append('llm.models=' + self.state('selected_model'))
                        if row['task_key'] == 'bakeoff':
                            parameters['sample'] = max(
                                1,
                                self.config.scheduler.bakeoff_requests
                                // max(1, len(self.config.llm.models)),
                            )
                    try:
                        job = self._job(row, parameters)
                    except ValueError:
                        self.update(
                            row['task_key'],
                            status='blocked',
                            last_error='writer or fingerprint needs attention',
                        )
                        continue
                    events = self.store.events(job['id'])
                    kind = events[-1]['kind'] if events else 'failed'
                    if job['status'] == 'succeeded':
                        self.update(row['task_key'], status='done', last_error=None)
                        if row['task_key'] == 'bakeoff':
                            self.choose_model()
                    elif kind == 'authentication_failed':
                        self.set_state('auth_blocked', True)
                        self.update(row['task_key'], status='blocked', last_error='needs attention')
                    elif kind in {'quota_exhausted', 'rate_limited'}:
                        until = (
                            now.replace(hour=0, minute=0, second=0, microsecond=0)
                            + timedelta(days=1)
                        ).timestamp()
                        with self.store.engine.connect() as connection:
                            cooldown = (
                                connection.execute(
                                    text('SELECT resume_at FROM cooldowns WHERE scope=:scope'),
                                    {'scope': self.config.llm.base_url},
                                ).scalar_one_or_none()
                                or 0
                            )
                        self.update(
                            row['task_key'],
                            status='pending',
                            last_error=kind,
                            next_eligible=max(until, cooldown),
                        )
                    else:
                        self.update(
                            row['task_key'],
                            status='blocked' if kind == 'needs_attention' else 'failed',
                            last_error='needs attention'
                            if kind == 'needs_attention'
                            else 'task failed',
                        )
                    if row['task_key'] == 'extract':
                        self.after_batch()
        except BlockingIOError:
            pass
        if automatic:
            self.set_state('automatic_day', now.date().isoformat())
        return self.snapshot()

    def after_batch(self) -> None:
        for command in ('aggregate', 'export'):
            key = 'batch-' + command
            with self.store.transaction() as connection:
                connection.execute(
                    text(
                        "INSERT OR IGNORE INTO schedule_tasks(task_key,command,dependencies,earliest_day,quota_cost,status,attempts,next_eligible,human,parameters) VALUES (:key,:command,'[]',:day,0,'pending',0,0,0,'{}')"
                    ),
                    {'key': key, 'command': command, 'day': self.now().date().isoformat()},
                )
            row = next(item for item in self.tasks() if item['task_key'] == key)
            if row['status'] == 'done':
                self.update(key, status='pending')
                row = next(item for item in self.tasks() if item['task_key'] == key)
            try:
                result = self._job(row, {})
                self.update(key, status='done' if result['status'] == 'succeeded' else 'failed')
            except ValueError:
                self.update(key, status='failed', last_error='writer needs attention')

    def choose_model(self) -> None:
        # No labelled quality ranking is invented; select only from measured bakeoff rows.
        roots = Paths.from_config(self.config).manifests(self.config) / 'bakeoff'
        files = (
            sorted(roots.glob('*/scores.json'), key=lambda path: path.stat().st_mtime, reverse=True)
            if roots.exists()
            else []
        )
        if not files:
            return
        rows = json.loads(files[0].read_text()).get('models', [])
        eligible = [
            row
            for row in rows
            if str(row.get('model', '')).endswith(':free')
            and row.get('nonempty_extractions', row.get('ok', 0))
        ]
        if not eligible:
            self.set_state('bakeoff_unusable', True)
            return
        self.set_state('bakeoff_unusable', False)
        selected = sorted(
            eligible,
            key=lambda row: (
                -float(row.get('parse_success_rate', 0)),
                float(row.get('empty_completion_rate', 0)),
                -sum(float(v) for v in row.get('coverage', {}).values()),
                (
                    0
                    if row.get('reasoning_tokens') == 0
                    else 1
                    if row.get('reasoning_tokens') is None
                    else 2
                ),
                float(row['completion_tokens'])
                if row.get('completion_tokens') is not None
                else float(row.get('tokens', float('inf'))),
                float(row.get('latency_p95_seconds') or float('inf')),
            ),
        )[0]['model']
        self.set_state('selected_model', selected)


def installation_preview(
    config: Config, root: Path, config_home: Path | None = None
) -> dict[str, str]:
    identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
    name = 'tresata-' + identity
    directory = (
        config_home or Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    ) / 'systemd/user'

    def quote(value: str) -> str:
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'

    marker = '# Managed by Tresata ' + identity
    service = f'{marker}\n[Unit]\nDescription=Tresata quota-aware tasks\n[Service]\nType=oneshot\nWorkingDirectory={str(root.resolve()).replace(chr(37), chr(37) * 2)}\nExecStart={quote(str(root.resolve() / "setup.sh"))} cli schedule run --once\n'
    timer = f'{marker}\n[Unit]\nDescription=Tresata UTC schedule\n[Timer]\nOnCalendar=*-*-* {config.schedule.run_at_utc}:00 UTC\nPersistent=true\nUnit={name}.service\n[Install]\nWantedBy=timers.target\n'
    return {
        str(directory / (name + '.service')): service,
        str(directory / (name + '.timer')): timer,
    }


def cron_entry(config: Config, root: Path) -> str:
    identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
    executable = shlex.quote(str(root.resolve() / 'setup.sh'))
    log = shlex.quote(str(Paths.from_config(config).resolve('logs/scheduler.log')))
    return f'# BEGIN Tresata {identity}\n* * * * * {executable} cli schedule run --once --automatic >> {log} 2>&1\n# END Tresata {identity}\n'


def edit_crontab(current: str, entry: str, remove: bool = False) -> str:
    begin, end = entry.splitlines()[0], entry.splitlines()[-1]
    lines = current.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip('\n') == begin]
    ends = [index for index, line in enumerate(lines) if line.rstrip('\n') == end]
    if (
        len(starts) > 1
        or len(ends) > 1
        or bool(starts) != bool(ends)
        or (starts and starts[0] >= ends[0])
    ):
        raise DataError('ambiguous scheduler crontab block; manual review required')
    if starts:
        lines = lines[: starts[0]] + lines[ends[0] + 1 :]
    body = ''.join(lines)
    if remove:
        return body
    if body and not body.endswith('\n'):
        body += '\n'
    return body + entry


def install(config: Config, root: Path, confirm: bool = False, remove: bool = False) -> None:
    systemd = bool(
        shutil.which('systemctl')
        and subprocess.run(
            ['systemctl', '--user', 'is-active', 'default.target'], capture_output=True, check=False
        ).returncode
        == 0
    )
    files = installation_preview(config, root)
    if systemd:
        for name, body in files.items():
            print(name + '\n' + body)
    else:
        print(cron_entry(config, root))
    if not confirm and (
        not sys.stdin.isatty()
        or input('Uninstall this schedule? [y/N] ' if remove else 'Install this schedule? [y/N] ')
        .strip()
        .lower()
        != 'y'
    ):
        return
    if not systemd:
        if not shutil.which('crontab'):
            raise DataError('neither user systemd nor crontab is available')
        existing = subprocess.run(['crontab', '-l'], capture_output=True, text=True, check=False)
        current = existing.stdout if existing.returncode == 0 else ''
        body = edit_crontab(current, cron_entry(config, root), remove)
        if not remove:
            Paths.from_config(config).resolve('logs').mkdir(parents=True, exist_ok=True)
        subprocess.run(['crontab', '-'], input=body, text=True, capture_output=True, check=True)
        return
    for name, body in files.items():
        path = Path(name)
        if path.exists() and not path.read_text().startswith(body.splitlines()[0]):
            raise DataError('timer path is not owned by this checkout')
    timer = next(Path(name).name for name in files if name.endswith('.timer'))
    if remove:
        if not any(Path(name).exists() for name in files):
            return
        subprocess.run(
            ['systemctl', '--user', 'disable', '--now', timer], check=False, capture_output=True
        )
        for name in files:
            Path(name).unlink(missing_ok=True)
    else:
        for name, body in files.items():
            atomic_bytes(body.encode(), Path(name))
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, capture_output=True)
    if not remove:
        subprocess.run(
            ['systemctl', '--user', 'enable', '--now', timer], check=True, capture_output=True
        )


def command(config: Config, config_path: Path, args: argparse.Namespace) -> int:
    scheduler = Scheduler(config, config_path)
    action = args.schedule_action
    scheduler.ensure_plan()
    if action in {'install', 'uninstall'}:
        install(
            config,
            Path(config.config_dir) / config.paths.project_dir,
            args.confirm,
            remove=action == 'uninstall',
        )
        return 0
    if action == 'pause':
        scheduler.set_state('paused', True)
        for task in scheduler.tasks():
            if task['status'] == 'running' and task['last_job']:
                scheduler.store.cancel(task['last_job'])
    if action == 'resume':
        scheduler.set_state('paused', False)
        if args.confirm_models:
            scheduler.set_state('models_confirmed', True)
            scheduler.set_state('auth_blocked', False)
    if action == 'run':
        if getattr(args, 'start_models', False):
            scheduler.start_models()
        while True:
            result = scheduler.run_once(args.automatic)
            if not args.daemon:
                break
            time.sleep(30)
    else:
        result = scheduler.snapshot()
    if action == 'plan':
        print('UTC | Local | Tasks | Used / Limit')
        for day in result['days']:
            tasks = ','.join(
                row['id'] for row in result['tasks'] if row['earliest_day'] == day['utc_day']
            )
            print(
                f'{day["utc_day"]} | {day["local_time"]} | {tasks} | {day["used"]} / {day["budget"]}'
            )
    else:
        print(json.dumps(result, sort_keys=True))
    return 0
