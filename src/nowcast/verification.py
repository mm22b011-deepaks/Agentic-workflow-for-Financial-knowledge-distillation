"""Deterministic synthetic corpus, full offline execution and independent metric checks."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from nowcast.aggregation.aggregate import aggregate_index, assert_index_level_only
from nowcast.config import Config
from nowcast.extraction.review_queue import load_queue
from nowcast.extraction.runner import consolidate, load_documents, run_extraction
from nowcast.ingestion.doc_index import write_index
from nowcast.ingestion.local_adapter import index_manifest
from nowcast.llm.caller import LLMResult
from nowcast.paths import Paths


class CorpusCaller:
    """Return controlled fixtures through the same extraction/validation path as a provider."""

    def __init__(self, replies: dict[str, dict[str, Any]]) -> None:
        self.replies = replies
        self.calls = 0

    def complete(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> LLMResult:
        content = '\n'.join(message['content'] for message in messages)
        document_id = re.findall(r'<document id="([^"]+)">', content)[-1]
        self.calls += 1
        return LLMResult(text=json.dumps(self.replies[document_id]), model=model)


def synthetic_demo(config: Config, directory: Path, count: int = 500) -> dict[str, Any]:
    """Generate releases and report measured per-class precision/recall and pandas agreement."""
    if count < 500:
        raise ValueError('S1 requires at least 500 generated releases')
    directory.mkdir(parents=True, exist_ok=True)
    paths = dataclasses.replace(config.paths, data_dir=str(directory.resolve()))
    # Avoid DATA_DIR overriding the isolated demo while retaining the original config environment.
    runtime = dataclasses.replace(
        config.runtime, data_dir_env='TRESATA_SYNTHETIC_DATA', max_concurrency=4
    )
    local = dataclasses.replace(
        config,
        paths=paths,
        runtime=runtime,
        cache=dataclasses.replace(config.cache, enabled=False),
        llm=dataclasses.replace(
            config.llm, requests_per_minute=count * 10, requests_per_day=count * 5
        ),
        extraction=dataclasses.replace(config.extraction, pack_phrases=()),
        aggregation=dataclasses.replace(
            config.aggregation, winsorize_pct=0, dedupe_rule='max_confidence'
        ),
    )
    source_dir = directory / 'sources'
    source_dir.mkdir(exist_ok=True)
    rows, truths, members = [], [], []
    replies: dict[str, dict[str, Any]] = {}
    for i in range(count):
        company, quarter = i // 4, i % 4 + 1
        name, cik = f'synthetic-{i:04d}', f'{company + 1:010d}'
        stamp = f'2025-{quarter * 3:02d}-15'
        eps, growth = round(1 + (i % 23) / 10, 2), float(i % 17)
        corruption = ('clean', 'wrong_number', 'wrong_sign', 'missing_quote', 'wrong_period')[i % 5]
        raw = source_dir / (name + '.html')
        raw.write_text(
            f'<p>GAAP EPS ${eps:.2f}. Prior GAAP EPS $1.00. Revenue growth {growth:g}%. Guidance raised. Tone neutral.</p>'
            '<table><tr><th></th><th>2025</th><th>2024</th></tr><tr><td>Revenue</td><td>$100 million</td><td>$80 million</td></tr></table>'
        )

        def field(value: Any, quote: str | None) -> dict[str, Any]:
            return {'value': value, 'evidence_quote': quote, 'confidence': 1}

        reply = {
            'schema_version': 'v1',
            'document_id': name,
            'fiscal_year': 2025,
            'fiscal_quarter': quarter,
            'currency': 'USD',
            'units': 'USD million',
            'reported_eps': field(eps, f'GAAP EPS ${eps:.2f}'),
            'prior_year_eps': field(1.0, 'Prior GAAP EPS $1.00'),
            'eps_basis': field('gaap', f'GAAP EPS ${eps:.2f}'),
            'prior_year_basis': field('gaap', 'Prior GAAP EPS $1.00'),
            'revenue': field(100.0, 'Revenue $100 million'),
            'revenue_yoy_growth': field(growth, f'Revenue growth {growth:g}%'),
            'guidance_direction': field('raised', 'Guidance raised'),
            'tone': field('neutral', 'Tone neutral'),
        }
        if corruption == 'wrong_number':
            reply['reported_eps'] = field(eps + 10, f'GAAP EPS ${eps + 10:.2f}')
        elif corruption == 'wrong_sign':
            reply['reported_eps'] = field(-eps, f'GAAP EPS ${eps:.2f}')
        elif corruption == 'missing_quote':
            reply['reported_eps'] = field(eps, None)
        elif corruption == 'wrong_period':
            reply['revenue'] = field(80.0, 'Revenue $80 million')
        replies[name] = reply
        rows.append(
            {
                'document_id': name,
                'cik': cik,
                'report_date': stamp,
                'document_type': 'EX-99.1',
                'path': str(raw.resolve()),
                'source': 'synthetic',
                'items': '2.02',
            }
        )
        truths.append(
            {
                'document_id': name,
                'cik': cik,
                'quarter': quarter,
                'eps_growth': eps - 1,
                'revenue_growth': growth,
                'corruption': corruption,
            }
        )
        if quarter == 1:
            members.append(
                {
                    'ticker': f'SYN{company}',
                    'cik': cik,
                    'effective_from': '2024-01-01',
                    'effective_to': '',
                }
            )
    manifest = directory / 'manifest.csv'
    pd.DataFrame(rows).to_csv(manifest, index=False)
    member_path = Paths.from_config(local).resolve(local.data.constituents_csv)
    member_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(members).to_csv(member_path, index=False)
    index = Paths.from_config(local).resolve(local.data.document_index)
    write_index(pd.DataFrame(index_manifest(local, manifest)), index)
    caller = CorpusCaller(replies)
    documents = load_documents(local, index)
    outcomes = asyncio.run(
        run_extraction(local, documents, lambda _: caller, models=['synthetic:free'])
    )
    frame = consolidate(local, ['synthetic:free'])
    aggregate = aggregate_index(local, frame)
    assert_index_level_only(aggregate)
    queue = load_queue(Paths.from_config(local).resolve(local.extraction.review_queue_path))
    truth = pd.DataFrame(truths)
    predicted = set(queue.document_id) if not queue.empty else set()
    classes = {}
    for label, group in truth.groupby('corruption'):
        positives = set(group.document_id) if label != 'clean' else set()
        hits = len(set(group.document_id) & predicted)
        classes[str(label)] = {
            'documents': len(group),
            'flagged': hits,
            'precision': 1.0 if positives and hits else (0.0 if hits else None),
            'recall': hits / len(positives) if positives else None,
            'false_positives': hits if label == 'clean' else 0,
        }
    code_truth = {
        'number_not_in_quote': set(truth.loc[truth.corruption.eq('wrong_sign'), 'document_id']),
        'quote_missing': set(truth.loc[truth.corruption.eq('missing_quote'), 'document_id']),
        'number_not_in_source': set(
            truth.loc[truth.corruption.isin(['wrong_number', 'wrong_period']), 'document_id']
        ),
    }
    code_scores = {}
    for code, expected_ids in code_truth.items():
        actual_ids = set(queue.loc[queue.reason.eq(code), 'document_id'])
        true_positives = len(expected_ids & actual_ids)
        code_scores[code] = {
            'true_positives': true_positives,
            'false_positives': len(actual_ids - expected_ids),
            'false_negatives': len(expected_ids - actual_ids),
            'precision': true_positives / len(actual_ids) if actual_ids else None,
            'recall': true_positives / len(expected_ids),
        }
        if actual_ids != expected_ids:
            raise AssertionError(f'controlled validator class disagrees: {code}')
    expected = truth.copy()
    expected.loc[
        expected.corruption.isin(['wrong_number', 'wrong_sign', 'missing_quote']), 'eps_growth'
    ] = float('nan')
    # Revenue-source errors do not withdraw independently evidenced printed growth.
    independent = expected.groupby('quarter').agg(
        eps_growth_agg=(
            'eps_growth',
            lambda values: float(values.dropna().sum() / values.notna().sum()),
        ),
        revenue_growth_agg=(
            'revenue_growth',
            lambda values: float(values.dropna().sum() / values.notna().sum()),
        ),
    )
    actual = aggregate.set_index('season_quarter')[
        ['eps_growth_agg', 'revenue_growth_agg']
    ].sort_index()
    pd.testing.assert_frame_equal(
        actual, independent.rename_axis('season_quarter'), check_dtype=False, check_exact=True
    )
    result = {
        'version': 'v1',
        'documents': len(documents),
        'companies': len(members),
        'seasons': 4,
        'calls': caller.calls,
        'resumed': sum(o.skipped for o in outcomes),
        'validator_classes': classes,
        'validator_reason_scores': code_scores,
        'pandas_agreement': True,
        'network_required': False,
    }
    (directory / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    from nowcast.contracts import IndexSnapshot

    snapshot = IndexSnapshot(
        source='synthetic',
        snapshots=json.loads(aggregate.to_json(orient='records', date_format='iso')),
    )
    (directory / 'index.json').write_text(snapshot.model_dump_json(indent=2) + '\n')
    return result


def freeze_panel(config: Config, count: int = 150) -> Path:
    """Freeze company identities and every eligible interval-season pair before live ingestion."""
    import hashlib
    import random

    from nowcast.ingestion.constituents import load_constituents
    from nowcast.ingestion.sampling import season_sample

    paths = Paths.from_config(config)
    target = paths.resolve('verification/panel.json')
    if target.exists():
        return target
    membership = load_constituents(paths.resolve(config.data.constituents_csv))
    start, end = pd.Timestamp(config.data.start_date), pd.Timestamp(config.data.end_date)
    valid_ciks = membership.cik.str.fullmatch(r'\d{10}') & membership.cik.ne('0000000000')
    eligible = membership[
        (membership.effective_from <= end)
        & (membership.effective_to.isna() | (membership.effective_to >= start))
    ]
    unmapped_eligible_intervals = int((~valid_ciks.loc[eligible.index]).sum())
    eligible = eligible[valid_ciks.loc[eligible.index]]
    ciks = sorted(eligible.cik.unique())
    if len(ciks) < count:
        raise ValueError(f'panel requires {count} eligible companies; found {len(ciks)}')
    selected = sorted(random.Random(config.runtime.seed).sample(ciks, count))
    frame = eligible[eligible.cik.isin(selected)]
    sample = season_sample(
        dataclasses.replace(config, universe=dataclasses.replace(config.universe, subset_n=0)),
        frame,
    )
    body = {
        'version': 'v1',
        'seed': config.runtime.seed,
        'start_date': config.data.start_date,
        'end_date': config.data.end_date,
        'companies': selected,
        'unmapped_eligible_intervals': unmapped_eligible_intervals,
        'pairs': [
            {'cik': cik, 'season': season, 'outcome': 'unvisited'} for cik, season in sample.pairs
        ],
    }
    body['panel_sha256'] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as handle:
        json.dump(body, handle, indent=2)
    frame.to_csv(target.with_suffix('.constituents.csv'), index=False)
    return target
