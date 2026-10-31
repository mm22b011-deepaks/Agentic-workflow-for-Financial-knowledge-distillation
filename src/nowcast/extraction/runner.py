"""Batch extraction runner with resume, budget guard and review routing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from nowcast.config import Config, cache_dir, extractions_dir, prompts_dir, resolve_data_path
from nowcast.errors import BudgetExceeded
from nowcast.extraction import review_queue
from nowcast.extraction.schema import ExtractionRecord
from nowcast.extraction.validators import needs_review, validate_record
from nowcast.llm.cache import ResponseCache, cache_key
from nowcast.llm.prompts import PromptBundle, load_prompt, prompt_hash
from nowcast.llm.structured import extract_structured
from nowcast.parsing.html import html_to_text
from nowcast.parsing.sections import pick_sections

LOGGER = logging.getLogger(__name__)
PROMPT_NAME = 'extraction'
EXTRACTION_PARQUET = 'extractions.parquet'


@dataclass
class Document:
    """One indexed document ready for extraction."""

    document_id: str
    cik: str
    report_date: str
    document_type: str
    raw_path: Path
    sha256: str


@dataclass
class ExtractionOutcome:
    """Per-document result summary."""

    document_id: str
    model: str
    status: str
    skipped: bool = False
    review_reasons: tuple[str, ...] = ()
    error: str | None = None


def model_slug(model: str) -> str:
    """Return a filesystem-safe slug for a model id."""
    return model.replace('/', '__').replace(':', '-')


def load_documents(config: Config, index_path: Path) -> list[Document]:
    """Load the document index and return typed documents."""
    from nowcast.ingestion.doc_index import load_index

    frame = load_index(index_path)
    documents: list[Document] = []
    for row in frame.to_dict('records'):
        raw_path = Path(str(row['raw_path']))
        if not raw_path.is_absolute():
            raw_path = resolve_data_path(config, str(row['raw_path']))
        documents.append(
            Document(
                document_id=str(row['document_id']),
                cik=str(row['cik']),
                report_date=str(row['report_date']),
                document_type=str(row['document_type']),
                raw_path=raw_path,
                sha256=str(row['sha256']),
            )
        )
    return documents


def document_text(config: Config, document: Document) -> str:
    """Read, convert and truncate a document's text for prompting."""
    raw = document.raw_path.read_text(encoding='utf-8', errors='replace')
    text = html_to_text(raw) if document.raw_path.suffix.lower() in {'.htm', '.html'} else raw
    sections: dict[str, str] = {}
    if config.parsing.section_patterns:
        text = pick_sections(
            text, dict(config.parsing.section_patterns), list(config.parsing.section_patterns)
        )
        sections = dict(config.parsing.section_patterns)
    del sections
    return text[: int(config.extraction.max_doc_chars)]


def fingerprint(config: Config, document: Document, model: str, prompt_digest: str) -> str:
    """Return the resume fingerprint for one document/model/prompt combination."""
    digest = hashlib.sha256()
    digest.update(document.sha256.encode('utf-8'))
    digest.update(prompt_digest.encode('utf-8'))
    digest.update(model.encode('utf-8'))
    digest.update(config.extraction.schema_version.encode('utf-8'))
    return digest.hexdigest()


def result_path(config: Config, model: str, document_id: str) -> Path:
    """Return the JSON result path for a document under one model."""
    return extractions_dir(config) / model_slug(model) / f'{document_id}.json'


