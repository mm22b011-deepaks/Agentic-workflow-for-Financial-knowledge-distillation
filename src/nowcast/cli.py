"""Command-line entry point for the index earnings nowcast pipeline."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from nowcast.config import (
    Config,
    aggregates_dir,
    data_root,
    load_config,
    manifests_dir,
    prompts_dir,
    resolve_data_path,
    validate_config,
)
from nowcast.errors import BudgetExceeded, ConfigError, DataError, NowcastError
from nowcast.logging_setup import setup_logging
from nowcast.manifest import (
    Manifest,
    file_fingerprint,
    finish_manifest,
    prompt_hashes,
    start_manifest,
)

# A stable name: run as `python -m nowcast.cli` the module is __main__, and log lines
# should not change name depending on how the CLI was started.
LOGGER = logging.getLogger('nowcast.cli')
DEFAULT_CONFIG = Path('configs') / 'config.yaml'


def _configure_logging(config: Config) -> None:
    """Configure root logging from the config's log level, ordinary output to stdout."""
    setup_logging(config.runtime.log_level, stdout=True)


def _record_run(config: Config, stage: str, inputs: list[str], manifest: Manifest) -> Path:
    """Stamp and write a run manifest, returning where it landed."""
    for item in inputs:
        path = Path(item)
        if path.is_file():
            manifest.input_fingerprints[path.name] = file_fingerprint(path)
    finish_manifest(manifest)
    return manifest.write(manifests_dir(config) / f'{stage}.manifest.json', config)


def _prompt_fingerprints(config: Config) -> dict[str, str]:
    """Return hashes of the extraction prompt version, or {} when it cannot load."""
    root = prompts_dir(config)
    try:
        return prompt_hashes(root, 'extraction', config.extraction.schema_version)
    except ConfigError:
        return {}


def _load(args: argparse.Namespace) -> Config:
    """Load config from the CLI path with any --set overrides applied."""
    overrides: dict[str, str] = {}
    for item in args.set or []:
        if '=' not in item:
            raise ConfigError(f'--set expects key=value, got {item!r}')
        key, value = item.split('=', 1)
        overrides[key.strip()] = value
    path = Path(args.config) if args.config else DEFAULT_CONFIG
    if not path.is_file():
        raise ConfigError(f'config file not found: {path}')
    config = load_config(path, overrides=overrides or None)
    _configure_logging(config)
    return config


def _add_common(parser: argparse.ArgumentParser) -> None:
    """Attach --config and repeated --set to a subcommand."""
    parser.add_argument('--config', default=str(DEFAULT_CONFIG), help='path to config YAML')
    parser.add_argument(
        '--set',
        action='append',
        metavar='KEY=VALUE',
        help='override a dotted config key (repeatable)',
    )


def _cmd_validate_config(args: argparse.Namespace) -> int:
    """Report config problems without running anything."""
    config = _load(args)
    strict = bool(getattr(args, 'strict', False))
    try:
        problems = validate_config(config, strict=strict)
    except ConfigError as exc:
        LOGGER.warning('problem: %s', exc)
        return 1
    if problems:
        for problem in problems:
            LOGGER.warning('problem: %s', problem)
        return 1
    LOGGER.info('config OK')
    LOGGER.info('data root: %s', data_root(config))
    return 0


def _cmd_build_constituents(args: argparse.Namespace) -> int:
    """Build the point-in-time constituents file."""
    from nowcast.ingestion.universe.builder import build_constituents

    config = _load(args)
    validate_config(config, strict=True)
    path = build_constituents(config)
    LOGGER.info('constituents written: %s', path)
    return 0


