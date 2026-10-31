"""Review-queue persistence for records that need human attention.

The queue is the current verdict on a document, not a log of everything ever said about
it. Writing a document's results replaces that document's rows for that model, because an
append-only queue lets one failed run exclude a document that has since been extracted
fine — and one model's flag exclude another model's good record.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

QUEUE_COLUMNS = ('document_id', 'field', 'reason', 'model')
QUEUE_KEYS = ['document_id', 'model']
SUPERSEDED_DIR = 'superseded'


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


def _archive_existing(target: Path, existing: pd.DataFrame, keys: pd.DataFrame) -> None:
    """Keep the rows being replaced under superseded/, so history is not lost."""
    if existing.empty or keys.empty:
        return
    replaced = existing.merge(keys.drop_duplicates(), on=QUEUE_KEYS, how='inner')
    if replaced.empty:
        return
    folder = target.parent / SUPERSEDED_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now('UTC').strftime('%Y%m%dT%H%M%S%f')
    replaced.to_parquet(folder / f'review_queue.{stamp}.parquet', index=False)


def replace_rows(
    path: Path | str, document_id: str, model: str, rows: list[dict[str, str]]
) -> None:
    """Replace one (document, model)'s queue rows with `rows`.

    An empty `rows` list clears the document's rows: the record passed review this time,
    so the old verdict is no longer true. Other documents and other models keep theirs.
    """
    target = Path(path)
    existing = load_queue(target)
    keys = pd.DataFrame([{'document_id': document_id, 'model': model}])
    keep = existing.merge(keys, on=QUEUE_KEYS, how='left', indicator=True)
    kept = existing[keep['_merge'] == 'left_only'].reset_index(drop=True)
    _archive_existing(target, existing, keys)
    new_frame = pd.DataFrame(rows, columns=list(QUEUE_COLUMNS))
    combined = pd.concat([kept, new_frame], ignore_index=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(target, index=False)


def append_rows(path: Path | str, rows: list[dict[str, str]]) -> pd.DataFrame:
    """Append review rows without replacing anything.

    Kept for callers that add a row about a document they are not re-extracting, such as
    a cross-model disagreement. A document's own verdict goes through `replace_rows`.
    """
    target = Path(path)
    existing = load_queue(target)
    if not rows:
        return existing
    new_frame = pd.DataFrame(rows, columns=list(QUEUE_COLUMNS))
    combined = pd.concat([existing, new_frame], ignore_index=True)
    combined = combined.drop_duplicates(subset=[*QUEUE_COLUMNS], keep='last')
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
