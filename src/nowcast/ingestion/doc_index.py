"""Parquet index of every downloaded or local document."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from nowcast.errors import DataError
from nowcast.storage import atomic_parquet

# `items` is the 8-K item list from the submissions feed ("2.02,9.01"). It is not part
# of the pre-v2 index, so it is the one column `load_index` backfills rather than
# rejects: an old index stays readable, but its rows cannot prove they are earnings
# releases and are therefore not extracted.
INDEX_COLUMNS = (
    'document_id',
    'cik',
    'report_date',
    'document_type',
    'source',
    'raw_path',
    'sha256',
    'chars',
    'downloaded_at',
    'items',
)
BACKFILLED_COLUMNS = ('items',)
EARNINGS_ITEM = '2.02'


def item_codes(value: object) -> set[str]:
    """Return the 8-K item codes in an index value, tolerating blanks and lists."""
    if value is None:
        return set()
    if isinstance(value, float) and value != value:  # NaN, as parquet stores a missing cell
        return set()
    text = str(value)
    return {code.strip() for code in text.split(',') if code.strip()}


def has_earnings_item(value: object, wanted: tuple[str, ...] = (EARNINGS_ITEM,)) -> bool:
    """Return whether an index row's items include a configured earnings item."""
    return bool(item_codes(value).intersection(wanted))


def file_sha256(path: Path | str, block_size: int = 1 << 20) -> str:
    """Return the sha256 hex digest of a file."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(block_size), b''):
            digest.update(block)
    return digest.hexdigest()


def load_index(path: Path | str) -> pd.DataFrame:
    """Load the document index, returning an empty typed frame when absent."""
    target = Path(path)
    if not target.is_file():
        return pd.DataFrame(columns=list(INDEX_COLUMNS))
    frame = pd.read_parquet(target)
    for column in INDEX_COLUMNS:
        if column not in frame.columns:
            if column in BACKFILLED_COLUMNS:
                frame[column] = None
                continue
            raise DataError(f'document index {target} is missing column {column!r}')
    return frame


def upsert_rows(existing: pd.DataFrame, rows: list[dict[str, object]]) -> pd.DataFrame:
    """Merge rows by document_id, keeping the newest record for each id."""
    new_frame = pd.DataFrame(rows)
    if new_frame.empty:
        return existing
    for column in INDEX_COLUMNS:
        if column not in new_frame.columns:
            new_frame[column] = None
    new_frame = new_frame[list(INDEX_COLUMNS)]
    combined = new_frame if existing.empty else pd.concat([existing, new_frame], ignore_index=True)
    combined = combined.drop_duplicates(subset=['document_id'], keep='last')
    return combined.sort_values(['report_date', 'document_id']).reset_index(drop=True)


def write_index(frame: pd.DataFrame, path: Path | str) -> Path:
    """Write the document index to parquet."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_parquet(frame[list(INDEX_COLUMNS)], target)
    return target


def upsert_index(path: Path | str, rows: list[dict[str, object]]) -> pd.DataFrame:
    """Load, merge and write the document index in one call."""
    existing = load_index(path)
    merged = upsert_rows(existing, rows)
    write_index(merged, path)
    return merged


class IndexCheckpoint:
    """Recover downloaded rows from fsynced receipts and batch expensive parquet writes."""

    def __init__(self, path: Path, batch_size: int = 25) -> None:
        import json

        self.path = path
        self.receipts = path.with_suffix('.receipts.jsonl')
        self.frame = load_index(path)
        self.pending: list[dict[str, object]] = []
        self.batch_size = batch_size
        if self.receipts.exists():
            for line in self.receipts.read_text().splitlines():
                try:
                    self.pending.append(json.loads(line))
                except ValueError:
                    # A killed append may leave the final line incomplete; earlier receipts survive.
                    break
            self.flush()

    def add(self, row: dict[str, object]) -> None:
        """Durably acknowledge a completed download before returning to ingestion."""
        import json
        import os

        self.receipts.parent.mkdir(parents=True, exist_ok=True)
        with self.receipts.open('a') as handle:
            handle.write(json.dumps(row) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        self.pending.append(row)
        if len(self.pending) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        """Checkpoint receipts before removing them; replay after a crash is idempotent."""
        if not self.pending:
            self.receipts.unlink(missing_ok=True)
            return
        self.frame = upsert_rows(self.frame, self.pending)
        write_index(self.frame, self.path)
        self.receipts.unlink(missing_ok=True)
        self.pending.clear()
