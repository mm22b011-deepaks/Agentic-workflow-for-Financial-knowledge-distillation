"""Command-line entry point for the index earnings nowcast pipeline."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from nowcast.config import (
    Config,
    data_root,
    load_config,
    manifests_dir,
    prompts_dir,
    resolve_data_path,
    validate_config,
)
from nowcast.errors import ConfigError, DataError, NowcastError
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


def _bootstrap_dotenv(candidates: tuple[Path, ...] = (Path('.env'),)) -> None:
    """Fill unset variables from a local .env, never overriding the real environment.

    A deployed environment (or a Colab secret) always wins; the .env file only
    supplies what is missing, which is what makes a local CLI run convenient
    without letting a checked-out file clobber real credentials.
    """
    from dotenv import load_dotenv

    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(candidate, override=False)


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
    _bootstrap_dotenv((path.resolve().parent.parent / '.env', Path('.env')))
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
    from nowcast.ingestion.constituents import cik_list
    from nowcast.ingestion.doc_index import load_index, upsert_rows, write_index
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

    frame = load_constituents(constituents)
    ciks = cik_list(frame)
    limit = int(config.data.edgar_max_documents)
    LOGGER.info('ingesting for %d companies, cap %d documents', len(ciks), limit)
    report = IngestReport()
    report_path = manifests_dir(config) / 'ingest_report.json'
    try:
        rows = ingest_edgar(
            config,
            ciks,
            max_documents=limit,
            per_cik_limit=int(config.data.edgar_docs_per_cik),
            report=report,
        )
    finally:
        # Written even on the abort path: the reason the run stopped is the most useful
        # thing the file can say, and losing it to an exception would be absurd.
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.as_dict(), indent=2), encoding='utf-8')
    target_index = index_path(config)
    existing = load_index(target_index)
    merged = upsert_rows(existing, rows)
    write_index(merged, target_index)
    summary = {
        'new_rows': len(rows),
        'index_rows': len(merged),
        'companies': len(ciks),
        'cap': limit,
        'start_date': config.data.start_date,
        'end_date': config.data.end_date,
        'status_counts': report.status_counts,
        'skip_reasons': report.skip_reasons,
        'zero_disclosure_companies': len(report.zero_disclosure_ciks),
    }
    target = manifests_dir(config) / 'ingest_summary.json'
    target.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    manifest.notes = f'indexed {len(rows)} new rows, {len(merged)} total'
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
    limit = int(args.limit) if args.limit else len(documents)
    documents = documents[:limit]
    if not documents:
        LOGGER.info('no documents to extract')
        return 0

    ledger = BudgetLedger(
        resolve_data_path(config, config.budget.ledger_path), config.budget.max_usd
    )
    models = list(config.llm.models)
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
            shared._caller.close()  # the composition owns exactly one client
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
    combined = consolidate(config, models)
    manifest.notes = (
        f'{ok} ok, {failed} failed, {review} flagged ({empty} empty); {len(combined)} rows'
    )
    _record_run(config, 'extract', [str(source_index)], manifest)
    LOGGER.info('consolidated %d rows', len(combined))
    return 0


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
    source = Path(chosen) if chosen else default_source(config)
    if not source.is_file():
        raise DataError(f'no index to rebuild at {source}')
    frame = load_index(source)
    report = rebuild_index(config, frame, source_path=source)
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


def _cmd_run_all(args: argparse.Namespace) -> int:
    """Run validate-config, build-constituents, ingest and extract in order."""
    steps = (_cmd_validate_config, _cmd_build_constituents, _cmd_ingest, _cmd_extract)
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
        'run-all': (_cmd_run_all, 'run every stage in order'),
    }
    for name, (handler, help_text) in common.items():
        sub = subparsers.add_parser(name, help=help_text)
        _add_common(sub)
        if name == 'extract':
            sub.add_argument('--limit', type=int, default=0, help='only the first N documents')
        if name == 'rebuild-index':
            sub.add_argument(
                '--source', default='', help='index to validate (default: the pre-v2 index)'
            )
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
