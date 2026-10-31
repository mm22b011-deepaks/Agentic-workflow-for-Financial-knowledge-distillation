"""Unit tests for the extraction runner."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nowcast.config import Config, extractions_dir, resolve_data_path
from nowcast.extraction import runner
from nowcast.extraction.review_queue import load_queue
from nowcast.extraction.runner import Document, run_extraction

REPLY = json.dumps(
    {
        'schema_version': 'v1',
        'document_id': 'x',
        'fiscal_year': 2026,
        'fiscal_quarter': 1,
        'currency': 'USD',
        'units': 'USD',
        'reported_eps': {
            'value': 0.55,
            'evidence_quote': 'earnings per share were $0.55',
            'confidence': 0.9,
        },
        'eps_basis': {
            'value': 'gaap',
            'evidence_quote': 'GAAP earnings per share',
            'confidence': 0.9,
        },
        'revenue': {
            'value': 1.2,
            'evidence_quote': 'Revenue was $1.20 billion',
            'confidence': 0.9,
        },
        'guidance_direction': {
            'value': 'maintained',
            'evidence_quote': 'Guidance was cut',
            'confidence': 0.8,
        },
    }
)
OTHER_REPLY = json.dumps(
    {
        **json.loads(REPLY),
        'guidance_direction': {
            'value': 'lowered',
            'evidence_quote': 'Guidance was cut',
            'confidence': 0.8,
        },
    }
)
SOURCE = 'Revenue was $1.20 billion. GAAP earnings per share were $0.55. Guidance was cut.'


def _documents(tmp_path: Path, count: int = 2) -> list[Document]:
    """Create document stubs whose raw files hold the same source text."""
    documents: list[Document] = []
    for index in range(count):
        path = tmp_path / f'doc{index}.txt'
        path.write_text(SOURCE, encoding='utf-8')
        documents.append(
            Document(
                document_id=f'doc{index}',
                cik='0000000001',
                report_date='2026-01-15',
                document_type='EX-99',
                raw_path=path,
                sha256=f'hash{index}',
            )
        )
    return documents


class CountingFakeCaller:
    """Caller that records calls and can fail on a given document."""

    def __init__(self, reply: str = REPLY, fail_document: str | None = None) -> None:
        self.reply = reply
        self.fail_document = fail_document
        self.calls: list[str] = []

    def complete(self, model: str, messages: list[dict[str, str]]) -> object:
        from nowcast.llm.caller import LLMResult

        content = '\n'.join(message['content'] for message in messages)
        for marker in ('doc0', 'doc1', 'doc2', 'doc3'):
            # The user template marks the document with either spelling.
            if f'document_id={marker}' in content or f'<document id="{marker}">' in content:
                self.calls.append(marker)
                if self.fail_document == marker:
                    raise RuntimeError('simulated failure')
                break
        return LLMResult(text=self.reply, model=model)


def _run(config: Config, documents: list[Document], caller: CountingFakeCaller, models=None):
    """Drive run_extraction with one shared fake caller."""
    return asyncio.run(
        run_extraction(
            config,
            documents,
            caller_factory=lambda _model: caller,
            models=models or [config.llm.models[0]],
            queue_path=resolve_data_path(config, config.extraction.review_queue_path),
        )
    )


def test_runner_skips_completed_documents(config: Config, tmp_path: Path) -> None:
    """A second run over the same inputs makes no new model calls."""
    documents = _documents(tmp_path)
    caller = CountingFakeCaller()
    _run(config, documents, caller)
    first_calls = len(caller.calls)
    second = _run(config, documents, caller)
    assert len(caller.calls) == first_calls
    assert all(outcome.skipped for outcome in second)


def test_runner_writes_results(config: Config, tmp_path: Path) -> None:
    """Each document produces a result file and a consolidated parquet."""
    documents = _documents(tmp_path)
    _run(config, documents, CountingFakeCaller())
    model_dir = extractions_dir(config) / runner.model_slug(config.llm.models[0])
    assert len(list(model_dir.glob('*.json'))) == 2
    parquet = extractions_dir(config) / f'{runner.model_slug(config.llm.models[0])}.parquet'
    assert parquet.is_file()


def test_runner_survives_one_bad_document(config: Config, tmp_path: Path) -> None:
    """One failing document is queued as llm_failed while the rest succeed."""
    documents = _documents(tmp_path)
    caller = CountingFakeCaller(fail_document='doc1')
    outcomes = _run(config, documents, caller)
    statuses = {outcome.document_id: outcome.status for outcome in outcomes}
    assert statuses == {'doc0': 'ok', 'doc1': 'failed'}
    queue = load_queue(resolve_data_path(config, config.extraction.review_queue_path))
    assert 'llm_failed' in set(queue['reason'])


def test_runner_stops_on_budget_and_keeps_results(config: Config, tmp_path: Path) -> None:
    """BudgetExceeded stops remaining work but keeps completed results."""
    from nowcast.errors import BudgetExceeded

    documents = _documents(tmp_path, count=3)
    processed: list[str] = []

    class BudgetCaller(CountingFakeCaller):
        def complete(self, model: str, messages: list[dict[str, str]]) -> object:
            if len(processed) >= 1:
                raise BudgetExceeded('cap reached')
            result = super().complete(model, messages)
            processed.append('x')
            return result

    outcomes = _run(config, documents, BudgetCaller())
    accepted = [outcome for outcome in outcomes if outcome.status == 'ok']
    stopped = [outcome for outcome in outcomes if outcome.status == 'budget_stopped']
    # 'either budget_stopped or failed' could never fail on the original bug: assert
    # the exact behaviour, and that the work already done is still on disk.
    assert accepted, 'the run must keep the documents it completed'
    assert stopped, 'the remaining documents must stop on the budget, not fail'
    assert not [outcome for outcome in outcomes if outcome.status == 'failed']
    assert len(accepted) + len(stopped) == len(outcomes)


def test_model_disagreement_queued(config: Config, tmp_path: Path) -> None:
    """Differing guidance across configured models lands in the review queue."""
    documents = _documents(tmp_path, count=1)
    callers = {
        'model-a:free': CountingFakeCaller(REPLY),
        'model-b:free': CountingFakeCaller(OTHER_REPLY),
    }
    asyncio.run(
        run_extraction(
            config,
            documents,
            caller_factory=lambda model: callers[model],
            models=['model-a:free', 'model-b:free'],
            queue_path=resolve_data_path(config, config.extraction.review_queue_path),
        )
    )
    queue = load_queue(resolve_data_path(config, config.extraction.review_queue_path))
    assert 'model_disagreement' in set(queue['reason'])


def test_runner_rejects_non_free_model(config: Config, tmp_path: Path) -> None:
    """A paid model id is refused before any call is made."""
    from nowcast.errors import ConfigError
    from nowcast.llm.caller import LLMCaller

    caller = LLMCaller(config.llm)
    try:
        with pytest.raises(ConfigError):
            caller.complete('paid/model', [{'role': 'user', 'content': 'x'}])
    finally:
        caller.close()


def test_load_documents_skips_non_text_files(config: Config, tmp_path: Path) -> None:
    """A stale index entry pointing at a scan is dropped before it reaches a prompt."""
    import pandas as pd

    index = pd.DataFrame(
        [
            {
                'document_id': 'doc-a',
                'cik': '0000000001',
                'report_date': '2025-01-30',
                'document_type': 'EX-99.1',
                'source': 'edgar',
                'raw_path': 'raw/0000000001/a/dex991.htm',
                'sha256': 'x',
                'chars': 10,
                'downloaded_at': '2025-01-30T00:00:00+00:00',
                'items': '2.02,9.01',
            },
            {
                'document_id': 'doc-b',
                'cik': '0000000001',
                'report_date': '2025-01-30',
                'document_type': 'EX-99.1',
                'source': 'edgar',
                'raw_path': 'raw/0000000001/a/ex991001.jpg',
                'sha256': 'y',
                'chars': 10,
                'downloaded_at': '2025-01-30T00:00:00+00:00',
                'items': '2.02,9.01',
            },
        ]
    )
    path = tmp_path / 'index.parquet'
    index.to_parquet(path, index=False)

    from nowcast.extraction.runner import load_documents

    documents = load_documents(config, path)
    assert [document.document_id for document in documents] == ['doc-a']


def _write_index(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    """Write a document index holding the given rows."""
    import pandas as pd

    path = tmp_path / 'index.parquet'
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _index_row(document_id: str, path: str, items: str) -> dict[str, object]:
    """Build one index row for a text document with the given 8-K items."""
    return {
        'document_id': document_id,
        'cik': '0000000001',
        'report_date': '2025-01-30',
        'document_type': 'EX-99.1',
        'source': 'edgar',
        'raw_path': path,
        'sha256': document_id,
        'chars': 10,
        'downloaded_at': '2025-01-30T00:00:00+00:00',
        'items': items,
    }


def test_non_earnings_document_not_extracted(config: Config, tmp_path: Path) -> None:
    """A filing without Item 2.02 is not an earnings release and never reaches a prompt."""
    from nowcast.extraction.runner import load_documents

    path = _write_index(
        tmp_path,
        [
            _index_row('earnings', 'raw/1/a/earnings.htm', '2.02,9.01'),
            _index_row('dividend', 'raw/1/b/dividend.htm', '8.01'),
            _index_row('unknown', 'raw/1/c/unknown.htm', ''),
        ],
    )
    documents = load_documents(config, path)
    assert [document.document_id for document in documents] == ['earnings']


def test_index_written_before_items_column_is_not_extracted(config: Config, tmp_path: Path) -> None:
    """A pre-v2 index carries no item proof, so its rows are refused rather than guessed."""
    import pandas as pd

    from nowcast.extraction.runner import load_documents

    path = tmp_path / 'old_index.parquet'
    pd.DataFrame(
        [
            {
                'document_id': 'old',
                'cik': '0000000001',
                'report_date': '2025-01-30',
                'document_type': 'EX-99',
                'source': 'edgar',
                'raw_path': 'raw/1/a/old.htm',
                'sha256': 'x',
                'chars': 10,
                'downloaded_at': '2025-01-30T00:00:00+00:00',
            }
        ]
    ).to_parquet(path, index=False)
    assert load_documents(config, path) == []


def test_runner_survives_missing_raw_file_and_write_error(config: Config, tmp_path: Path) -> None:
    """A missing raw file and an unwritable result both fail one document, not the run."""
    documents = _documents(tmp_path, count=3)
    documents[0].raw_path = tmp_path / 'gone.txt'  # never written
    caller = CountingFakeCaller()

    original = runner._write_result
    writes: list[str] = []

    def failing_write(path: Path, payload: dict[str, object]) -> None:
        if path.name.startswith('doc2'):
            raise OSError('disk full')
        writes.append(path.name)
        original(path, payload)

    runner._write_result = failing_write  # type: ignore[assignment]
    try:
        outcomes = _run(config, documents, caller)
    finally:
        runner._write_result = original  # type: ignore[assignment]

    statuses = {outcome.document_id: outcome.status for outcome in outcomes}
    assert statuses == {'doc0': 'failed', 'doc1': 'ok', 'doc2': 'failed'}
    assert {outcome.document_id for outcome in outcomes if outcome.status == 'ok'} == {'doc1'}
    queue = load_queue(resolve_data_path(config, config.extraction.review_queue_path))
    assert 'document_error' in set(queue['reason'])


def test_changing_threshold_invalidates_or_revalidates(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing a validation setting or the text cut must not resume an old record."""
    import dataclasses

    from nowcast.extraction.runner import fingerprint

    document = _documents(tmp_path, count=1)[0]
    base = fingerprint(config, document, 'model:free', 'prompt-digest')

    def changed(section: str, **updates: object) -> object:
        return dataclasses.replace(
            config, **{section: dataclasses.replace(getattr(config, section), **updates)}
        )

    variants = {
        'max_doc_chars': changed('extraction', max_doc_chars=12000),
        'min_confidence': changed('extraction', min_confidence=0.7),
        'quote_match_min_ratio': changed('extraction', quote_match_min_ratio=0.5),
        'confidence_penalty_on_issue': changed('extraction', confidence_penalty_on_issue=0.5),
        'eps_tolerance_abs': changed('extraction', eps_tolerance_abs=0.05),
        'max_evidence_words': changed('extraction', max_evidence_words=10),
        'themes': changed('extraction', themes=('demand',)),
        'section_patterns': changed('parsing', section_patterns={'mda': 'x'}),
    }
    for name, variant in variants.items():
        digest = fingerprint(variant, document, 'model:free', 'prompt-digest')  # type: ignore[arg-type]
        assert digest != base, f'changing {name} did not invalidate the fingerprint'

    # The same settings on a copy must produce the same fingerprint: the check above
    # would pass even if the digest were random.
    same = changed('extraction', max_doc_chars=int(config.extraction.max_doc_chars))
    assert fingerprint(same, document, 'model:free', 'prompt-digest') == base  # type: ignore[arg-type]
