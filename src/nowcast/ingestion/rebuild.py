"""Rebuild the document index into the configured v2 path, preserving everything old.

The pre-v2 index is a fact about what was downloaded, not a draft to be edited: it is
left where it is, and the rebuilt index is written to `data.document_index`. Results
and review-queue rows that describe documents the new index no longer carries are moved
to `superseded/` rather than deleted, so the old state stays recoverable.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from nowcast.config import Config, data_root, extractions_dir, resolve_data_path
from nowcast.errors import DataError
from nowcast.extraction.review_queue import load_queue
from nowcast.ingestion.doc_index import (
    INDEX_COLUMNS,
    has_earnings_item,
    load_index,
    write_index,
)

LOGGER = logging.getLogger(__name__)
TEXT_SUFFIXES = ('.htm', '.html', '.txt')
SUPERSEDED_DIR = 'superseded'

# A row that was downloaded into the index but would not be extracted again: no text,
# no earnings item, or outside the window. Named so the report can count each reason.
INVALID_NON_TEXT = 'non_text'
INVALID_NO_EARNINGS_ITEM = 'no_earnings_item'
INVALID_OUT_OF_WINDOW = 'out_of_window'


@dataclass(frozen=True)
class IndexProblem:
    """One index row that must not carry into the rebuilt index."""

    document_id: str
    code: str
    detail: str


@dataclass
class RebuildReport:
    """What a rebuild did, in counts a person can check against the old index."""

    source_path: Path | None = None
    new_path: Path | None = None
    source_rows: int = 0
    kept_rows: int = 0
    dropped_documents: list[str] = field(default_factory=list)
    problems: list[IndexProblem] = field(default_factory=list)
    superseded_extractions: list[str] = field(default_factory=list)
    superseded_queue_rows: int = 0

    def as_dict(self) -> dict[str, object]:
        """Return the report as JSON-serialisable data."""
        return {
            'source_path': str(self.source_path) if self.source_path else None,
            'new_path': str(self.new_path) if self.new_path else None,
            'source_rows': self.source_rows,
            'kept_rows': self.kept_rows,
            'dropped_documents': list(self.dropped_documents),
            'problem_count_by_code': _count_by_code(self.problems),
            'superseded_extractions': list(self.superseded_extractions),
            'superseded_queue_rows': self.superseded_queue_rows,
        }


def _count_by_code(problems: list[IndexProblem]) -> dict[str, int]:
    """Count index problems by their code."""
    counts: dict[str, int] = {}
    for problem in problems:
        counts[problem.code] = counts.get(problem.code, 0) + 1
    return dict(sorted(counts.items()))


def _window(config: Config) -> tuple[date | None, date | None]:
    """Return the configured [start, end] window as dates, blank ends as None."""
    lower = date.fromisoformat(str(config.data.start_date)[:10]) if config.data.start_date else None
    upper = date.fromisoformat(str(config.data.end_date)[:10]) if config.data.end_date else None
    return lower, upper


def validate_index_rows(frame: pd.DataFrame, config: Config) -> list[IndexProblem]:
    """Return every row that is not a parseable earnings release inside the window."""
    problems: list[IndexProblem] = []
    wanted = tuple(config.data.edgar_earnings_items) or ('2.02',)
    lower, upper = _window(config)
    for row in frame.to_dict('records'):
        document_id = str(row.get('document_id', ''))
        raw_path = Path(str(row.get('raw_path', '')))
        if raw_path.suffix.lower() not in TEXT_SUFFIXES:
            problems.append(
                IndexProblem(document_id, INVALID_NON_TEXT, f'suffix {raw_path.suffix!r}')
            )
            continue
        if not has_earnings_item(row.get('items'), wanted):
            problems.append(
                IndexProblem(document_id, INVALID_NO_EARNINGS_ITEM, str(row.get('items') or ''))
            )
            continue
        try:
            report_date = date.fromisoformat(str(row.get('report_date'))[:10])
        except ValueError:
            problems.append(
                IndexProblem(document_id, INVALID_OUT_OF_WINDOW, str(row.get('report_date')))
            )
            continue
        if (lower is not None and report_date < lower) or (
            upper is not None and report_date > upper
        ):
            problems.append(
                IndexProblem(document_id, INVALID_OUT_OF_WINDOW, report_date.isoformat())
            )
    return problems


def index_path(config: Config) -> Path:
    """Return the configured document index path, resolved against the data root."""
    return resolve_data_path(config, config.data.document_index)


def _move_extractions(config: Config, document_ids: set[str]) -> list[str]:
    """Move stored extraction results for the given documents into superseded/.

    Files are moved, not copied: a result for a document the index no longer carries
    must not be picked up by the next consolidate, which globs the model directory.
    """
    if not document_ids:
        return []
    moved: list[str] = []
    root = extractions_dir(config)
    if not root.is_dir():
        return moved
    target_root = root / SUPERSEDED_DIR
    for model_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if model_dir.name == SUPERSEDED_DIR:
            continue
        for document_id in sorted(document_ids):
            source = model_dir / f'{document_id}.json'
            if not source.is_file():
                continue
            target = target_root / model_dir.name / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moved.append(str(target))
    return moved


def _supersede_queue_rows(config: Config, document_ids: set[str]) -> int:
    """Remove queue rows for the given documents, keeping a copy of what was removed."""
    if not document_ids:
        return 0
    queue_path = resolve_data_path(config, config.extraction.review_queue_path)
    queue = load_queue(queue_path)
    if queue.empty:
        return 0
    doomed = queue[queue['document_id'].astype(str).isin(document_ids)]
    if doomed.empty:
        return 0
    kept = queue.drop(doomed.index)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive = queue_path.parent / SUPERSEDED_DIR / f'review_queue.{stamp}.parquet'
    archive.parent.mkdir(parents=True, exist_ok=True)
    doomed.to_parquet(archive, index=False)
    if kept.empty:
        queue_path.unlink()
    else:
        kept.reset_index(drop=True).to_parquet(queue_path, index=False)
    return len(doomed)


def rebuild_index(
    config: Config,
    rows: list[dict[str, object]] | pd.DataFrame,
    source_path: Path | None = None,
    supersede: bool = True,
) -> RebuildReport:
    """Validate and write the rebuilt index, then move superseded results aside.

    The new index is written to `data.document_index`, which must not be the source
    path: overwriting the old index would destroy the only record of what was
    downloaded before, which is exactly the thing a rebuild is meant to be checked
    against.
    """
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    for column in INDEX_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame = frame[list(INDEX_COLUMNS)].reset_index(drop=True)

    target = index_path(config)
    report = RebuildReport(source_path=source_path, new_path=target, source_rows=len(frame))
    if source_path is not None and Path(source_path).resolve() == target.resolve():
        raise DataError(
            f'refusing to rebuild {target} in place: data.document_index must name a new '
            'path so the previous index survives the rebuild'
        )

    problems = validate_index_rows(frame, config)
    bad_ids = {problem.document_id for problem in problems}
    kept = frame[~frame['document_id'].astype(str).isin(bad_ids)].reset_index(drop=True)
    report.problems = problems
    report.kept_rows = len(kept)

    dropped = set(bad_ids)
    if source_path is not None and Path(source_path).is_file():
        old = load_index(source_path)
        dropped |= set(old['document_id'].astype(str)) - set(kept['document_id'].astype(str))
    report.dropped_documents = sorted(dropped)

    write_index(kept, target)
    if supersede:
        report.superseded_extractions = _move_extractions(config, dropped)
        report.superseded_queue_rows = _supersede_queue_rows(config, dropped)
    LOGGER.info(
        'rebuilt index rows=%d kept=%d dropped=%d -> %s',
        report.source_rows,
        report.kept_rows,
        len(report.dropped_documents),
        target,
    )
    return report


def write_rebuild_report(config: Config, report: RebuildReport) -> Path:
    """Write the rebuild report next to the other run manifests."""
    from nowcast.config import manifests_dir

    target = manifests_dir(config) / 'rebuild_index.json'
    target.write_text(json.dumps(report.as_dict(), indent=2), encoding='utf-8')
    return target


def default_source(config: Config) -> Path:
    """Return the pre-v2 index path if it exists, else the configured index path."""
    legacy = data_root(config) / 'document_index.parquet'
    return legacy if legacy.is_file() else index_path(config)
