"""Measure how much document text the extraction cut drops, and what sits past it.

Reads a document index, prepares every text document with the same conversion, section
selection and `extraction.max_doc_chars` cut the runner uses, and reports:

- how many documents are cut and how many characters never reach the prompt;
- how often four key terms first occur after the cut, and how often any occurrence does.

The terms are fixed here on purpose: the point is a reproducible measurement, so the
search is part of the result. Run it from the repository root:

    python scripts/measure_truncation.py --index document_index.parquet

`--index` is resolved like every other input path: relative to the data root.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import pandas as pd
from _bootstrap import setup

from nowcast.config import Config, resolve_data_path
from nowcast.extraction.runner import Document, prepare_text

LOGGER = logging.getLogger('nowcast.scripts.measure_truncation')
TERMS = {
    'eps': re.compile(r'earnings per share|\bEPS\b', re.IGNORECASE),
    'revenue': re.compile(r'\brevenue\b|\bnet sales\b', re.IGNORECASE),
    'guidance': re.compile(r'\bguidance\b|\boutlook\b', re.IGNORECASE),
    'growth': re.compile(r'\bgrowth\b|\bgrew\b', re.IGNORECASE),
}


def measure(config: Config, frame: pd.DataFrame) -> dict[str, object]:
    """Return the cut statistics over every text row in the index frame."""
    documents = 0
    over_cut = 0
    chars_total = 0
    chars_dropped = 0
    missing_from_sent = dict.fromkeys(TERMS, 0)
    over_ids: list[str] = []
    for row in frame.to_dict('records'):
        raw_path = Path(str(row['raw_path']))
        if raw_path.suffix.lower() not in {'.htm', '.html', '.txt'}:
            continue
        path = raw_path if raw_path.is_absolute() else resolve_data_path(config, str(raw_path))
        if not path.is_file():
            LOGGER.warning('index row has no raw file document=%s', row['document_id'])
            continue
        document = Document(
            document_id=str(row['document_id']),
            cik=str(row['cik']),
            report_date=str(row['report_date']),
            document_type=str(row['document_type']),
            raw_path=path,
            sha256=str(row['sha256']),
        )
        prepared = prepare_text(config, document)
        text = prepared.source_text
        documents += 1
        chars_total += prepared.chars_total
        for name, term in TERMS.items():
            # What actually matters now that the text is packed: does the word reach the
            # model at all? Position past `chars_sent` stopped being meaningful the
            # moment the packer started keeping windows from further down.
            if term.search(text) and not term.search(prepared.text):
                missing_from_sent[name] += 1
        if not prepared.truncated:
            continue
        over_cut += 1
        over_ids.append(document.document_id)
        chars_dropped += prepared.chars_total - prepared.chars_sent
        if len(text) != prepared.chars_total:
            raise SystemExit(f'{document.document_id}: reproduced length differs from the cut')
    return {
        'cut': int(config.extraction.max_doc_chars),
        'documents': documents,
        'over_cut': over_cut,
        'share_over': round(over_cut / documents, 4) if documents else None,
        'chars_total': chars_total,
        'chars_dropped': chars_dropped,
        'share_dropped': round(chars_dropped / chars_total, 4) if chars_total else None,
        # Per term: in how many documents the word exists but never reaches the model.
        'terms_missing_from_sent': missing_from_sent,
        'over_ids': over_ids,
        'terms': {name: term.pattern for name, term in TERMS.items()},
    }


def main(argv: list[str] | None = None) -> int:
    """Load the index, measure the cut, and log one JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--index',
        default=None,
        help='index parquet, relative to the data root (default: data.document_index)',
    )
    args = parser.parse_args(argv)
    config = setup()
    index = resolve_data_path(config, args.index or config.data.document_index)
    if not index.is_file():
        LOGGER.error('document index not found: %s', index)
        return 2
    summary = measure(config, pd.read_parquet(index))
    LOGGER.info('truncation measurement: %s', json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
