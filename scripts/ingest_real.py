"""Download a bounded set of real 8-K exhibits and write the document index."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from nowcast.config import load_config, manifests_dir  # noqa: E402
from nowcast.ingestion.constituents import cik_list, load_constituents  # noqa: E402
from nowcast.ingestion.doc_index import upsert_index  # noqa: E402
from nowcast.ingestion.edgar import ingest_edgar  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def main(limit: int) -> int:
    """Fetch up to `limit` documents and merge them into the document index."""
    load_dotenv(ROOT / '.env', override=True)
    config = load_config(ROOT / 'configs' / 'config.yaml')
    constituents = load_constituents(ROOT / 'inputs' / 'constituents.csv')
    ciks = cik_list(constituents)
    rows = ingest_edgar(
        config,
        ciks,
        max_documents=limit,
        start_date=date.fromisoformat(config.data.start_date) if config.data.start_date else None,
        end_date=date.fromisoformat(config.data.end_date) if config.data.end_date else None,
    )
    index_path = ROOT / 'data' / 'document_index.parquet'
    frame = upsert_index(index_path, rows)
    print(f'indexed {len(rows)} new rows; index size now {len(frame)} -> {index_path}')
    manifest = manifests_dir(config) / 'ingest_summary.txt'
    manifest.write_text(
        f'new_rows={len(rows)}\nindex_rows={len(frame)}\ndocuments={sorted({r["document_id"] for r in rows})}\n',
        encoding='utf-8',
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 100))