def _cmd_estimate_scope(args: argparse.Namespace) -> int:
    """Estimate document count and token load without touching the network."""
    from nowcast.ingestion.universe.builder import estimate_scope

    config = _load(args)
    estimate = estimate_scope(config)
    for line in estimate.as_lines():
        LOGGER.info('%s', line)
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    """Download earnings documents for the constituents CIKs and index them."""
    from nowcast.ingestion.doc_index import IndexCheckpoint, load_index
    from nowcast.ingestion.edgar import IngestReport, ingest_edgar
    from nowcast.ingestion.rebuild import index_path
    from nowcast.ingestion.universe.builder import _resolve_input

    config = _load(args)
    validate_config(config, strict=True)
    manifest = start_manifest(config, stage='ingest')
    constituents = _resolve_input(config, config.data.constituents_csv)
    if constituents is None:
        raise DataError(
            f'constituents file not found: {config.data.constituents_csv}; '
            'run build-constituents first, or pass --set data.constituents_csv=...'
        )
    from nowcast.ingestion.constituents import load_constituents
    from nowcast.ingestion.sampling import season_sample

    frame = load_constituents(constituents)
    from nowcast.scope import scoped_membership

    config, frame = scoped_membership(config, frame)
    limit = int(config.data.edgar_max_documents)
    per_cik = int(config.data.edgar_docs_per_cik)
    # Seeded per-season walk order, not the sorted head of the CIK list: the ingest stops
    # at the document cap, so CIK order would fill it with the alphabetically first
    # companies — a sample of the alphabet, not of the index.
    sample = season_sample(config, frame)
    from nowcast.registry import load_registry

    registry = load_registry(config)
    if len(sample.pairs) > registry.limits.maximum_planned_pairs:
        raise DataError('planned company-season pairs exceed configured maximum')
    ciks = list(sample.ciks)
    # Say what the cap will actually cover: a cap of 100 documents at 3 per company
    # visits at most 34 companies, whichever 519 were sampled.
    visitable = min(len(ciks), -(-limit // per_cik) if per_cik else len(ciks))
    LOGGER.info(
        'ingesting %d sampled companies, up to %d will be visited '
        '(cap %d documents, %d per company) across %s; seasons %s',
        len(ciks),
        visitable,
        limit,
        per_cik,
        f'{config.data.start_date}..{config.data.end_date}',
        ', '.join(sample.seasons),
    )
    report = IngestReport()
    report_path = manifests_dir(config) / 'ingest_report.json'
    target_index = index_path(config)
    cohort_path = manifests_dir(config) / 'cohort.csv'
    # The cohort is the (company, season) pairs this run intends to fetch, so a company
    # sampled for one quarter is not counted as expected in the others. CIKs and seasons
    # only; it never enters a report. Written in the finally block: an abort must not
    # lose the record of what the run was trying to do.
    cohort = pd.DataFrame([{'cik': cik, 'season': season} for cik, season in sample.pairs])
    cohort_path.parent.mkdir(parents=True, exist_ok=True)
    cohort.to_csv(cohort_path, index=False)

    checkpoint = IndexCheckpoint(target_index)

    rows: list[dict[str, object]] = []
    try:
        if any(
            not cik.isascii() or not cik.isdecimal() or len(cik) != 10 or int(cik) == 0
            for cik in ciks
        ):
            raise DataError('membership contains unmapped CIKs; resolve them before SEC ingestion')
        rows = ingest_edgar(
            config,
            ciks,
            max_documents=limit,
            per_cik_limit=per_cik,
            report=report,
            on_row=checkpoint.add,
            target_seasons=sample.season_targets(),
            membership=frame,
        )
    finally:
        checkpoint.flush()
        # Every one of these is written even on the abort path: how far a run got and why
        # it stopped are the most useful things these files can say.
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.as_dict(), indent=2), encoding='utf-8')
        planned = cohort.copy()
        planned['outcome'] = [
            report.pair_outcomes.get(str(row.cik) + ':' + str(row.season), 'unvisited')
            for row in planned.itertuples()
        ]
        planned.to_csv(manifests_dir(config) / 'pair_outcomes.csv', index=False)
        cohort = planned[planned['outcome'] != 'unvisited'][['cik', 'season']]
        cohort.to_csv(cohort_path, index=False)
    merged = load_index(target_index)
    summary = {
        'new_rows': len(rows),
        'index_rows': len(merged),
        'companies': len(ciks),
        'cohort_pairs': len(sample.pairs),
        'cap': limit,
        'start_date': config.data.start_date,
        'end_date': config.data.end_date,
        'sample': sample.as_dict(),
        'status_counts': report.status_counts,
        'skip_reasons': report.skip_reasons,
        'zero_disclosure_companies': len(report.zero_disclosure_ciks),
        'aborted': report.aborted,
    }
    target = manifests_dir(config) / 'ingest_summary.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    per_season: dict[str, int] = {}
    for season in cohort['season'].astype(str):
        per_season[season] = per_season.get(season, 0) + 1
    for season, count in sorted(per_season.items()):
        if count < int(config.aggregation.min_constituents):
            LOGGER.warning('cohort_too_small:%s (%d companies)', season, count)
    manifest.notes = f'indexed {len(rows)} new rows, {len(merged)} total'
    manifest.sample = sample.as_dict()
    _record_run(config, 'ingest', [str(constituents)], manifest)
    LOGGER.info('indexed %d new documents (%d total) -> %s', len(rows), len(merged), target_index)
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    """Run extraction over the document index and consolidate the results."""
    import asyncio

    from nowcast.extraction.runner import consolidate, load_documents, run_extraction
    from nowcast.ingestion.rebuild import index_path
    from nowcast.llm.composition import make_caller
    from nowcast.llm.ledger import BudgetLedger

    config = _load(args)
    validate_config(config, strict=True)
    manifest = start_manifest(config, stage='extract')
    manifest.prompt_hashes = _prompt_fingerprints(config)
    source_index = index_path(config)
    if not source_index.is_file():
        raise DataError(f'no document index at {source_index}; run ingest or rebuild-index first')
    documents = load_documents(config, source_index)
    from nowcast.scope import dimensions, freeze_scope

    if any(dimensions(config)):
        from nowcast.ingestion.constituents import load_constituents

        members = load_constituents(resolve_data_path(config, config.data.constituents_csv))
        panel = freeze_scope(config, members)
        pairs = {(row['cik'], row['season']) for row in panel['pairs']}
        from nowcast.extraction.selection import season_of_date

        documents = [
            doc
            for doc in documents
            if (str(doc.cik).zfill(10), season_of_date(doc.report_date)) in pairs
        ]
    from nowcast.registry import load_registry

    registry = load_registry(config)
    maximum_requests = len(documents) * int(config.llm.retry_attempts)
    if maximum_requests > registry.limits.maximum_requests:
        raise DataError('maximum extraction request plan exceeds configured maximum')
    # `--limit` is the index head — the oldest filings of a few companies. `--sample`
    # takes one document per company first, spread across seasons, so a capped run
    # describes the index rather than the alphabet.
    if args.sample:
        from nowcast.extraction.selection import describe, season_of_date, stratified_sample

        seeds = int(args.seed) if args.seed is not None else int(config.aggregation.sample_seed)
        documents = stratified_sample(documents, int(args.sample), seeds)
        # The season a document was sampled for is part of its result key, so a different
        # cohort cannot silently resume this run's records.
        sampled = [
            dataclasses.replace(item, season=season_of_date(item.report_date)) for item in documents
        ]
        documents = sampled
        LOGGER.info('sampled %s seed=%d', describe(documents), seeds)
    elif args.limit:
        LOGGER.warning('--limit takes the head of the index, which is not a representative sample')
        documents = documents[: int(args.limit)]
    if not documents:
        LOGGER.info('no documents to extract')
        return 0

    ledger = BudgetLedger(
        resolve_data_path(config, config.budget.ledger_path), config.budget.max_usd
    )
    models = list(config.llm.models[:1])
    shared: Any = None

    def factory(model: str) -> Any:
        """Return the composed caller built at the one composition point."""
        nonlocal shared
        del model
        if shared is None:
            shared = make_caller(config, ledger=ledger)
        return shared

    try:
        outcomes = asyncio.run(run_extraction(config, documents, factory, models))
    finally:
        if shared is not None:
            shared.close()  # the composition owns exactly one client
        ledger.flush()
    ok = sum(1 for item in outcomes if item.status == 'ok')
    failed = sum(1 for item in outcomes if item.status == 'failed')
    review = sum(1 for item in outcomes if item.review_reasons)
    empty = sum(1 for item in outcomes if 'empty_extraction' in item.review_reasons)
    LOGGER.info(
        'extracted: %d ok, %d failed, %d flagged for review (%d empty extractions)',
        ok,
        failed,
        review,
        empty,
    )
    from nowcast.extraction.runner import write_consolidated

    combined = consolidate(config, models)
    write_consolidated(config, combined)
    manifest.notes = (
        f'{ok} ok, {failed} failed, {review} flagged ({empty} empty); {len(combined)} rows'
    )
    _record_run(config, 'extract', [str(source_index)], manifest)
    LOGGER.info('consolidated %d rows', len(combined))
    if any(item.status == 'budget_stopped' for item in outcomes):
        raise BudgetExceeded('request budget exhausted; partial extraction results preserved')
    return 1 if any(item.status == 'failed' for item in outcomes) else 0


