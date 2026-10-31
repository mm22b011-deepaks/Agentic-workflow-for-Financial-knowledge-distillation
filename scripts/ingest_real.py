"""Download a bounded set of real 8-K exhibits and merge them into the document index."""

from __future__ import annotations

import argparse
import logging

from _bootstrap import setup

from nowcast.config import resolve_data_path
from nowcast.ingestion.constituents import cik_list, load_constituents
from nowcast.ingestion.doc_index import upsert_index
from nowcast.ingestion.edgar import IngestReport, ingest_edgar

LOGGER = logging.getLogger('nowcast.scripts.ingest_real')


def main(argv: list[str] | None = None) -> int:
    """Fetch up to `--limit` documents and merge them into the configured index."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=100, help='document cap for this run')
    args = parser.parse_args(argv)
    config = setup()
    constituents = resolve_data_path(config, config.data.constituents_csv)
    frame_in = load_constituents(constituents)
    report = IngestReport()
    rows = ingest_edgar(
        config,
        cik_list(frame_in),
        max_documents=args.limit,
        per_cik_limit=int(config.data.edgar_docs_per_cik),
        report=report,
    )
    # The same upsert the CLI uses, into the same configured path: a script must not
    # invent its own index location.
    target = resolve_data_path(config, config.data.document_index)
    frame = upsert_index(target, rows)
    LOGGER.info('indexed %d new rows; index size now %d -> %s', len(rows), len(frame), target)
    LOGGER.info(
        'statuses=%s skips=%s zero_disclosure=%d',
        report.status_counts,
        report.skip_reasons,
        len(report.zero_disclosure_ciks),
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
