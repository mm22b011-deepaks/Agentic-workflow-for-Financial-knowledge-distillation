"""Extract a stratified real sample with one configured free model, for manual spot-checks."""

from __future__ import annotations

import argparse
import asyncio
import logging

from _bootstrap import setup

from nowcast.config import resolve_data_path
from nowcast.extraction.runner import load_documents, run_extraction
from nowcast.llm.composition import make_caller

LOGGER = logging.getLogger('nowcast.scripts.extract_sample')


def main(argv: list[str] | None = None) -> int:
    """Extract `--sample` documents (one per company first) with one free model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0, help='first N documents (not a sample)')
    parser.add_argument(
        '--sample', type=int, default=5, help='N documents, one per company first, by season'
    )
    parser.add_argument('--seed', type=int, default=None, help='seed for --sample')
    parser.add_argument('--model', default='', help='model id (default: first configured)')
    args = parser.parse_args(argv)
    config = setup()
    model = args.model or config.llm.models[0]
    index = resolve_data_path(config, config.data.document_index)
    # load_documents drops non-text documents and rows without an earnings item, so a
    # stale index holding EX-99 scans cannot feed a JPEG to the model.
    documents = load_documents(config, index)
    from nowcast.extraction.selection import describe, stratified_sample

    if args.limit:
        LOGGER.warning('--limit takes the head of the index, which is not a representative sample')
        documents = documents[: args.limit]
    else:
        seed = int(args.seed) if args.seed is not None else int(config.aggregation.sample_seed)
        documents = stratified_sample(documents, args.sample, seed)
    LOGGER.info('documents=%s model=%s', describe(documents), model)

    shared: dict[str, object] = {}

    def factory(_model: str) -> object:
        # One composed caller for the whole run: the runner passes a RetryingCaller
        # through unchanged, so retry and cache apply but the HTTP client is not rebuilt
        # per document.
        if 'caller' not in shared:
            shared['caller'] = make_caller(config)
        return shared['caller']

    def progress(outcome: object) -> None:
        info = outcome
        LOGGER.info(
            '%s %s %s',
            info.document_id[:48],
            info.status,
            ','.join(info.review_reasons),
        )

    try:
        outcomes = asyncio.run(
            run_extraction(
                config,
                documents,
                caller_factory=factory,
                models=[model],
                on_outcome=progress,
            )
        )
    finally:
        if 'caller' in shared:
            shared['caller'].close()
    ok = sum(1 for item in outcomes if item.status == 'ok')
    failed = sum(1 for item in outcomes if item.status == 'failed')
    LOGGER.info('ok=%d failed=%d', ok, failed)
    for item in outcomes:
        if item.status != 'ok':
            LOGGER.warning('FAILED %s %s', item.document_id, (item.error or '')[:300])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
