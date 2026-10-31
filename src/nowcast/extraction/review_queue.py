"""Review-queue persistence for records that need human attention."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

QUEUE_COLUMNS = ('document_id', 'field', 'reason', 'model')


def load_queue(path: Path | str) -> pd.DataFrame:
    """Load the review queue, returning an empty typed frame when absent."""
    target = Path(path)
    if not target.is_file():
        return pd.DataFrame(columns=list(QUEUE_COLUMNS))
    frame = pd.read_parquet(target)
    for column in QUEUE_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    return frame[list(QUEUE_COLUMNS)]


def append_rows(path: Path | str, rows: list[dict[str, str]]) -> pd.DataFrame:
    """Append review rows, de-duplicating identical document/field/reason/model tuples."""
    target = Path(path)
    existing = load_queue(target)
    if not rows:
        return existing
    new_frame = pd.DataFrame(rows, columns=list(QUEUE_COLUMNS))
    combined = pd.concat([existing, new_frame], ignore_index=True)
    combined = combined.drop_duplicates(
        subset=['document_id', 'field', 'reason', 'model'], keep='last'
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(target, index=False)
    return combined.reset_index(drop=True)


def rows_for_record(
    document_id: str, model: str, reasons: list[str], issues: list[tuple[str, str]]
) -> list[dict[str, str]]:
    """Build review-queue rows from review reasons and validation issues."""
    rows: list[dict[str, str]] = []
    for reason in reasons:
        field = reason.split(':', 1)[1] if ':' in reason else 'record'
        rows.append(
            {
                'document_id': document_id,
                'field': field,
                'reason': reason.split(':', 1)[0],
                'model': model,
            }
        )
    for field, code in issues:
        rows.append({'document_id': document_id, 'field': field, 'reason': code, 'model': model})
    return rows
