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
from nowcast.errors import AuthError, BudgetExceeded, EmptyCompletion, TruncatedCompletion
from nowcast.extraction import review_queue
from nowcast.extraction.schema import ExtractionRecord
from nowcast.extraction.units import normalise_record
from nowcast.extraction.validators import needs_review, validate_record
from nowcast.llm.cache import ResponseCache
from nowcast.llm.prompts import PromptBundle, load_prompt, prompt_hash
from nowcast.llm.structured import extract_structured
from nowcast.parsing.html import html_to_text, strip_sgml_wrapper
from nowcast.parsing.packing import pack
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
    truncated: bool = False


@dataclass(frozen=True)
class DocumentText:
    """One document's prompt text and how much of the source survived the cut."""

    text: str
    chars_total: int
    chars_sent: int
    windows_used: int = 0
    # The converted text before the cut. Kept so a measurement does not have to parse
    # the same document a second time just to ask what was left out.
    source_text: str = ''

    @property
    def truncated(self) -> bool:
        """Return True when text was dropped before the prompt."""
        return self.chars_sent < self.chars_total


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


def prepare_text(config: Config, document: Document) -> DocumentText:
    """Read, convert and cut a document's text, reporting what the cut dropped.

    `chars_total` is the length after conversion and section selection, i.e. the text
    the prompt would carry if nothing were cut; `chars_sent` is what it did carry.
    The gap is the only honest measure of how much of a long release the model never
    saw, and on the real corpus it is not small: see DEFECTS.md H5.
    """
    raw = document.raw_path.read_text(encoding='utf-8', errors='replace')
    if document.raw_path.suffix.lower() in {'.htm', '.html'}:
        text = html_to_text(raw)
    else:
        # A `.txt` exhibit from EDGAR still carries the <DOCUMENT><TYPE>..<TEXT> wrapper.
        text = strip_sgml_wrapper(raw)
    if config.parsing.section_patterns:
        text = pick_sections(
            text, dict(config.parsing.section_patterns), list(config.parsing.section_patterns)
        )
    packed = pack(text, int(config.extraction.max_doc_chars), tuple(config.extraction.pack_phrases))
    return DocumentText(
        text=packed.text,
        chars_total=packed.chars_total,
        chars_sent=len(packed.text),
        windows_used=packed.windows_used,
        source_text=text,
    )


