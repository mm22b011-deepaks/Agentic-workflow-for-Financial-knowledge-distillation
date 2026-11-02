"""Independent worker process; survives API restarts and never evaluates client code."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import suppress
from pathlib import Path

from nowcast.config import load_config
from nowcast.errors import AuthError, BudgetExceeded, ConfigError, RateLimited
from nowcast.jobs import JobCancelled, JobStore, check_cancelled, config_fingerprint
from nowcast.llm.receipts import RequestUncertain


def execute_stage(config_path: Path, stage: str, parameters: dict | None = None) -> None:
    """CLI and website share the same existing pipeline services."""
    from nowcast.cli import build_parser
    from nowcast.cli_registry import command_argv

    args = build_parser().parse_args(command_argv(stage, parameters or {}, config_path))
    code = int(args.handler(args))
    if code:
        raise RuntimeError(f'stage exited {code}')


def _run(store: JobStore, job_id: str) -> None:
    if not store.claim(job_id):
        return
    os.environ['NOWCAST_JOB_DATABASE'] = str(store.path)
    os.environ['NOWCAST_JOB_ID'] = job_id
    row = store.get(job_id)
    if row is None:
        return
    try:
        path = Path(row['config_path'])
        config = load_config(path)
        os.environ[config.runtime.data_dir_env] = str(store.path.parent)
        if config_fingerprint(config) != row['fingerprint']:
            raise ValueError('configuration fingerprint changed')
        for index, stage in enumerate(json.loads(row['stages'])):
            check_cancelled()
            store.update(job_id, stage=stage)
            store.event(job_id, stage, 'started')
            request = json.loads(row.get('request_json') or '{}')
            parameters = request.get('parameters', {})
            if parameters:
                execute_stage(path, stage, parameters)
            else:
                execute_stage(path, stage)
            from nowcast.artifacts import record_artifacts

            record_artifacts(store, job_id, stage, config, path)
            store.update(job_id, completed=index + 1)
            store.event(job_id, stage, 'completed')
        check_cancelled()
        store.update(job_id, status='succeeded')
        store.event(job_id, None, 'succeeded')
    except JobCancelled:
        store.update(job_id, status='cancelled')
        store.event(job_id, None, 'cancelled')
    except BudgetExceeded:
        store.update(job_id, status='interrupted')
        store.event(job_id, None, 'quota_exhausted')
    except RateLimited:
        store.update(job_id, status='interrupted')
        store.event(job_id, None, 'rate_limited')
    except RequestUncertain:
        store.update(job_id, status='failed')
        store.event(job_id, None, 'needs_attention')
    except (AuthError, ConfigError) as exc:
        store.update(job_id, status='failed')
        store.event(
            job_id,
            None,
            'authentication_failed' if isinstance(exc, AuthError) else 'configuration_error',
        )
    except Exception:
        # Private data and provider response bodies never enter public job events.
        store.update(job_id, status='failed')
        store.event(job_id, None, 'failed')


def run(store: JobStore, job_id: str) -> None:
    from nowcast.storage import file_lock

    keys = {'NOWCAST_JOB_DATABASE', 'NOWCAST_JOB_ID', 'DATA_DIR'}
    row = store.get(job_id)
    if row:
        with suppress(ConfigError):
            keys.add(load_config(Path(row['config_path'])).runtime.data_dir_env)
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with file_lock(store.path.parent / '.pipeline', blocking=False):
            _run(store, job_id)
    except BlockingIOError:
        store.update(job_id, status='failed')
        store.event(job_id, None, 'writer_busy')
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--job', required=True)
    args = parser.parse_args()
    run(JobStore(args.database), args.job)


if __name__ == '__main__':
    main()