def _already_done(path: Path, expected: str) -> bool:
    """Return True when a result file exists with the expected fingerprint."""
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False
    return str(payload.get('fingerprint')) == expected


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    """Write one extraction result atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    temporary.replace(path)


class CachedCaller:
    """Wraps a caller with the response cache and turns transient failures into retries."""

    def __init__(self, caller: Any, cache: ResponseCache, config: Config) -> None:
        """Store the inner caller, cache and retry settings."""
        self._caller = caller
        self._cache = cache
        self._config = config
        self.cache_hits = 0

    def complete(self, model: str, messages: list[dict[str, str]]) -> Any:
        """Return a cached or fresh completion, retrying transient errors."""
        prompt_text = '\n'.join(message['content'] for message in messages)
        key = cache_key(
            prompt_text,
            model,
            params={
                'temperature': self._config.llm.temperature,
                'max_tokens': self._config.llm.max_tokens,
            },
        )
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            from nowcast.llm.caller import LLMResult

            return LLMResult(text=cached, model=model)
        attempts = max(1, int(self._config.llm.retry_attempts))
        backoff = float(self._config.llm.retry_backoff_seconds)
        max_wait = float(self._config.llm.retry_max_wait_seconds)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                result = self._caller.complete(model, messages)
            except BudgetExceeded:
                raise
            except Exception as exc:
                last_error = exc
                LOGGER.warning('call failed attempt=%d model=%s error=%s', attempt, model, exc)
                if attempt < attempts - 1:
                    requested = getattr(exc, 'retry_after_seconds', None)
                    delay = backoff * (attempt + 1)
                    if isinstance(requested, (int, float)):
                        # A provider-stated delay (usually a 429 on a busy free pool)
                        # beats our fixed backoff, which is far too short for it.
                        delay = max(delay, float(requested))
                    delay = min(delay, max_wait)
                    if delay > 0:
                        LOGGER.info('retrying in %.1fs attempt=%d model=%s', delay, attempt, model)
                        time.sleep(delay)
                continue
            self._cache.set(key, result.text, model)
            return result
        raise RuntimeError(f'all {attempts} attempts failed: {last_error}')


async def run_extraction(
    config: Config,
    documents: list[Document],
    caller_factory: Callable[[str], Any],
    models: list[str] | None = None,
    queue_path: Path | None = None,
    on_outcome: Callable[[ExtractionOutcome], None] | None = None,
) -> list[ExtractionOutcome]:
    """Extract every document for every model, resuming completed work."""

    active_models = models or list(config.llm.models)
    bundle: PromptBundle = load_prompt(
        PROMPT_NAME, config.extraction.schema_version, prompts_dir(config)
    )
    cache = ResponseCache(config.cache, cache_dir(config))
    queue_target = queue_path or resolve_data_path(config, config.extraction.review_queue_path)
    semaphore = asyncio.Semaphore(int(config.runtime.max_concurrency))
    stop = {'budget': False}
    outcomes: list[ExtractionOutcome] = []
    lock = asyncio.Lock()

    def _prompt_digest() -> str:
        return prompt_hash(
            bundle,
            {
                'max_evidence_words': config.extraction.max_evidence_words,
                'themes': str(list(config.extraction.themes)),
            },
        )

    digest = _prompt_digest()

    async def _process(model: str, document: Document) -> ExtractionOutcome:
        expected = fingerprint(config, document, model, digest)
        target = result_path(config, model, document.document_id)
        if _already_done(target, expected):
            return ExtractionOutcome(document.document_id, model, 'skipped', skipped=True)
        async with semaphore:
            if stop['budget']:
                return ExtractionOutcome(document.document_id, model, 'budget_stopped')
            caller = caller_factory(model)
            variables = {
                'document_id': document.document_id,
                'document_text': document_text(config, document),
                'max_evidence_words': config.extraction.max_evidence_words,
                'themes': ', '.join(config.extraction.themes),
            }
            try:
                parsed, raw_text, error = await asyncio.to_thread(
                    extract_structured,
                    caller,
                    model,
                    bundle,
                    variables,
                    ExtractionRecord,
                    int(config.extraction.max_repairs),
                    cache,
                )
                record: ExtractionRecord | None = (
                    parsed if isinstance(parsed, ExtractionRecord) else None
                )
            except BudgetExceeded:
                stop['budget'] = True
                return ExtractionOutcome(document.document_id, model, 'budget_stopped')
            if record is None:
                rows = [
                    {
                        'document_id': document.document_id,
                        'field': 'record',
                        'reason': 'llm_failed',
                        'model': model,
                    }
                ]
                review_queue.append_rows(queue_target, rows)
                return ExtractionOutcome(
                    document.document_id,
                    model,
                    'failed',
                    review_reasons=('llm_failed',),
                    error=error,
                )
            record = record.model_copy(
                update={
                    'document_id': document.document_id,
                    'schema_version': config.extraction.schema_version,
                }
            )
            source = str(variables['document_text'])
            issues, record = validate_record(record, source, config)
            reasons = needs_review(record, issues, config)
            if reasons:
                rows = review_queue.rows_for_record(
                    document.document_id,
                    model,
                    reasons,
                    [(issue.field, issue.code) for issue in issues],
                )
                review_queue.append_rows(queue_target, rows)
            _write_result(
                target,
                {
                    'fingerprint': expected,
                    'model': model,
                    'document_id': document.document_id,
                    'cik': document.cik,
                    'report_date': document.report_date,
                    'document_type': document.document_type,
                    'raw_text': raw_text,
                    'record': record.model_dump(mode='json'),
                },
            )
            return ExtractionOutcome(
                document.document_id, model, 'ok', review_reasons=tuple(reasons)
            )

    tasks = [_process(model, document) for model in active_models for document in documents]
    for coro in asyncio.as_completed(tasks):
        outcome = await coro
        async with lock:
            outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    _flag_disagreements(config, outcomes, active_models, queue_target)
    consolidate(config, active_models)
    return outcomes


def _load_result(config: Config, model: str, document_id: str) -> dict[str, Any] | None:
    """Load one stored result payload, returning None when absent or unreadable."""
    path = result_path(config, model, document_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _flag_disagreements(
    config: Config, outcomes: list[ExtractionOutcome], models: list[str], queue_path: Path
) -> None:
    """Queue documents where configured models disagree on key fields."""
    if len(models) < 2:
        return
    ok_documents = {
        outcome.document_id for outcome in outcomes if outcome.status in {'ok', 'skipped'}
    }
    tolerance = float(config.extraction.eps_tolerance_abs)
    rows: list[dict[str, str]] = []
    for document_id in sorted(ok_documents):
        records = []
        for model in models:
            payload = _load_result(config, model, document_id)
            if payload is not None:
                records.append((model, payload['record']))
        if len(records) < 2:
            continue
        directions = {
            (record.get('guidance_direction') or {}).get('value') for _model, record in records
        }
        eps_values = [(record.get('reported_eps') or {}).get('value') for _model, record in records]
        numeric = [value for value in eps_values if isinstance(value, (int, float))]
        eps_conflict = bool(numeric) and (max(numeric) - min(numeric)) > tolerance
        if len(directions) > 1 or eps_conflict:
            for model, _record in records:
                rows.append(
                    {
                        'document_id': document_id,
                        'field': 'record',
                        'reason': 'model_disagreement',
                        'model': model,
                    }
                )
    if rows:
        review_queue.append_rows(queue_path, rows)


def consolidate(config: Config, models: list[str]) -> pd.DataFrame:
    """Write one parquet file per model holding every stored record."""
    frames: list[pd.DataFrame] = []
    for model in models:
        directory = extractions_dir(config) / model_slug(model)
        rows: list[dict[str, Any]] = []
        for path in sorted(directory.glob('*.json')):
            payload = _load_result(config, model, path.stem)
            if payload is None:
                continue
            row = {
                'document_id': payload['document_id'],
                'cik': payload.get('cik'),
                'report_date': payload.get('report_date'),
                'document_type': payload.get('document_type'),
                'model': model,
                'fingerprint': payload['fingerprint'],
            }
            record = payload['record']
            row['fiscal_year'] = record.get('fiscal_year')
            row['fiscal_quarter'] = record.get('fiscal_quarter')
            row['currency'] = record.get('currency')
            row['units'] = record.get('units')
            for name in (
                'reported_eps',
                'prior_year_eps',
                'consensus_eps',
                'revenue',
                'revenue_yoy_growth',
            ):
                row[name] = (record.get(name) or {}).get('value')
            for name in ('eps_basis', 'guidance_direction', 'guidance_metric', 'tone'):
                row[name] = (record.get(name) or {}).get('value')
            for theme, mention in (record.get('theme_mentions') or {}).items():
                row[f'theme_{theme}_mentioned'] = bool(mention.get('mentioned'))
                row[f'theme_{theme}_direction'] = mention.get('direction')
            rows.append(row)
        if rows:
            frame = pd.DataFrame(rows)
            target = extractions_dir(config) / f'{model_slug(model)}.parquet'
            frame.sort_values('document_id').to_parquet(target, index=False)
            LOGGER.info('consolidated model=%s rows=%d path=%s', model, len(frame), target)
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    target = consolidated_path(config)
    combined.sort_values(['model', 'document_id']).to_parquet(target, index=False)
    LOGGER.info('consolidated all models rows=%d path=%s', len(combined), target)
    return combined


CONSOLIDATED_NAME = EXTRACTION_PARQUET


def consolidated_path(config: Config) -> Path:
    """Return the combined extraction parquet path."""
    return extractions_dir(config) / CONSOLIDATED_NAME
