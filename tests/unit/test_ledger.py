"""Unit tests for the budget ledger."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.errors import BudgetExceeded
from nowcast.llm.caller import LLMResult
from nowcast.llm.ledger import BudgetLedger


def _usage(cost: float, tokens: int = 10) -> LLMResult:
    """Build a canned LLMResult with a given cost."""
    return LLMResult(text='x', model='m:free', total_tokens=tokens, cost_usd=cost)


def test_ledger_total_and_parquet(tmp_path: Path) -> None:
    """Recorded calls accumulate and flush to a parquet file with the fixed schema."""
    ledger = BudgetLedger(tmp_path / 'ledger.parquet', max_usd=1.0)
    ledger.record('m:free', _usage(0.02))
    ledger.record('m:free', _usage(0.03))
    ledger.flush()
    assert ledger.total_usd == pytest.approx(0.05)
    frame = pd.read_parquet(tmp_path / 'ledger.parquet')
    assert list(frame.columns) == [
        'timestamp',
        'model',
        'prompt_tokens',
        'completion_tokens',
        'total_tokens',
        'cost_usd',
        'max_tokens',
        'finish_reason',
        'outcome',
        'cached',
        'reasoning_tokens',
        'content_tokens',
        'latency_seconds',
        'status_code',
        'attempt_id',
        'request_kind',
        'request_id',
        'retry_number',
        'document_id',
    ]
    assert len(frame) == 2
    # The budget each call ran under is recorded, so a truncated reply is visible.
    assert frame['max_tokens'].tolist() == [0, 0]
    reloaded = BudgetLedger(tmp_path / 'ledger.parquet', max_usd=1.0)
    assert reloaded.total_usd == pytest.approx(0.05)


def test_budget_exceeded_raises(tmp_path: Path) -> None:
    """Spending past the cap raises BudgetExceeded."""
    ledger = BudgetLedger(tmp_path / 'ledger.parquet', max_usd=0.01)
    ledger.record('m:free', _usage(0.02))
    with pytest.raises(BudgetExceeded):
        ledger.check_budget()


def test_ledger_empty_flush_writes_schema(tmp_path: Path) -> None:
    """Flushing with no calls still writes an empty file with the schema."""
    ledger = BudgetLedger(tmp_path / 'ledger.parquet', max_usd=1.0)
    ledger.flush()
    frame = pd.read_parquet(tmp_path / 'ledger.parquet')
    assert frame.empty
    assert 'cost_usd' in frame.columns


def test_ledger_records_are_thread_safe(tmp_path: Path) -> None:
    """Concurrent records never lose or duplicate a row or a dollar of spend."""
    import threading

    ledger = BudgetLedger(tmp_path / 'ledger.parquet', max_usd=1000.0)
    per_call = 0.001
    result = LLMResult(text='x', model='m', cost_usd=per_call)

    def worker() -> None:
        for _ in range(100):
            ledger.record('m:free', result)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ledger.flush()
    frame = pd.read_parquet(tmp_path / 'ledger.parquet')
    assert len(frame) == 800
    assert ledger.total_usd == pytest.approx(800 * per_call)
    assert frame['cost_usd'].sum() == pytest.approx(800 * per_call)


def test_two_process_views_do_not_overwrite_attempts(tmp_path: Path) -> None:
    path = tmp_path / 'ledger.parquet'
    first = BudgetLedger(path, 1)
    second = BudgetLedger(path, 1)
    first.record('a:free', _usage(0.01))
    second.record('b:free', _usage(0.02))
    first.flush()
    second.flush()
    first.flush()
    frame = pd.read_parquet(path)
    assert len(frame) == 2
    assert set(frame.model) == {'a:free', 'b:free'}
