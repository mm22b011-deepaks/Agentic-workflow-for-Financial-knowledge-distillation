"""Prepare reproducible private human-labelling records and guidance inspection snippets."""

from __future__ import annotations

import json
import random

from _bootstrap import setup

from nowcast.config import extractions_dir
from nowcast.extraction.runner import load_documents, model_slug, prepare_text
from nowcast.ingestion.rebuild import index_path
from nowcast.paths import Paths


def main() -> None:
    config = setup()
    target = Paths.from_config(config).resolve('verification/human-panel.json')
    if target.exists():
        return
    documents = {d.document_id: d for d in load_documents(config, index_path(config))}
    folder = extractions_dir(config) / model_slug(config.llm.models[0])
    payloads = []
    for path in sorted(folder.glob('*.json')):
        data = json.loads(path.read_text())
        if data.get('document_id') in documents:
            payloads.append(data)
    rng = random.Random(config.runtime.seed)
    rng.shuffle(payloads)
    records = []
    for data in payloads[:30]:
        document = documents[data['document_id']]
        source = prepare_text(config, document).source_text
        records.append(
            {
                'document_id': document.document_id,
                'sha256': document.sha256,
                'source': source,
                'extraction': data['record'],
                'labels': None,
            }
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {'version': 'v1', 'seed': config.runtime.seed, 'records': records, 'scored': 0},
            indent=2,
        )
    )
    nulls = [d for d in payloads if not (d['record'].get('guidance_direction') or {}).get('value')][
        :10
    ]
    inspections = []
    for data in nulls:
        source = prepare_text(config, documents[data['document_id']]).source_text
        lines = source.splitlines()
        excerpts = []
        for index, line in enumerate(lines):
            if any(
                word in line.lower()
                for word in ('guidance', 'outlook', 'forecast', 'expect', 'anticipate')
            ):
                excerpts.append('\n'.join(lines[max(0, index - 1) : min(len(lines), index + 3)]))
        inspections.append(
            {
                'document_id': data['document_id'],
                'excerpts': excerpts[:12],
                'inspection': None,
                'source_chars': len(source),
            }
        )
    (target.parent / 'guidance-inspection.json').write_text(json.dumps(inspections, indent=2))


if __name__ == '__main__':
    main()
