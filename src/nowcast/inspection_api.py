"""Schema-validated, private-by-default inspection endpoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request

from nowcast import inspection
from nowcast.config import Config
from nowcast.contracts import (
    CanvasRegistry,
    ConfigControl,
    EvidenceResponse,
    KPIKnowledgeBase,
    LabelRequest,
    LabelResponse,
    MetricSnapshot,
    PaneResponse,
    SettingsResponse,
    StageSnapshot,
)
from nowcast.errors import DataError
from nowcast.jobs import JobStore
from nowcast.offline import saved_snapshot
from nowcast.workflow_registry import canvas_registry


def register(app: FastAPI, config: Config, config_path: Path, store: JobStore) -> None:
    def trace(request: Request) -> bool:
        return (
            os.environ.get('NOWCAST_INTERNAL_TRACE') == '1'
            and request.headers.get('x-tresata-trace') == 'session'
        )

    @app.get('/api/v1/settings', response_model=SettingsResponse)
    def settings() -> SettingsResponse:
        import json

        from nowcast.workflow_registry import extension_path

        nodes = {}
        for node, paths in json.loads(extension_path().read_text()).get('bindings', {}).items():
            fields = []
            for path in paths:
                section, key = path.split('.')
                if key.endswith('_env') or any(
                    term in key for term in ('secret', 'password', 'api_key')
                ):
                    raise ValueError('secret binding refused')
                value = getattr(getattr(config, section), key)
                kind: Literal['boolean', 'integer', 'number', 'string'] = (
                    'boolean'
                    if isinstance(value, bool)
                    else 'integer'
                    if isinstance(value, int)
                    else 'number'
                    if isinstance(value, float)
                    else 'string'
                )
                fields.append(
                    ConfigControl(
                        path=path,
                        kind=kind,
                        value=list(value) if isinstance(value, tuple) else value,
                        multiple=isinstance(value, tuple),
                    )
                )
            nodes[node] = fields
        return SettingsResponse(nodes=nodes)

    @app.get('/api/v1/kpis', response_model=KPIKnowledgeBase)
    def kpis() -> KPIKnowledgeBase:
        from nowcast.knowledge import knowledge_base

        return saved_snapshot(config, 'kpis', KPIKnowledgeBase) or knowledge_base(config)

    @app.get('/api/v1/stages', response_model=StageSnapshot)
    def stages() -> StageSnapshot:
        return saved_snapshot(config, 'stages', StageSnapshot) or inspection.stages(
            config, config_path, store
        )

    @app.get('/api/v1/canvas-registry', response_model=CanvasRegistry)
    def registry() -> CanvasRegistry:
        return canvas_registry()

    @app.get('/api/v1/nodes/{node}/{side}', response_model=PaneResponse)
    def pane(
        node: str,
        side: Literal['input', 'output'],
        request: Request,
        run: str | None = None,
        upstream: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        search: str = Query('', max_length=200),
        flagged: bool | None = None,
        reason: str = Query('', max_length=80),
        field: str = Query('', max_length=80),
        season: str = Query('', pattern=r'^(?:20\d{2}Q[1-4])?$'),
        sample: int = Query(0, ge=0, le=10000),
        seed: int = 42,
    ) -> PaneResponse:
        if side not in {'input', 'output'}:
            raise HTTPException(404, 'unknown pane')
        try:
            return inspection.pane(
                config,
                config_path,
                store,
                node,
                side,
                trace=trace(request),
                run=run,
                upstream=upstream,
                offset=offset,
                limit=limit,
                search=search,
                flagged=flagged,
                reason=reason,
                field=field,
                season=season,
                sample=sample,
                seed=seed,
            )
        except DataError as exc:
            raise HTTPException(404, 'artifact unavailable') from exc

    @app.get('/api/v1/records/{record_id}/evidence', response_model=EvidenceResponse)
    def evidence(record_id: str, request: Request, run: str | None = None) -> EvidenceResponse:
        if not trace(request):
            raise HTTPException(403, 'internal trace is disabled')
        try:
            return inspection.evidence(config, record_id, store, run)
        except DataError as exc:
            raise HTTPException(404, 'evidence unavailable') from exc

    @app.post('/api/v1/labels', response_model=LabelResponse)
    def label(payload: LabelRequest, request: Request) -> LabelResponse:
        if not trace(request):
            raise HTTPException(403, 'internal trace is disabled')
        try:
            return inspection.save_label(config, payload)
        except DataError as exc:
            raise HTTPException(409, 'record changed') from exc

    @app.get('/api/v1/coverage', response_model=MetricSnapshot)
    def coverage() -> MetricSnapshot:
        return saved_snapshot(config, 'coverage', MetricSnapshot) or inspection.coverage(config)

    @app.get('/api/v1/cost', response_model=MetricSnapshot)
    def cost() -> MetricSnapshot:
        return saved_snapshot(config, 'cost', MetricSnapshot) or inspection.cost(config, store)

    @app.get('/api/v1/plan', response_model=MetricSnapshot)
    def plan() -> MetricSnapshot:
        return saved_snapshot(config, 'plan', MetricSnapshot) or inspection.plan(config)

    @app.get('/api/v1/bakeoff', response_model=MetricSnapshot)
    def bakeoff() -> MetricSnapshot:
        return saved_snapshot(config, 'bakeoff', MetricSnapshot) or inspection.bakeoff(config)
