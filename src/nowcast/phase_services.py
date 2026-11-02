"""Individually executable pipeline phases using the existing parsers and validators."""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from nowcast.config import Config
from nowcast.errors import DataError
from nowcast.paths import Paths
from nowcast.storage import atomic_json, atomic_parquet

PHASES = (
    'cohort',
    'discover',
    'download',
    'parse',
    'validate',
    'consolidate',
    'review',
    'gate',
    'publish',
    'suppressed',
)


RUN_ALL_STAGES = (
    'validate-config',
    'build-constituents',
    'estimate-scope',
    'cohort',
    'ingest',
    'parse',
    'extract',
    'validate',
    'consolidate',
    'aggregate',
    'gate',
    'publish',
    'export',
)


def phase_path(config: Config, phase: str) -> Path:
    return Paths.from_config(config).resolve('manifests/stages/' + phase + '.parquet')


def execute(phase: str, config: Config) -> None:
    from nowcast.ingestion.constituents import load_constituents
    from nowcast.ingestion.doc_index import IndexCheckpoint
    from nowcast.ingestion.rebuild import index_path
    from nowcast.jobs import check_cancelled
    from nowcast.scope import scoped_membership

    paths = Paths.from_config(config)
    frame = pd.DataFrame()
    rows: list[dict[str, Any]] = []
    if phase in {'cohort', 'discover'}:
        membership = load_constituents(paths.resolve(config.data.constituents_csv))
        effective, membership = scoped_membership(config, membership)
        from nowcast.ingestion.sampling import season_sample

        sample = season_sample(effective, membership)
        frame = pd.DataFrame(sample.pairs, columns=['cik', 'season'])
        frame['outcome'] = 'unvisited'
        if phase == 'discover':
            from nowcast.ingestion.constituents import active_on
            from nowcast.ingestion.edgar import (
                IngestReport,
                RateLimiter,
                build_client,
                fetch_disclosures,
            )
            from nowcast.ingestion.sampling import select_filings

            rows = []
            report = IngestReport()
            limiter = RateLimiter(effective.data.sec_max_requests_per_sec)
            try:
                with build_client(effective) as client:
                    for cik in sample.ciks:
                        check_cancelled()
                        disclosures = fetch_disclosures(
                            effective, cik, client, limiter, report=report
                        )
                        disclosures = [
                            d
                            for d in disclosures
                            if d.cik in set(active_on(membership, d.filing_date.isoformat()).cik)
                        ]
                        chosen, _ = select_filings(
                            disclosures, wanted_seasons=sample.season_targets().get(cik, ())
                        )
                        rows.extend(
                            {
                                **dataclasses.asdict(d),
                                'filing_date': d.filing_date.isoformat(),
                                'form': '8-K',
                            }
                            for d in chosen
                        )
            finally:
                atomic_json(
                    report.as_dict(), paths.resolve('manifests/stages/discover-report.json')
                )
            frame = pd.DataFrame(rows)
    elif phase == 'download':
        from nowcast.ingestion.edgar import (
            Disclosure,
            RateLimiter,
            build_client,
            download_document,
            index_row,
        )

        source = phase_path(config, 'discover')
        if not source.is_file():
            raise DataError('Discover artifact required')
        limiter = RateLimiter(config.data.sec_max_requests_per_sec)
        checkpoint = IndexCheckpoint(index_path(config))
        rows = []
        try:
            with build_client(config) as client:
                for row in pd.read_parquet(source).to_dict('records'):
                    check_cancelled()
                    disclosure = Disclosure(
                        **{
                            **{key: row[key] for key in Disclosure.__dataclass_fields__},
                            'filing_date': date.fromisoformat(row['filing_date']),
                        }
                    )
                    target = download_document(config, disclosure, client, limiter)
                    item = index_row(config, disclosure, target)
                    rows.append(item)
                    checkpoint.add(item)
        finally:
            checkpoint.flush()
        frame = pd.DataFrame(rows)
    elif phase in {'parse', 'validate'}:
        from nowcast.extraction.runner import load_documents, prepare_text
        from nowcast.scope import select_documents

        documents = select_documents(config, load_documents(config, index_path(config)))
        rows = []
        for document in documents:
            check_cancelled()
            prepared = prepare_text(config, document)
            if phase == 'parse':
                rows.append(
                    {
                        'document_id': document.document_id,
                        'chars': prepared.chars_total,
                        'chars_sent': prepared.chars_sent,
                        'truncated': prepared.truncated,
                    }
                )
            else:
                from nowcast.extraction.review_queue import replace_rows, rows_for_record
                from nowcast.extraction.runner import model_slug
                from nowcast.extraction.schema import ExtractionRecord
                from nowcast.extraction.validators import needs_review, validate_record

                for model in config.llm.models:
                    for source in (paths.extractions(config) / model_slug(model)).rglob('*.json'):
                        payload = json.loads(source.read_text())
                        if payload.get('document_id') != document.document_id or not payload.get(
                            'record'
                        ):
                            continue
                        issues, record = validate_record(
                            ExtractionRecord.model_validate(payload['record']),
                            prepared.source_text,
                            config,
                            report_date=document.report_date,
                        )
                        reasons = needs_review(record, issues, config, truncated=prepared.truncated)
                        queue = rows_for_record(
                            document.document_id,
                            model,
                            reasons,
                            [(i.field, i.code) for i in issues],
                        )
                        replace_rows(
                            paths.resolve(config.extraction.review_queue_path),
                            document.document_id,
                            model,
                            queue,
                        )
                        rows.append(
                            {
                                'document_id': document.document_id,
                                'issues': len(issues),
                                'flagged': bool(reasons),
                                'record': record.model_dump_json(),
                            }
                        )
        frame = pd.DataFrame(rows)
    elif phase == 'consolidate':
        from nowcast.extraction.runner import consolidate, write_consolidated

        frame = consolidate(config, list(config.llm.models))
        write_consolidated(config, frame)
    elif phase == 'review':
        from nowcast.extraction.review_queue import load_queue

        frame = load_queue(paths.resolve(config.extraction.review_queue_path))
    elif phase in {'gate', 'publish', 'suppressed'}:
        source = paths.aggregates(config) / 'index_aggregates.parquet'
        if not source.is_file():
            raise DataError('Aggregate artifact required')
        aggregate = pd.read_parquet(source)
        if phase == 'gate':
            from nowcast.registry import load_registry

            latest = (
                aggregate.sort_values('as_of_date')
                .groupby(['season_year', 'season_quarter'])
                .tail(1)
            )
            rows = []
            for row in latest.to_dict('records'):
                for kpi in load_registry(config).kpis:
                    status = row.get('metric_status_' + kpi.output, 'unavailable')
                    rows.append(
                        {
                            'season': f'{row["season_year"]}Q{row["season_quarter"]}',
                            'metric': kpi.id,
                            'pass': status == 'ok' and not row.get('suppressed', True),
                            'status': status,
                        }
                    )
            frame = pd.DataFrame(rows)
        else:
            frame = aggregate[aggregate.suppressed.eq(phase == 'suppressed')].copy()
            if phase == 'publish':
                from nowcast.knowledge import knowledge_base

                knowledge_base(config, write=True)
            from nowcast.contracts import IndexSnapshot

            snapshot = IndexSnapshot(
                snapshots=json.loads(frame.to_json(orient='records', date_format='iso'))
            )
            atomic_json(
                snapshot.model_dump(mode='json'), paths.resolve('exports/' + phase + '.json')
            )
    else:
        raise DataError('unknown pipeline phase')
    atomic_parquet(frame, phase_path(config, phase))
