"""Extract a small real sample with the configured free model, for manual spot-checks."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from nowcast.config import load_config  # noqa: E402
from nowcast.extraction.runner import load_documents, run_extraction  # noqa: E402
from nowcast.llm.caller import LLMCaller  # noqa: E402

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')


def main(limit: int) -> int:
    """Run extraction over the first `limit` text documents with one free model."""
    load_dotenv(ROOT / '.env', override=True)
    config = load_config(ROOT / 'configs' / 'config.yaml')
    # load_documents drops non-text documents, so an index holding old EX-99 scans
    # cannot feed a JPEG to the model.
    documents = load_documents(config, ROOT / 'data' / 'document_index.parquet')[:limit]
    print(f'documents={len(documents)} model={config.llm.models[0]}')
    caller = LLMCaller(config.llm)

    def factory(_model: str) -> LLMCaller:
        return caller

    def progress(outcome: object) -> None:
        info = outcome
        print(f'  {info.document_id[:48]:48s} {info.status:14s} {",".join(info.review_reasons)}')

    try:
        outcomes = asyncio.run(
            run_extraction(config, documents, caller_factory=factory, models=[config.llm.models[0]])
        )
    finally:
        caller.close()
    ok = sum(1 for item in outcomes if item.status == 'ok')
    print(f'ok={ok} failed={sum(1 for i in outcomes if i.status == "failed")}')
    if ok < len(outcomes):
        for item in outcomes:
            if item.status != 'ok':
                print('  FAILED', item.document_id, (item.error or '')[:300])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5))