def _cmd_rebuild_index(args: argparse.Namespace) -> int:
    """Validate an existing index and write a clean copy to data.document_index."""
    from nowcast.ingestion.doc_index import load_index
    from nowcast.ingestion.rebuild import (
        default_source,
        rebuild_index,
        write_rebuild_report,
    )

    config = _load(args)
    validate_config(config, strict=True)
    chosen = getattr(args, 'source', None)
    active = resolve_data_path(config, config.data.document_index)
    if not chosen and active.is_file() and not load_index(active).empty:
        raise DataError('replacing a populated index requires an explicit --source')
    source = Path(chosen) if chosen else default_source(config)
    if not source.is_file():
        raise DataError(f'no index to rebuild at {source}')
    frame = load_index(source)
    report = rebuild_index(config, frame, source_path=source, force=bool(args.force))
    report_file = write_rebuild_report(config, report)
    LOGGER.info(
        'rebuilt %d rows from %s; %d kept, %d dropped; report at %s',
        report.source_rows,
        source,
        report.kept_rows,
        len(report.dropped_documents),
        report_file,
    )
    if report.kept_rows == 0 and report.source_rows > 0:
        raise DataError(
            f'rebuild kept none of {report.source_rows} rows: the source index carries no '
            f'2.02 text rows inside the window; see {report_file}'
        )
    if report.superseded_extractions or report.superseded_queue_rows:
        LOGGER.info(
            'moved %d extraction results and %d review rows to superseded/',
            len(report.superseded_extractions),
            report.superseded_queue_rows,
        )
    return 0


