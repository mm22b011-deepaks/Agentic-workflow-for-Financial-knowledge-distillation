"""Unit tests for the local manifest adapter."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import Config, data_root
from nowcast.errors import DataError
from nowcast.ingestion.local_adapter import index_manifest, load_manifest


def _manifest(tmp_path: Path) -> Path:
    """Create a source document plus a one-row manifest referencing it."""
    source = tmp_path / 'release.html'
    source.write_text('<p>Revenue was $10 million.</p>', encoding='utf-8')
    manifest = tmp_path / 'manifest.csv'
    pd.DataFrame(
        [
            {
                'document_id': 'local-001',
                'cik': '1',
                'report_date': '2026-03-01',
                'document_type': 'EX-99',
                'path': 'release.html',
                'source': 'local',
            }
        ]
    ).to_csv(manifest, index=False)
    return manifest


def test_local_adapter_indexes_rows(tmp_path: Path, config: Config) -> None:
    """A manifest row becomes one index row with a copied raw file."""
    rows = index_manifest(config, _manifest(tmp_path))
    assert len(rows) == 1
    row = rows[0]
    assert row['document_id'] == 'local-001'
    assert row['cik'] == '0000000001'
    assert not Path(str(row['raw_path'])).is_absolute()
    assert (data_root(config) / str(row['raw_path'])).is_file()
    assert int(str(row['chars'])) > 0


def test_local_adapter_is_idempotent(tmp_path: Path, config: Config) -> None:
    """Indexing twice produces identical rows and does not fail."""
    manifest = _manifest(tmp_path)
    first = index_manifest(config, manifest)
    second = index_manifest(config, manifest)
    assert first[0]['sha256'] == second[0]['sha256']
    assert first[0]['raw_path'] == second[0]['raw_path']


def test_local_adapter_missing_column(tmp_path: Path) -> None:
    """A manifest missing a required column raises DataError naming it."""
    manifest = tmp_path / 'bad.csv'
    pd.DataFrame([{'document_id': 'x'}]).to_csv(manifest, index=False)
    with pytest.raises(DataError) as excinfo:
        load_manifest(manifest)
    assert 'cik' in str(excinfo.value)


def test_local_adapter_missing_document(tmp_path: Path, config: Config) -> None:
    """A manifest pointing at a missing file raises DataError."""
    manifest = _manifest(tmp_path)
    (tmp_path / 'release.html').unlink()
    with pytest.raises(DataError):
        index_manifest(config, manifest)
