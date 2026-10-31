"""Model bakeoff: the same real releases through every configured free model.

One model choice made from a benchmark of candidates, not from a hunch: empty-completion
rate, parse success, per-field coverage and latency, on the same documents, so the costs
of a weak free model are visible before a 500-document run pays for them.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nowcast.config import Config, extractions_dir, prompts_dir, resolve_data_path
from nowcast.errors import AuthError, BudgetExceeded, EmptyCompletion
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
    coverage: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the score as a flat record for the report."""
        total = self.documents or 1
        coverage = {name: round(self.coverage.get(name, 0) / total, 4) for name in FIELDS}
        return {
            'model': self.model,
            'documents': self.documents,
            'ok': self.ok,
            'empty_completion_rate': round(self.empty / total, 4),
            'failed_rate': round(self.failed / total, 4),
            'parse_success_rate': round(self.ok / total, 4),
            'coverage': coverage,
            'requests': self.requests,
            'latency_p50_seconds': round(statistics.median(self.latencies), 2)
            if self.latencies
            else None,
        }


def documents_for(config: Config, index: Path, count: int) -> list[Document]:
    """Return the same stratified sample every candidate model is measured on."""
    sample = stratified_sample(
        load_documents(config, index), count, int(config.aggregation.sample_seed)
    )
    return sample


def score_model(
    config: Config,
    model: str,
    documents: list[Document],
    caller_factory: Any,
) -> ModelScore:
    """Extract `documents` with one model and aggregate the outcome counts."""
    score = ModelScore(model=model, documents=len(documents))
    started = time.monotonic()
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
        if outcome.status == 'ok':
            score.ok += 1
        elif outcome.status == 'skipped':
            score.cached_or_skipped += 1
        elif outcome.truncated or 'truncated' in outcome.review_reasons:
            score.empty += 1
        else:
            score.failed += 1
    elapsed = time.monotonic() - started
    # Requests per document, measured from the ledger the caller writes: a model that
    # retries its way through every document is expensive even when its replies parse.
    ledger = getattr(caller_factory(''), '_ledger', None)
    score.requests = int(getattr(ledger, 'rows_recorded', lambda: 0)())
    score.latencies.append(elapsed / max(len(documents), 1))
    frame = consolidate(config, [model])
    for name in FIELDS:
        if frame.empty or name not in frame.columns:
            continue
        score.coverage[name] = int(frame[name].notna().sum())
    return score


def run_bakeoff(
    config: Config,
    models: list[str],
    index: Path,
    count: int,
) -> dict[str, Any]:
    """Measure every candidate on the same documents and return the table."""
    documents = documents_for(config, index, count)
    from nowcast.llm.composition import make_caller

    scores: list[ModelScore] = []
    for model in models:
        shared: dict[str, Any] = {}

        def factory(_model: str, shared: dict[str, Any] = shared) -> Any:
            if 'caller' not in shared:
                shared['caller'] = make_caller(config)
            return shared['caller']

        try:
            scores.append(score_model(config, model, documents, factory))
        except (AuthError, EmptyCompletion, BudgetExceeded) as exc:
            # A model that cannot answer at all is a result, not a reason to lose the run.
            score = ModelScore(model=model, documents=len(documents), failed=len(documents))
            score.model = f'{model} ({type(exc).__name__}: {str(exc)[:80]})'
            scores.append(score)
        finally:
            caller = shared.get('caller')
            inner = getattr(caller, '_caller', None)
            if inner is not None:
                inner.close()
    return {
        'documents': describe(documents),
        'seed': int(config.aggregation.sample_seed),
        'models': [score.as_dict() for score in scores],
        'extractions_dir': str(extractions_dir(config)),
        'prompts_dir': str(prompts_dir(config)),
    }