def _cmd_aggregate(args: argparse.Namespace) -> int:
    """Aggregate consolidated extractions into index-level rows, privacy check first."""
    from nowcast.aggregation.aggregate import aggregate_index, assert_index_level_only
    from nowcast.extraction.runner import consolidated_path
    from nowcast.ingestion.constituents import load_constituents

    config = _load(args)
    validate_config(config, strict=True)
    manifest = start_manifest(config, stage='aggregate')
    source = consolidated_path(config)
    if not source.is_file():
        raise DataError(f'no consolidated extractions at {source}; run extract first')
    frame = pd.read_parquet(source)
    constituents_path = resolve_data_path(config, config.data.constituents_csv)
    constituents = load_constituents(constituents_path)
    aggregate = aggregate_index(config, frame, str(constituents_path))
    # The guardrail runs before the write, not after: a file that exists has been read.
    assert_index_level_only(aggregate, constituents)
    target = aggregates_dir(config) / 'index_aggregates.parquet'
    target.parent.mkdir(parents=True, exist_ok=True)
    aggregate.to_parquet(target, index=False)
    aggregate.to_csv(target.with_suffix('.csv'), index=False)
    unsuppressed = int((~aggregate['suppressed']).sum()) if not aggregate.empty else 0
    manifest.notes = f'{len(aggregate)} rows, {unsuppressed} unsuppressed'
    _record_run(config, 'aggregate', [str(source)], manifest)
    LOGGER.info('aggregated %d rows (%d unsuppressed) -> %s', len(aggregate), unsuppressed, target)
    return 0


