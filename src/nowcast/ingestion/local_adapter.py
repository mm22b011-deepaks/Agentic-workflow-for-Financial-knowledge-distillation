"""Local manifest adapter: index user-supplied documents without downloading."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from nowcast.config import Config, data_root, raw_dir
from nowcast.errors import DataError
from nowcast.ingestion.doc_index import file_sha256
from nowcast.parsing.html import html_to_text

REQUIRED_COLUMNS = ('document_id', 'cik', 'report_date', 'document_type', 'path', 'source')


def load_manifest(path: Path | str) -> pd.DataFrame:
    """Load and validate the local manifest CSV."""
    target = Path(path)
    if not target.is_file():
        raise DataError(f'local manifest not found: {target}')
    frame = pd.read_csv(target, dtype={'cik': str})
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DataError(
            f'local manifest {target} is missing required columns: {", ".join(missing)}; '
            f'required: {", ".join(REQUIRED_COLUMNS)}'
        )
    return frame


def _resolve_source(raw_path: str, manifest_dir: Path) -> Path:
    """Resolve a manifest path as absolute, manifest-relative, then cwd-relative."""
    candidate = Path(raw_path)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    for base in (manifest_dir, Path.cwd()):
        resolved = (base / raw_path).resolve()
        if resolved.is_file():
            return resolved
    raise DataError(f'manifest document not found: {raw_path}')


def index_manifest(config: Config, manifest_path: Path | str) -> list[dict[str, object]]:
    """Copy manifest documents into the raw directory and return index rows."""
    target = Path(manifest_path)
    manifest = load_manifest(target)
    manifest_dir = target.resolve().parent
    raw_root = raw_dir(config)
    rows: list[dict[str, object]] = []
    for record in manifest.to_dict('records'):
        source_path = _resolve_source(str(record['path']), manifest_dir)
        document_id = str(record['document_id'])
        cik = str(record['cik']).strip().zfill(10)
        suffix = source_path.suffix.lower() or '.txt'
        destination = raw_root / cik / document_id
        destination.mkdir(parents=True, exist_ok=True)
        raw_file = destination / f'{document_id}{suffix}'
        if not raw_file.is_file() or file_sha256(raw_file) != file_sha256(source_path):
            shutil.copyfile(source_path, raw_file)
        text = _document_text(raw_file)
        rows.append(
            {
                'document_id': document_id,
                'cik': cik,
                'report_date': pd.Timestamp(record['report_date']).date().isoformat(),
                'document_type': str(record['document_type']),
                'source': str(record.get('source') or 'local'),
                # Relative to the data root, like the EDGAR adapter, so the index
                # survives moving or copying the data directory.
                'raw_path': str(raw_file.relative_to(data_root(config))),
                'sha256': file_sha256(raw_file),
                'chars': len(text),
                'downloaded_at': datetime.now(timezone.utc).isoformat(),
            }
        )
    return rows


def _document_text(path: Path) -> str:
    """Read a document as text, converting HTML when the suffix says so."""
    raw = path.read_text(encoding='utf-8', errors='replace')
    if path.suffix.lower() in {'.html', '.htm'}:
        return html_to_text(raw)
    return raw