def document_text(config: Config, document: Document) -> str:
    """Read, convert and truncate a document's text for prompting."""
    return prepare_text(config, document).text


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
    review_queue.replace_rows(
        queue_target,
        document.document_id,
        model,
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
    queue_target = queue_path or resolve_data_path(config, config.extraction.review_queue_path)
    semaphore = asyncio.Semaphore(int(config.runtime.max_concurrency))
    stop: dict[str, object] = {'budget': False, 'auth': ''}
    outcomes: list[ExtractionOutcome] = []
    lock = asyncio.Lock()

    def prompt_variables(document: Document, text: str) -> dict[str, object]:
        """Return the template variables, including the vocabularies from config.

        The prompt is not allowed to carry its own copies of these lists: a value the
        prompt offers and the validator rejects teaches the model to fail.
        """
        return {
            'document_id': document.document_id,
            'document_text': text,
            'max_evidence_words': config.extraction.max_evidence_words,
            'themes': ', '.join(config.extraction.themes),
            'schema_version': config.extraction.schema_version,
            'eps_basis_vocab': ', '.join(config.extraction.eps_basis_vocab),
            'guidance_direction_vocab': ', '.join(config.extraction.guidance_direction_vocab),
            'tone_vocab': ', '.join(config.extraction.tone_vocab),
        }

    def _prompt_digest() -> str:
        static = {
            key: value
            for key, value in prompt_variables(Document('', '', '', '', Path(), ''), '').items()
            if key not in {'document_id', 'document_text'}
        }
        return prompt_hash(bundle, static)

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
            if stop['auth']:
                return ExtractionOutcome(
                    document.document_id, model, 'auth_failed', error=str(stop['auth'])
                )
            # Every model call goes through the one composition point, so retry,
            # Retry-After and the cache apply on the live path, not only in tests.
            caller = compose_caller(config, caller_factory(model))
            prepared = prepare_text(config, document)
            variables = prompt_variables(document, prepared.text)
            if prepared.truncated:
                # A cut document is not a clean success even when the record is: the
                # model answered about the part it was shown, not about the release.
                LOGGER.warning(
                    'document truncated document=%s sent=%d of %d chars (%.0f%%)',
                    document.document_id,
                    prepared.chars_sent,
                    prepared.chars_total,
                    100.0 * prepared.chars_sent / max(prepared.chars_total, 1),
                )
            try:
                parsed, raw_text, error = await asyncio.to_thread(
                    extract_structured,
                    caller,
                    model,
                    bundle,
                    variables,
                    ExtractionRecord,
                    int(config.extraction.max_repairs),
                )
                record: ExtractionRecord | None = (
                    parsed if isinstance(parsed, ExtractionRecord) else None
                )
            except BudgetExceeded:
                stop['budget'] = True
                return ExtractionOutcome(document.document_id, model, 'budget_stopped')
            except AuthError as exc:
                # A rejected credential fails every document identically: stop the run
                # once with the real cause instead of queueing N `llm_failed` rows.
                stop['auth'] = str(exc)
                return ExtractionOutcome(document.document_id, model, 'auth_failed', error=str(exc))
            except EmptyCompletion as exc:
                # The model returned nothing. Distinct from llm_failed so the queue says
                # what actually happened and the run summary can count it.
                reason = 'truncated' if isinstance(exc, TruncatedCompletion) else 'llm_failed'
                return _record_failure(queue_target, document, model, reason, str(exc))
            if record is None:
                return _record_failure(queue_target, document, model, 'llm_failed', error)
            record = record.model_copy(
                update={
                    'document_id': document.document_id,
                    'schema_version': config.extraction.schema_version,
                }
            )
            # Normalise before validating: the model copies numbers as printed, so a
            # fraction returned for "up 4%" is corrected to 4.0 first and then checked
            # against the quote. Validating first would penalise a value the code can
            # simply read correctly.
            record = normalise_record(record)
            source = str(variables['document_text'])
            issues, record = validate_record(record, source, config)
            reasons = needs_review(record, issues, config, truncated=prepared.truncated)
            diagnostics = {
                'chars_total': prepared.chars_total,
                'chars_sent': prepared.chars_sent,
                'truncated': prepared.truncated,
                'windows_used': prepared.windows_used,
            }
            # Replace, never append: a document that passed on this run must not keep a
            # row from a run where it did not.
            review_queue.replace_rows(
                queue_target,
                document.document_id,
                model,
                review_queue.rows_for_record(
                    document.document_id,
                    model,
                    reasons,
                    [(issue.field, issue.code) for issue in issues],
                ),
            )
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
                    'diagnostics': diagnostics,
                },
            )
            return ExtractionOutcome(
                document.document_id,
                model,
                'ok',
                review_reasons=tuple(reasons),
                truncated=prepared.truncated,
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
    if stop['auth']:
        raise AuthError(
            f'every call was rejected ({stop["auth"]}); the run stopped after '
            f'{len(outcomes)} document(s) instead of queueing them one by one'
        )
    return outcomes


SKIPPED_RESULTS: list[str] = []


def _load_result(config: Config, model: str, document_id: str) -> dict[str, Any] | None:
    """Load one stored result payload, returning None when absent or unreadable.

    A truncated or corrupted file is skipped and counted, not raised: one bad file must
    not abort consolidation after a long extraction run.
    """
    path = result_path(config, model, document_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning('skipping unreadable result path=%s', path)
        SKIPPED_RESULTS.append(str(path))
        return None
    if not isinstance(payload, dict) or 'document_id' not in payload:
        LOGGER.warning('skipping malformed result path=%s', path)
        SKIPPED_RESULTS.append(str(path))
        return None
    return payload


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
            if payload is not None and isinstance(payload.get('record'), dict):
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


def skipped_result_count() -> int:
    """Return how many result files consolidation and disagreement checks skipped."""
    return len(SKIPPED_RESULTS)


def consolidate(config: Config, models: list[str]) -> pd.DataFrame:
    """Write one parquet file per model holding every stored record.

    Columns are the union over all models: a theme or diagnostic present for one model
    and not the other must not disappear because the other model's frames were built
    first. Missing values are None ("not measured"), never False.
    """
    frames: list[pd.DataFrame] = []
    for model in models:
        directory = extractions_dir(config) / model_slug(model)
        rows: list[dict[str, Any]] = []
        for path in sorted(directory.glob('*.json')):
            payload = _load_result(config, model, path.stem)
            if payload is None:
                continue
            record = payload.get('record')
            if not isinstance(record, dict):
                LOGGER.warning('skipping result without a record path=%s', path)
                SKIPPED_RESULTS.append(str(path))
                continue
            row = {
                'document_id': payload['document_id'],
                'cik': payload.get('cik'),
                'report_date': payload.get('report_date'),
                'document_type': payload.get('document_type'),
                'model': model,
                'fingerprint': payload.get('fingerprint'),
            }
            # Results written before H5 carry no diagnostics; recording them as None
            # is honest ("not measured"), while False would claim the text was whole.
            diagnostics = payload.get('diagnostics') or {}
            row['chars_total'] = diagnostics.get('chars_total')
            row['chars_sent'] = diagnostics.get('chars_sent')
            row['truncated'] = diagnostics.get('truncated')
            row['windows_used'] = diagnostics.get('windows_used')
            row['fiscal_year'] = record.get('fiscal_year')
            row['fiscal_quarter'] = record.get('fiscal_quarter')
            row['currency'] = record.get('currency')
            row['units'] = record.get('units')
            for name in ('reported_eps', 'prior_year_eps', 'consensus_eps', 'revenue'):
                row[name] = (record.get(name) or {}).get('value')
            # Percent as printed (H5): 4.0 means 4%, so the column carries the unit in
            # its name instead of leaving every reader to assume one.
            row['revenue_yoy_growth_pct'] = (record.get('revenue_yoy_growth') or {}).get('value')
            for name in ('eps_basis', 'guidance_direction', 'guidance_metric', 'tone'):
                row[name] = (record.get(name) or {}).get('value')
            for theme in config.extraction.themes:
                mention = (record.get('theme_mentions') or {}).get(theme) or {}
                # Every configured theme gets a column for every model, so the frames
                # share a schema and a theme nobody mentioned is an explicit False.
                row[f'theme_{theme}_mentioned'] = bool(mention.get('mentioned'))
                row[f'theme_{theme}_direction'] = mention.get('direction')
            # Mean confidence of the fields that carry the record. Dedupe keys on this;
            # without it every duplicate was resolved by document id, silently.
            row['record_confidence'] = record_confidence(record)
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


CONFIDENCE_FIELDS = ('reported_eps', 'revenue', 'guidance_direction', 'tone')


def record_confidence(record: dict[str, Any]) -> float | None:
    """Return the mean confidence of the non-null core fields, or None when none exist."""
    values = [
        float((record.get(name) or {}).get('confidence') or 0.0)
        for name in CONFIDENCE_FIELDS
        if (record.get(name) or {}).get('value') is not None
    ]
    return round(sum(values) / len(values), 4) if values else None


CONSOLIDATED_NAME = EXTRACTION_PARQUET


def consolidated_path(config: Config) -> Path:
    """Return the combined extraction parquet path."""
    return extractions_dir(config) / CONSOLIDATED_NAME
