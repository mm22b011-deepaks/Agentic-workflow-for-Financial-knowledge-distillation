"""Batch extraction runner with resume, budget guard and review routing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from nowcast.config import Config, cache_dir, extractions_dir, prompts_dir, resolve_data_path
from nowcast.errors import BudgetExceeded, TruncatedCompletion
from nowcast.extraction import review_queue
from nowcast.extraction.schema import ExtractionRecord
from nowcast.extraction.validators import needs_review, validate_record
from nowcast.llm.cache import ResponseCache
from nowcast.llm.prompts import PromptBundle, load_prompt, prompt_hash
from nowcast.llm.structured import extract_structured
from nowcast.parsing.html import html_to_text, strip_sgml_wrapper
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


TEXT_SUFFIXES = ('.htm', '.html', '.txt')
EARNINGS_ITEM = '2.02'


def load_documents(
    config: Config, index_path: Path, suffixes: tuple[str, ...] | None = None
) -> list[Document]:
    """Load the document index and return typed documents.

    Two filters, both at the index: a row whose raw file is not parseable text never
    reaches a prompt, and neither does a row whose 8-K items do not include a configured
    earnings item. The second is the difference between extracting an earnings release
    and extracting someone's dividend announcement with equal confidence.
    """
    from nowcast.ingestion.doc_index import has_earnings_item, load_index

    frame = load_index(index_path)
    allowed = {item.lower() for item in (suffixes if suffixes is not None else TEXT_SUFFIXES)}
    wanted_items = tuple(config.data.edgar_earnings_items) or (EARNINGS_ITEM,)
    documents: list[Document] = []
    not_earnings = 0
    for row in frame.to_dict('records'):
        raw_path = Path(str(row['raw_path']))
        if raw_path.suffix.lower() not in allowed:
            LOGGER.info('skip non-text document raw_path=%s', raw_path)
            continue
        items = row.get('items')
        if not has_earnings_item(items, wanted_items):
            # An index written before the `items` column existed carries no proof, so
            # every row of it lands here. That is deliberate: it sends the operator to
            # the rebuild (N7) instead of extracting unclassified filings.
            not_earnings += 1
            continue
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
    if not_earnings:
        LOGGER.warning(
            'skip documents whose index row has no earnings item: %d (wanted %s)',
            not_earnings,
            ','.join(wanted_items),
        )
    return documents


def document_text(config: Config, document: Document) -> str:
    """Read, convert and truncate a document's text for prompting."""
    raw = document.raw_path.read_text(encoding='utf-8', errors='replace')
    if document.raw_path.suffix.lower() in {'.htm', '.html'}:
        text = html_to_text(raw)
    else:
        # A `.txt` exhibit from EDGAR still carries the <DOCUMENT><TYPE>..<TEXT> wrapper.
        text = strip_sgml_wrapper(raw)
    sections: dict[str, str] = {}
    if config.parsing.section_patterns:
        text = pick_sections(
            text, dict(config.parsing.section_patterns), list(config.parsing.section_patterns)
        )
        sections = dict(config.parsing.section_patterns)
    del sections
    return text[: int(config.extraction.max_doc_chars)]


def validation_settings(config: Config) -> dict[str, object]:
    """Return every setting that changes what a stored record means.

    A record is the model's reply *after* validation: confidences are penalized, review
    reasons are derived and the text is cut at `max_doc_chars`. Changing any of those
    settings changes the record, so a stored record produced under different settings
    must not be resumed over.
    """
    extraction = config.extraction
    return {
        'schema_version': extraction.schema_version,
        'max_doc_chars': int(extraction.max_doc_chars),
        'quote_match_min_ratio': float(extraction.quote_match_min_ratio),
        'confidence_penalty_on_issue': float(extraction.confidence_penalty_on_issue),
        'min_confidence': float(extraction.min_confidence),
        'eps_tolerance_abs': float(extraction.eps_tolerance_abs),
        'max_evidence_words': int(extraction.max_evidence_words),
        'themes': [str(theme) for theme in extraction.themes],
        'section_patterns': {str(k): str(v) for k, v in config.parsing.section_patterns.items()},
        'min_section_chars': int(config.parsing.min_section_chars),
    }


