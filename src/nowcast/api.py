"""Workstation control plane with same-origin and CSRF protection."""

from __future__ import annotations

import json
import os
import secrets
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from nowcast.aggregation.aggregate import assert_index_level_only
from nowcast.config import load_config
from nowcast.contracts import (
    IndexSnapshot,
    RunEvent,
    RunRequest,
    RunStatus,
    ScheduleSnapshot,
    SessionResponse,
)
from nowcast.jobs import store_for
from nowcast.offline import saved_snapshot
from nowcast.paths import Paths


def create_app(config_path: Path, launch_workers: bool = True) -> FastAPI:
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    store = store_for(config)
    store.reconcile()
    nonce = secrets.token_urlsafe(32)
    app = FastAPI(title='Tresata workstation API', version='1', docs_url=None, redoc_url=None)
    app.state.store = store
    local_hosts = {'localhost', '127.0.0.1', '::1', socket.gethostname().lower()}

    @app.middleware('http')
    async def boundary(request: Request, call_next: Any) -> Response:
        host = request.url.hostname
        server = request.scope.get('server')
        allowed_hosts = local_hosts | ({server[0]} if server else set())
        if host not in allowed_hosts:
            return JSONResponse({'detail': 'workstation host required'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': 'same origin required'}, status_code=403)
        if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'}:
            return JSONResponse({'detail': 'same origin required'}, status_code=403)
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            cookie, header = (
                request.cookies.get('tresata_session', ''),
                request.headers.get('x-tresata-csrf', ''),
            )
            if not secrets.compare_digest(cookie, nonce) or not secrets.compare_digest(
                header, nonce
            ):
                return JSONResponse({'detail': 'session protection required'}, status_code=403)
            if saved_snapshot(config, 'index', IndexSnapshot) is not None:
                return JSONResponse({'detail': 'offline snapshot is read-only'}, status_code=409)
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            import re

            body = await request.body()
            key = os.environ.get(config.llm.api_key_env, '')
            if (key and key.encode() in body) or re.search(rb'sk-or-v1-[a-fA-F0-9]{32,}', body):
                return JSONResponse({'detail': 'credential input rejected'}, status_code=422)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
        return response

    def require(job_id: str) -> dict[str, Any]:
        row = store.get(job_id)
        if row is None:
            raise HTTPException(404, 'run not found')
        return row

    @app.get('/api/v1/session', response_model=SessionResponse)
    def session(response: Response) -> dict[str, Any]:
        response.set_cookie('tresata_session', nonce, httponly=True, samesite='strict')
        return {
            'version': 'v1',
            'csrf_token': nonce,
            'internal_trace_available': os.environ.get('NOWCAST_INTERNAL_TRACE') == '1',
        }

    @app.get('/api/v1/registry')
    def definitions() -> dict[str, Any]:
        from nowcast.workflow_registry import canvas_registry

        return canvas_registry().model_dump(mode='json')

    @app.get('/api/v1/runs', response_model=list[RunStatus])
    def runs() -> list[RunStatus]:
        store.reconcile()
        return store.list_runs()

    @app.post('/api/v1/runs', response_model=RunStatus, status_code=202)
    def create(request: RunRequest) -> RunStatus:
        try:
            row, created = store.create(request, config, config_path)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if created and launch_workers:
            store.launch(row['id'])
        return store.public(row)

    @app.get('/api/v1/runs/{job_id}', response_model=RunStatus)
    def status(job_id: str) -> RunStatus:
        store.reconcile()
        return store.public(require(job_id))

    @app.post('/api/v1/runs/{job_id}/cancel', response_model=RunStatus)
    def cancel(job_id: str) -> RunStatus:
        require(job_id)
        store.cancel(job_id)
        return store.public(require(job_id))

    @app.post('/api/v1/runs/{job_id}/resume', response_model=RunStatus)
    def resume(job_id: str) -> RunStatus:
        require(job_id)
        try:
            store.resume(job_id, load_config(config_path))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if launch_workers:
            store.launch(job_id)
        return store.public(require(job_id))

    @app.get('/api/v1/runs/{job_id}/events', response_model=list[RunEvent])
    def events(job_id: str, after: int = 0) -> list[dict[str, Any]]:
        require(job_id)
        if after < 0:
            raise HTTPException(422, 'after must be nonnegative')
        return store.events(job_id, after)

    @app.get('/api/v1/index', response_model=IndexSnapshot)
    def index() -> IndexSnapshot:
        bundled = saved_snapshot(config, 'index', IndexSnapshot)
        if bundled is not None:
            return bundled
        path = Paths.from_config(config).aggregates(config) / 'index_aggregates.parquet'
        demo = Paths.from_config(config).resolve('demo/index.json')
        document_index = Paths.from_config(config).resolve(config.data.document_index)
        releases = pd.read_parquet(document_index) if document_index.is_file() else pd.DataFrame()
        real_releases = not releases.empty and (
            'source' not in releases or releases.source.ne('synthetic').any()
        )
        show_demo = not path.is_file() and not real_releases
        if show_demo and demo.is_file():
            from pydantic import ValidationError

            try:
                return IndexSnapshot.model_validate_json(demo.read_text()).model_copy(
                    update={'source': 'synthetic'}
                )
            except (OSError, ValueError, ValidationError):
                return IndexSnapshot(source='synthetic', status='unavailable', snapshots=[])
        if not path.is_file():
            return IndexSnapshot(status='unavailable', snapshots=[])
        frame = pd.read_parquet(path)
        assert_index_level_only(frame)
        records = json.loads(frame.to_json(orient='records', date_format='iso'))
        source = Paths.from_config(config).resolve('manifests/source.json')
        synthetic = source.is_file() and json.loads(source.read_text()).get('source') == 'synthetic'
        return IndexSnapshot(source='synthetic' if synthetic else 'pipeline', snapshots=records)

    @app.get('/api/v1/quality')
    def quality() -> dict[str, Any]:
        from nowcast.extraction.review_queue import load_queue

        queue = load_queue(Paths.from_config(config).resolve(config.extraction.review_queue_path))
        return {
            'version': 'v1',
            'queued_documents': int(queue.document_id.nunique()) if not queue.empty else 0,
            'reason_counts': {str(k): int(v) for k, v in queue.reason.value_counts().items()}
            if not queue.empty
            else {},
            'gate_r0': 'failed',
            'human_labels': 'unavailable',
        }

    @app.get('/api/v1/optimise')
    def optimise() -> dict[str, Any]:
        day = datetime.now(timezone.utc).date().isoformat()
        with store.engine.connect() as connection:
            reserved = connection.execute(
                text('SELECT count(*) FROM reservations WHERE scope=:scope AND utc_day=:day'),
                {'scope': config.llm.base_url, 'day': day},
            ).scalar_one()
        usage = {
            'utc_request_day': day,
            'utc_requests_reserved': reserved,
            'configured_daily_request_limit': config.llm.requests_per_day,
        }
        path = Paths.from_config(config).resolve(config.budget.ledger_path)
        if not path.is_file():
            return {'version': 'v1', 'measurement': 'unavailable', **usage}
        frame = pd.read_parquet(path)
        kinds = frame.get('request_kind', pd.Series('completion', index=frame.index)).fillna(
            'completion'
        )
        latency = (
            frame.get('latency_seconds', pd.Series(index=frame.index, dtype=float))
            .where(kinds.eq('completion'))
            .dropna()
        )
        tokens: dict[str, Any] = {}
        for column in ('prompt_tokens', 'completion_tokens', 'reasoning_tokens', 'content_tokens'):
            measured = (
                pd.to_numeric(
                    frame.get(column, pd.Series(index=frame.index, dtype=float)), errors='coerce'
                )
                .where(kinds.eq('completion'))
                .dropna()
            )
            tokens['recorded_' + column] = int(measured.sum()) if not measured.empty else None
            tokens[column + '_measured_attempts'] = len(measured)
        return {
            'version': 'v1',
            **usage,
            **tokens,
            'recorded_http_attempts': int(kinds.ne('cache').sum()),
            'model_requests': int(kinds.eq('completion').sum()),
            'recorded_cache_hits': int(kinds.eq('cache').sum()),
            'truncated': int((frame.outcome == 'truncated').sum()),
            'latency_measured_attempts': len(latency),
            'latency_p50_seconds': float(latency.median()) if not latency.empty else None,
            'latency_p95_seconds': float(latency.quantile(0.95)) if not latency.empty else None,
            'xbrl_saved_calls': None,
        }

    @app.get('/api/v1/schedule', response_model=ScheduleSnapshot)
    def schedule() -> ScheduleSnapshot:
        from nowcast.scheduler import Scheduler

        return saved_snapshot(
            config, 'schedule', ScheduleSnapshot
        ) or ScheduleSnapshot.model_validate(Scheduler(config, config_path).snapshot())

    @app.get('/api/v1/trace')
    def trace(request: Request) -> dict[str, Any]:
        if (
            os.environ.get('NOWCAST_INTERNAL_TRACE') != '1'
            or request.headers.get('x-tresata-trace') != 'session'
        ):
            raise HTTPException(403, 'internal trace is disabled')
        from nowcast.extraction.review_queue import load_queue

        frame = load_queue(Paths.from_config(config).resolve(config.extraction.review_queue_path))
        return {'version': 'v1', 'rows': json.loads(frame.to_json(orient='records'))}

    from nowcast.inspection_api import register

    register(app, config, config_path, store)
    web = Path(config.config_dir) / config.paths.project_dir / 'web' / 'dist'
    if web.is_dir():
        app.mount('/', StaticFiles(directory=web, html=True), name='website')
    return app
