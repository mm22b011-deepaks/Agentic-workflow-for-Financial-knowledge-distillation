"""Independent worker process; survives API restarts and never evaluates client code."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from nowcast.config import load_config
from nowcast.errors import AuthError, BudgetExceeded, ConfigError
from nowcast.jobs import JobCancelled, JobStore, check_cancelled, config_fingerprint


def execute_stage(config_path: Path, stage: str) -> None:
    """CLI and website share the same existing pipeline services."""
    if stage == 'demo':
        from nowcast.paths import Paths
        from nowcast.verification import synthetic_demo

        config = load_config(config_path)
        synthetic_demo(config, Paths.from_config(config).resolve('demo'))
        return
    from nowcast.cli import build_parser

    args = build_parser().parse_args([stage, '--config', str(config_path)])
    code = int(args.handler(args))
    if code:
        raise RuntimeError(f'stage exited {code}')


def run(store: JobStore, job_id: str) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--job', required=True)
    args = parser.parse_args()
    run(JobStore(args.database), args.job)


if __name__ == '__main__':
    main()
