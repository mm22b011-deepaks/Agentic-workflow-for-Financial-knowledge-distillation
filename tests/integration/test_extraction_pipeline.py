"""C2: three fixture documents through parse, extract, validate and consolidate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import Config, load_config
from nowcast.extraction.runner import (
    consolidate,
    document_text,
    load_documents,
    run_extraction,
)
from nowcast.ingestion.local_adapter import index_manifest
from nowcast.llm.caller import LLMResult

REPO = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO / 'tests' / 'fixtures' / 'documents'
MODEL = 'fixture/model:free'


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Load the project config with DATA_DIR pointed at a temp directory."""
    data = tmp_path / 'data'
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('DATA_DIR', str(data))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    return load_config(
        REPO / 'configs' / 'config.yaml',
        overrides={
            'data.start_date': '2025-01-01',
            'data.end_date': '2025-12-31',
            'extraction.themes': 'demand,pricing',
        },
    )


def _manifest(tmp_path: Path) -> Path:
    """Write a local manifest pointing at the three fixture documents."""
    rows = [
        {
            'document_id': f'doc-fixture-{index:03d}',
            'cik': f'000000000{index}',
            'report_date': date,
            'document_type': '8-K-EX99',
            'path': str(FIXTURES / f'doc-fixture-{index:03d}.htm'),
            'source': 'fixture',
            # These are earnings releases, so the index must say so: extraction now
            # refuses a row whose items do not include the configured earnings item.
            'items': '2.02,9.01',
        }
        for index, date in ((1, '2025-04-24'), (2, '2025-07-25'), (3, '2025-10-24'))
    ]
    path = tmp_path / 'local_manifest.csv'
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


class FixtureCaller:
    """Return the canned extraction record matching the document named in the prompt."""

    def __init__(self, records: dict[str, dict]) -> None:
        """Store canned records and reset the call log."""
        self.records = records
        self.calls: list[str] = []

    def complete(self, model: str, messages: list[dict[str, str]]) -> LLMResult:
        """Echo the record whose document_id appears in the user message."""
        text = '\n'.join(message['content'] for message in messages)
        for document_id in self.records:
            if document_id in text:
                self.calls.append(document_id)
                return LLMResult(text=json.dumps(self.records[document_id]), model=model)
        raise AssertionError('prompt did not name any known fixture document')


def test_fixture_documents_index_parse_and_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole Phase 3 path runs on three documents without touching the network."""
    config = _config(tmp_path, monkeypatch)
    records = json.loads((FIXTURES / 'records.json').read_text(encoding='utf-8'))

    index_path = tmp_path / 'data' / 'document_index.parquet'
    rows = index_manifest(config, _manifest(tmp_path))
    pd.DataFrame(rows).to_parquet(index_path, index=False)

    documents = load_documents(config, index_path)
    assert len(documents) == 3
    assert all(row['chars'] > 0 for row in rows)

    # The fixtures carry <style>, <script> and an HTML comment; none may reach the prompt.
    prompts = {document.document_id: document_text(config, document) for document in documents}
    assert 'font:12px' not in prompts['doc-fixture-001']
    assert 'internal drafting note' not in prompts['doc-fixture-001']
    assert 'tracking' not in prompts['doc-fixture-003']
    assert 'GAAP diluted earnings per share were $0.55' in prompts['doc-fixture-001']

    caller = FixtureCaller(records)
    outcomes = asyncio.run(run_extraction(config, documents, lambda _model: caller, [MODEL]))

    assert {outcome.status for outcome in outcomes} == {'ok'}
    assert len(caller.calls) == 3

    combined = consolidate(config, [MODEL])
    assert len(combined) == 3
    by_id = combined.set_index('document_id')
    assert by_id.loc['doc-fixture-001', 'reported_eps'] == pytest.approx(0.55)
    assert by_id.loc['doc-fixture-001', 'prior_year_eps'] == pytest.approx(0.48)
    assert by_id.loc['doc-fixture-002', 'guidance_direction'] == 'raised'
    assert by_id.loc['doc-fixture-003', 'reported_eps'] == pytest.approx(-0.12)
    # H5: the fixture's model reply says 0.08 for "up 8%"; the stored frame is percent
    # as printed. A pre-corrected fixture would not prove the correction runs.
    assert by_id.loc['doc-fixture-001', 'revenue_yoy_growth_pct'] == pytest.approx(8.0)
    # A theme that was never mentioned still gets a column, set false.
    assert not bool(by_id.loc['doc-fixture-003', 'theme_demand_mentioned'])
    assert bool(by_id.loc['doc-fixture-001', 'theme_demand_mentioned'])


def test_second_run_is_a_resume_not_a_second_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running twice over the same documents makes no new LLM calls."""
    config = _config(tmp_path, monkeypatch)
    records = json.loads((FIXTURES / 'records.json').read_text(encoding='utf-8'))
    index_path = tmp_path / 'data' / 'document_index.parquet'
    pd.DataFrame(index_manifest(config, _manifest(tmp_path))).to_parquet(index_path, index=False)
    documents = load_documents(config, index_path)

    first = FixtureCaller(records)
    asyncio.run(run_extraction(config, documents, lambda _model: first, [MODEL]))
    assert len(first.calls) == 3

    second = FixtureCaller(records)
    outcomes = asyncio.run(run_extraction(config, documents, lambda _model: second, [MODEL]))
    assert second.calls == []
    assert {outcome.status for outcome in outcomes} == {'skipped'}


def test_unparseable_reply_goes_to_the_review_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model that never returns valid JSON fails the document and queues it, not the run."""
    config = _config(tmp_path, monkeypatch)
    index_path = tmp_path / 'data' / 'document_index.parquet'
    pd.DataFrame(index_manifest(config, _manifest(tmp_path))).to_parquet(index_path, index=False)
    documents = load_documents(config, index_path)[:1]

    class BadCaller:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, model: str, messages: list[dict[str, str]]) -> LLMResult:
            self.calls += 1
            return LLMResult(text='I am unable to answer that.', model=model)

    bad = BadCaller()
    outcomes = asyncio.run(run_extraction(config, documents, lambda _model: bad, [MODEL]))
    assert outcomes[0].status == 'failed'
    # One attempt plus the configured repair turns.
    assert bad.calls == 1 + int(config.extraction.max_repairs)

    queue = pd.read_parquet(tmp_path / 'data' / 'extractions' / 'review_queue.parquet')
    assert set(queue['reason']) == {'llm_failed'}
    assert len(queue) == 1