def fingerprint(config: Config, document: Document, model: str, prompt_digest: str) -> str:
    """Return the resume fingerprint for one document/model/prompt/settings combination."""
    digest = hashlib.sha256()
    digest.update(document.sha256.encode('utf-8'))
    digest.update(prompt_digest.encode('utf-8'))
    digest.update(model.encode('utf-8'))
    digest.update(json.dumps(validation_settings(config), sort_keys=True).encode('utf-8'))
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


def _record_failure(
    queue_target: Path,
    document: Document,
    model: str,
    reason: str,
    detail: str | None,
) -> ExtractionOutcome:
    """Queue one failed document with its reason and return the outcome."""
    review_queue.append_rows(
        queue_target,
        [
            {
                'document_id': document.document_id,
                'field': 'record',
                'reason': reason,
                'model': model,
            }
        ],
    )
    return ExtractionOutcome(
        document.document_id,
        model,
        'failed',
        review_reasons=(reason,),
        error=detail,
    )


def _safe_failure(
    queue_target: Path,
    document: Document,
    model: str,
    reason: str,
    detail: str | None,
) -> ExtractionOutcome:
    """Record a failure without letting the recording itself raise.

    Used only on the catch-all path: if the queue is what failed (an unwritable data
    directory, say), reporting it again through the same queue would abort the run.
    """
    try:
        return _record_failure(queue_target, document, model, reason, detail)
    except Exception:
        LOGGER.exception(
            'could not queue document failure document=%s model=%s', document.document_id, model
        )
        return ExtractionOutcome(
            document.document_id,
            model,
            'failed',
            review_reasons=(reason,),
            error=detail,
        )


def compose_caller(config: Config, inner: Any, cache: ResponseCache | None = None) -> Any:
    """Wrap a raw caller in the shared retry-plus-cache composition.

    A caller that is already composed (a test fake, or a `RetryingCaller` handed in by a
    caller) is passed through unchanged, so composing twice is harmless and never
    double-counts retries.
    """
    from nowcast.llm.composition import RetryingCaller

    if isinstance(inner, RetryingCaller):
        return inner
    active_cache = cache if cache is not None else ResponseCache(config.cache, cache_dir(config))
    return RetryingCaller(inner, active_cache, config)


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
        """Extract one (model, document), converting any failure into an outcome.

        The whole path is guarded, not just the model call: a missing raw file, a
        validation crash, a queue write that fails and an unwritable result file are
        all per-document problems, and none of them may take down a 480-document run.
        """
        try:
            return await _process_document(model, document)
        except BudgetExceeded:
            # A spend cap is a run-level stop, not a document failure; handled inside.
            stop['budget'] = True
            return ExtractionOutcome(document.document_id, model, 'budget_stopped')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception('document failed model=%s document=%s', model, document.document_id)
            return _safe_failure(queue_target, document, model, 'document_error', str(exc))

    async def _process_document(model: str, document: Document) -> ExtractionOutcome:
        """The unguarded per-document path; every exception is handled by _process."""
        expected = fingerprint(config, document, model, digest)
        target = result_path(config, model, document.document_id)
        if _already_done(target, expected):
            return ExtractionOutcome(document.document_id, model, 'skipped', skipped=True)
        async with semaphore:
            if stop['budget']:
                return ExtractionOutcome(document.document_id, model, 'budget_stopped')
            # Every model call goes through the one composition point, so retry,
            # Retry-After and the cache apply on the live path, not only in tests.
            caller = compose_caller(config, caller_factory(model))
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
            except TruncatedCompletion as exc:
                # The model returned nothing within its budget. Distinct from llm_failed
                # so the queue says what actually happened and the run summary can count it.
                return _record_failure(queue_target, document, model, 'truncated', str(exc))
            if record is None:
                return _record_failure(queue_target, document, model, 'llm_failed', error)
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
