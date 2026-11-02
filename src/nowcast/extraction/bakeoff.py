"""Model bakeoff: the same real releases through every configured free model.

One model choice made from a benchmark of candidates, not from a hunch: empty-completion
rate, parse success, per-field coverage and latency, on the same documents, so the costs
of a weak free model are visible before a 500-document run pays for them.
"""

from __future__ import annotations

import asyncio
import dataclasses
import statistics
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from nowcast.config import Config, extractions_dir, prompts_dir, resolve_data_path
from nowcast.extraction.runner import (
    Document,
    consolidate,
    load_documents,
    run_extraction,
)
from nowcast.extraction.selection import describe, stratified_sample

FIELDS = ('reported_eps', 'prior_year_eps', 'revenue', 'guidance_direction', 'tone')


@dataclass
class ModelScore:
    """One model's measured behaviour over the bakeoff documents."""

    model: str
    documents: int = 0
    ok: int = 0
    empty: int = 0
    failed: int = 0
    cached_or_skipped: int = 0
    latencies: list[float] = field(default_factory=list)
    requests: int = 0
    http_attempts: int = 0
    cache_hits: int = 0
    nonempty: int = 0
    throttled: int = 0
    tokens: int = 0
    accuracy: dict[str, float] | None = None
    coverage: dict[str, int] = field(default_factory=dict)
    unvisited: int = 0
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the score as a flat record for the report."""
        total = self.documents or 1
        coverage = {name: round(self.coverage.get(name, 0) / total, 4) for name in FIELDS}
        return {
            'model': self.model,
            'documents': self.documents,
            'unvisited': self.unvisited,
            'execution_complete': self.unvisited == 0,
            'ok': self.ok,
            'empty_completion_rate': round(self.empty / total, 4),
            'failed_rate': round(self.failed / total, 4),
            'parse_success_rate': round(self.ok / total, 4),
            'coverage': coverage,
            'requests': self.requests,
            'http_attempts': self.http_attempts,
            'cache_hits': self.cache_hits,
            'nonempty_extractions': self.nonempty,
            'throttled': self.throttled,
            'tokens': self.tokens,
            'completion_tokens': self.completion_tokens,
            'reasoning_tokens': self.reasoning_tokens,
            'accuracy': self.accuracy,
            'latency_p95_seconds': float(np.percentile(self.latencies, 95))
            if self.latencies
            else None,
            'latency_p50_seconds': round(statistics.median(self.latencies), 2)
            if self.latencies
            else None,
        }


def _scope_documents(config: Config, documents: list[Document]) -> list[Document]:
    from nowcast.scope import select_documents

    return select_documents(config, documents)


def documents_for(config: Config, index: Path, count: int) -> list[Document]:
    """Return the same stratified sample every candidate model is measured on."""
    sample = stratified_sample(
        _scope_documents(config, load_documents(config, index)),
        count,
        int(config.aggregation.sample_seed),
    )
    return sample


def score_model(
    config: Config,
    model: str,
    documents: list[Document],
    caller_factory: Any,
    ledger: Any = None,
    labels: Path | None = None,
) -> ModelScore:
    """Extract `documents` with one model and aggregate the outcome counts."""
    score = ModelScore(model=model, documents=len(documents))
    outcomes = asyncio.run(
        run_extraction(
            config,
            documents,
            caller_factory=caller_factory,
            models=[model],
            queue_path=resolve_data_path(config, config.extraction.review_queue_path),
        )
    )
    for outcome in outcomes:
        if outcome.status == 'budget_stopped':
            score.unvisited += 1
        elif outcome.status == 'ok':
            score.ok += 1
        elif outcome.status == 'skipped':
            score.cached_or_skipped += 1
        elif outcome.truncated or 'truncated' in outcome.review_reasons:
            score.empty += 1
        else:
            score.failed += 1
    measured = score_existing(config, model, documents, ledger, labels)
    measured.unvisited = score.unvisited
    measured.ok = score.ok + score.cached_or_skipped
    measured.empty = score.empty
    measured.failed = score.failed
    measured.cached_or_skipped = score.cached_or_skipped
    return measured


def score_existing(
    config: Config,
    model: str,
    documents: list[Document],
    ledger: Any = None,
    labels: Path | None = None,
) -> ModelScore:
    """Read durable results and attempts without issuing a request."""
    import pandas as pd

    from nowcast.extraction.review_queue import affected_fields, load_queue

    score = ModelScore(model=model, documents=len(documents))
    ids = {document.document_id for document in documents}
    attempted: set[str] = set()
    if ledger is not None:
        ledger.flush()
        import pandas as pd

        from nowcast.llm.ledger import LEDGER_COLUMNS

        attempts = (
            pd.read_parquet(ledger._path)
            if ledger._path.exists()
            else pd.DataFrame(columns=LEDGER_COLUMNS)
        )
        if 'document_id' in attempts:
            attempted.update(set(attempts.document_id.dropna().astype(str)) & ids)
        score.http_attempts = int(attempts.request_kind.ne('cache').sum())
        score.cache_hits = int(attempts.request_kind.eq('cache').sum())
        attempts = attempts[attempts.request_kind.eq('completion')]
        score.requests = len(attempts)
        score.tokens = int(attempts.total_tokens.sum())
        for name in ('completion_tokens', 'reasoning_tokens'):
            values = pd.to_numeric(
                attempts.get(name, pd.Series(dtype=float)), errors='coerce'
            ).dropna()
            setattr(score, name, int(values.sum()) if len(values) else None)
        score.throttled = int(attempts.status_code.eq(429).sum())
        score.latencies = list(attempts.latency_seconds.dropna())
    frame = consolidate(config, [model])
    if not frame.empty:
        frame = frame[frame.document_id.isin(ids)].drop_duplicates('document_id')
        attempted.update(frame.document_id)
        score.ok = len(frame)
    effects: dict[str, set[str]] = {}
    for issue in load_queue(resolve_data_path(config, config.extraction.review_queue_path)).to_dict(
        'records'
    ):
        if issue['model'] == model:
            effects.setdefault(issue['document_id'], set()).update(
                affected_fields(issue['field'], issue['reason'])
            )
    for row in frame.to_dict('records'):
        excluded = effects.get(row['document_id'], set())
        usable = {
            name
            for name in FIELDS
            if 'record' not in excluded and name not in excluded and pd.notna(row.get(name))
        }
        score.nonempty += bool(usable & {'reported_eps', 'revenue'})
        for name in usable:
            score.coverage[name] = score.coverage.get(name, 0) + 1
    score.unvisited = max(0, len(ids) - len(attempted))
    score.failed = max(0, len(attempted) - score.ok)
    if labels is not None:
        score.accuracy = score_labels(frame, labels)

    return score


def run_bakeoff(
    config: Config,
    models: list[str],
    index: Path,
    count: int,
    labels: Path | None = None,
) -> dict[str, Any]:
    """Measure every candidate on the same documents and return the table."""
    documents = documents_for(config, index, count)
    from nowcast.config import manifests_dir
    from nowcast.llm.composition import make_caller
    from nowcast.llm.ledger import BudgetLedger

    run_root = manifests_dir(config) / 'bakeoff' / uuid.uuid4().hex
    run_root.mkdir(parents=True)
    isolated = dataclasses.replace(
        config,
        paths=dataclasses.replace(config.paths, extractions_dir=str(run_root / 'extractions')),
        extraction=dataclasses.replace(
            config.extraction, review_queue_path=str(run_root / 'review_queue.parquet')
        ),
    )
    from nowcast.storage import atomic_json

    scores = [
        ModelScore(model=model, documents=len(documents), unvisited=len(documents))
        for model in models
    ]
    result = {
        'run_directory': str(run_root),
        'documents': describe(documents),
        'seed': int(config.aggregation.sample_seed),
        'models': [],
        'extractions_dir': str(extractions_dir(isolated)),
        'prompts_dir': str(prompts_dir(config)),
        'execution_complete': False,
    }
    for position, model in enumerate(models):
        ledger = BudgetLedger(
            run_root / (model.replace('/', '__').replace(':', '-') + '.ledger.parquet'),
            config.budget.max_usd,
        )
        shared: dict[str, Any] = {}

        def factory(
            _model: str, shared: dict[str, Any] = shared, ledger: BudgetLedger = ledger
        ) -> Any:
            if 'caller' not in shared:
                shared['caller'] = make_caller(isolated, ledger=ledger)
            return shared['caller']

        try:
            scores[position] = score_model(
                isolated, model, documents, factory, ledger=ledger, labels=labels
            )
        except Exception as exc:
            scores[position] = score_existing(isolated, model, documents, ledger, labels)
            result['error_kind'] = type(exc).__name__
            raise
        finally:
            caller = shared.get('caller')
            if caller is not None:
                caller.close()
            ledger.flush()
            result['models'] = [score.as_dict() for score in scores]
            result['execution_complete'] = (
                all(score.unvisited == 0 for score in scores) and 'error_kind' not in result
            )
            atomic_json(result, run_root / 'scores.json')

    return result


def score_labels(frame: Any, labels: Path) -> dict[str, float]:
    """Score supplied labels only; absent/unlabelled documents cannot become successes."""
    import pandas as pd

    truth = pd.read_csv(labels)
    if 'document_id' not in truth or len(truth.document_id.unique()) < 10:
        raise ValueError('bakeoff accuracy needs at least ten labelled releases')
    if truth.document_id.isna().any() or not truth.document_id.is_unique:
        raise ValueError('labelled releases must have unique document identifiers')
    predictions = frame.reindex(columns=['document_id', *FIELDS])
    if not predictions.empty and not predictions.document_id.is_unique:
        raise ValueError('accuracy requires one prediction per release')
    joined = truth.merge(predictions, on='document_id', how='left', suffixes=('_label', '_model'))
    scores = {}
    for name in FIELDS:
        if name + '_label' not in joined:
            continue
        usable = joined[name + '_label'].notna()
        if usable.any():
            scores[name] = float(
                joined.loc[usable, name + '_label']
                .eq(joined.loc[usable, name + '_model'])
                .fillna(False)
                .mean()
            )
    return scores
