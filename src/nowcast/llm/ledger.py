"""Spend ledger with a hard budget cap."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from nowcast.errors import BudgetExceeded

if TYPE_CHECKING:
    from nowcast.llm.caller import LLMResult

LOGGER = logging.getLogger(__name__)
LEDGER_COLUMNS = [
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
]


class BudgetLedger:
    """Tracks cumulative spend and refuses calls past the configured cap."""

    def __init__(self, path: Path | str, max_usd: float) -> None:
        """Point the ledger at a parquet file and set the spend cap."""
        self._path = Path(path)
        self._max_usd = float(max_usd)
        self._rows: list[dict[str, Any]] = []
        self._total = 0.0
        # Extraction runs many calls from a thread pool; every read-modify-write of
        # the running total must hold this lock or spend can be lost or double-counted.
        self._lock = threading.RLock()
        if self._path.is_file():
            existing = pd.read_parquet(self._path)
            if 'cost_usd' in existing.columns:
                self._total = float(existing['cost_usd'].sum())
                self._rows = [
                    {str(key): value for key, value in row.items()}
                    for row in existing.to_dict('records')
                ]

    @property
    def total_usd(self) -> float:
        """Return the cumulative spend in US dollars."""
        with self._lock:
            return self._total

    def rows_recorded(self) -> int:
        """Return how many calls the ledger holds; a count, not the rows themselves."""
        with self._lock:
            return len(self._rows)

    @property
    def max_usd(self) -> float:
        """Return the configured spend cap."""
        return self._max_usd

    def check_budget(self) -> None:
        """Raise BudgetExceeded when cumulative spend has reached the cap."""
        with self._lock:
            total = self._total
        if total >= self._max_usd:
            raise BudgetExceeded(f'budget exhausted: {total:.6f} >= {self._max_usd:.6f} USD')

    def record(
        self,
        model: str,
        usage: LLMResult,
        max_tokens: int = 0,
        finish_reason: str = '',
        outcome: str = 'ok',
    ) -> None:
        """Append one call to the in-memory ledger.

        `max_tokens`, `finish_reason` and `outcome` are recorded next to the completion
        size so a budget-exhausted reply (completion_tokens == max_tokens, empty content)
        is visible in the data, and a call that raised is still counted: the calls that
        fail are exactly the ones a cost or truncation analysis needs.
        """
        row = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'model': model,
            'prompt_tokens': usage.prompt_tokens,
            'completion_tokens': usage.completion_tokens,
            'total_tokens': usage.total_tokens,
            'cost_usd': float(usage.cost_usd),
            'max_tokens': int(max_tokens),
            'finish_reason': finish_reason,
            'outcome': outcome,
            'cached': bool(getattr(usage, 'cached', False)),
        }
        with self._lock:
            self._rows.append(row)
            self._total += float(usage.cost_usd)

    def flush(self) -> None:
        """Write the ledger to parquet, preserving the schema even when empty."""
        with self._lock:
            rows = list(self._rows)
            total = self._total
        self._path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(rows, columns=LEDGER_COLUMNS)
        frame.to_parquet(self._path, index=False)
        LOGGER.info('ledger flushed rows=%d total_usd=%.6f path=%s', len(frame), total, self._path)