def _cmd_model_bakeoff(args: argparse.Namespace) -> int:
    """Measure every configured free model on the same real releases."""
    from nowcast.extraction.bakeoff import run_bakeoff
    from nowcast.ingestion.rebuild import index_path

    config = _load(args)
    validate_config(config, strict=True)
    source = index_path(config)
    if not source.is_file():
        raise DataError(f'no document index at {source}; run rebuild-index first')
    models = args.model or list(config.llm.models)
    table = run_bakeoff(
        config,
        models,
        source,
        int(args.sample),
        labels=Path(args.labels) if getattr(args, 'labels', None) else None,
    )
    target = manifests_dir(config) / 'bakeoff.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(table, indent=2), encoding='utf-8')
    for row in table['models']:
        LOGGER.info('bakeoff %s', json.dumps(row))
    LOGGER.info('bakeoff written: %s', target)
    return 0


def _not_implemented(name: str) -> int:
    """Refuse a stage that Gate R0 has not reached yet, and say so."""
    LOGGER.error('%s is not implemented; Gate R0 must be green first', name)
    return 2


def _cmd_run_all(args: argparse.Namespace) -> int:
    """Run validate-config, build-constituents, ingest, extract and aggregate in order."""
    steps = (
        _cmd_validate_config,
        _cmd_build_constituents,
        _cmd_ingest,
        _cmd_extract,
        _cmd_aggregate,
    )
    for step in steps:
        code = step(args)
        if code != 0:
            return code
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with every subcommand."""
    parser = argparse.ArgumentParser(
        prog='nowcast', description='Index-level earnings nowcast pipeline'
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    common = {
        'validate-config': (_cmd_validate_config, 'check config values and required env'),
        'build-constituents': (_cmd_build_constituents, 'build the point-in-time constituents CSV'),
        'estimate-scope': (_cmd_estimate_scope, 'estimate documents and tokens, offline'),
        'ingest': (_cmd_ingest, 'download and index earnings documents'),
        'rebuild-index': (_cmd_rebuild_index, 'validate an index into data.document_index'),
        'extract': (_cmd_extract, 'run LLM extraction over indexed documents'),
        'aggregate': (_cmd_aggregate, 'aggregate extractions into index-level rows'),
        'model-bakeoff': (_cmd_model_bakeoff, 'measure every configured model on one sample'),
        'run-all': (_cmd_run_all, 'run every stage in order'),
    }
    for name, (handler, help_text) in common.items():
        sub = subparsers.add_parser(name, help=help_text)
        _add_common(sub)
        if name == 'extract':
            sub.add_argument('--limit', type=int, default=0, help='only the first N documents')
            sub.add_argument(
                '--sample',
                type=int,
                default=0,
                help='N documents, one per company first and spread across seasons',
            )
            sub.add_argument('--seed', type=int, default=None, help='seed for --sample')
        if name == 'rebuild-index':
            sub.add_argument(
                '--source', default='', help='index to validate (default: the pre-v2 index)'
            )
            sub.add_argument(
                '--force',
                action='store_true',
                help='replace a populated data.document_index after backing it up',
            )
        if name == 'model-bakeoff':
            sub.add_argument(
                '--sample', type=int, default=10, help='documents each model is measured on'
            )
            sub.add_argument('--model', action='append', default=[], help='model (repeatable)')
            sub.add_argument('--labels', type=Path, default=None, help='supplied human labels')
        if name == 'validate-config':
            sub.add_argument(
                '--strict',
                action='store_true',
                help='also require the secret environment variables to be set',
            )
        sub.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ConfigError, DataError, NowcastError) as exc:
        LOGGER.error('error: %s', exc)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
