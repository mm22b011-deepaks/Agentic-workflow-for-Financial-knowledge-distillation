"""End-to-end universe build: source, CIK mapping, validation, artifacts."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from nowcast.config import FREE_MODEL_SUFFIX, Config, data_root
from nowcast.errors import DataError
from nowcast.ingestion.constituents import load_constituents
from nowcast.ingestion.universe import historical_csv_source, wikipedia_source
from nowcast.ingestion.universe.base import Anomaly, MembershipSource, cache_path_for
from nowcast.ingestion.universe.cik_mapper import UNRESOLVED, load_overrides, load_sec_map, map_ciks
from nowcast.ingestion.universe.validate import (
    check_coverage,
    check_overlaps,
    member_count_audit,
)

LOGGER = logging.getLogger(__name__)
CONSTITUENTS_COLUMNS = (
    'ticker',
    'cik',
    'effective_from',
    'effective_to',
    'company_name',
    'cik_source',
)


def universe_dir(config: Config) -> Path:
    """Return the universe output directory, creating it."""
    target = data_root(config) / 'universe'
    target.mkdir(parents=True, exist_ok=True)
    return target


def cache_root(config: Config) -> Path:
    """Return the cache directory for universe downloads."""
    target = data_root(config) / 'raw' / 'universe'
    target.mkdir(parents=True, exist_ok=True)
    return target


def config_hash(config: Config) -> str:
    """Return a hash of the universe and date-window settings."""
    payload = {
        'universe': config.universe.__dict__,
        'start_date': config.data.start_date,
        'end_date': config.data.end_date,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
    ).hexdigest()


def _resolve_input(config: Config, relative: str) -> Path | None:
    """Find an input file under the data root, the project root, or as given.

    Returns None when the path is unset or nothing exists at it, so callers can
    distinguish "not configured" from "configured but missing".
    """
    if not relative:
        return None
    candidate = Path(relative)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    for base in (data_root(config), Path.cwd()):
        path = base / candidate
        if path.is_file():
            return path
    return None


def _file_sha256(path: Path) -> str:
    """Hash a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_input_hashes(config: Config) -> dict[str, str]:
    """Hash the local copy of every input the build depends on.

    An input that has not been downloaded yet yields an empty result, so a missing
    local copy forces a real build instead of a skip on absent evidence.
    """
    settings = config.universe
    cache = cache_root(config)
    hashes: dict[str, str] = {}
    if settings.source == 'wikipedia_changes':
        pairs = (
            ('current_sha256', settings.current_table_url),
            ('changes_sha256', settings.changes_table_url),
        )
        for key, url in pairs:
            if not url:
                return {}
            path = cache_path_for(cache, url)
            if not path.is_file():
                return {}
            hashes[key] = _file_sha256(path)
    elif settings.source == 'historical_csv':
        location = settings.historical_csv_path_or_url
        if not location:
            return {}
        if location.startswith(('http://', 'https://')):
            path = cache_path_for(cache, location).with_suffix('.raw')
        else:
            path = Path(location)
        if not path.is_file():
            return {}
        hashes['historical_sha256'] = _file_sha256(path)
    else:
        return {}
    if settings.sec_ticker_map_url:
        sec_path = cache_path_for(cache, settings.sec_ticker_map_url).with_suffix('.raw')
        if not sec_path.is_file():
            return {}
        hashes['sec_map_sha256'] = _file_sha256(sec_path)
    if settings.cik_overrides_csv:
        overrides_path = _resolve_input(config, settings.cik_overrides_csv)
        if overrides_path is not None:
            hashes['cik_overrides_sha256'] = _file_sha256(overrides_path)
    return hashes


def select_source(config: Config, transport: object | None = None) -> MembershipSource:
    """Fetch membership from the source named in config."""
    if config.universe.source == 'wikipedia_changes':
        return wikipedia_source.load_source(config, cache_root(config), transport=transport)
    if config.universe.source == 'historical_csv':
        return historical_csv_source.load_source(config, cache_root(config))
    raise DataError(f'unknown universe.source {config.universe.source!r}')


def deterministic_subset(frame: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Pick a deterministic sample of companies, keeping all their intervals."""
    if n <= 0 or frame.empty:
        return frame
    tickers = sorted(frame['ticker'].unique())
    if n >= len(tickers):
        return frame
    rng = __import__('random').Random(seed)
    chosen = sorted(rng.sample(tickers, n))
    return frame[frame['ticker'].isin(chosen)].reset_index(drop=True)


def _write_unmapped(path: Path, unmapped: pd.DataFrame) -> None:
    """Write unresolved rows for manual review."""
    if unmapped.empty:
        if path.is_file():
            path.unlink()
        return
    unmapped.to_csv(path, index=False)


def _write_anomalies(path: Path, anomalies: list[Anomaly], extra: list[dict[str, str]]) -> int:
    """Write anomalies to CSV and return the total count."""
    rows = [
        {
            'kind': item.kind,
            'ticker': item.ticker,
            'company_name': item.company_name,
            'event_date': item.event_date,
            'detail': item.detail,
            'source': item.source,
        }
        for item in anomalies
    ]
    rows.extend(
        {
            'kind': item.get('kind', ''),
            'ticker': item.get('ticker', ''),
            'company_name': item.get('company_name', ''),
            'event_date': '',
            'detail': item.get('detail', ''),
            'source': 'validate',
        }
        for item in extra
    )
    frame = pd.DataFrame(
        rows, columns=['kind', 'ticker', 'company_name', 'event_date', 'detail', 'source']
    )
    if frame.empty:
        frame.to_csv(path, index=False)
        return 0
    frame.to_csv(path, index=False)
    return len(frame)


def build_constituents(config: Config, transport: object | None = None) -> Path:
    """Build data/universe/constituents.csv and its report, idempotently."""
    out_dir = universe_dir(config)
    report_path = out_dir / 'build_report.json'
    constituents_path = out_dir / 'constituents.csv'
    run_hash = config_hash(config)
    if report_path.is_file() and constituents_path.is_file() and not config.universe.refresh:
        previous = json.loads(report_path.read_text(encoding='utf-8'))
        stored = previous.get('input_hashes')
        current = current_input_hashes(config)
        if (
            previous.get('config_hash') == run_hash
            and isinstance(stored, dict)
            and current
            and stored == current
        ):
            LOGGER.info(
                'universe build up to date (config and inputs unchanged): %s', constituents_path
            )
            return constituents_path

    source = select_source(config, transport=transport)
    overrides = load_overrides(config)
    sec_map = load_sec_map(config, cache_root(config), transport=transport)
    mapped = map_ciks(source.frame, overrides, sec_map)
    _overlap_frame, overlap_anomalies = check_overlaps(mapped.frame)

    unmapped_path = out_dir / 'unmapped.csv'
    _write_unmapped(unmapped_path, mapped.unmapped)
    anomalies_path = out_dir / 'anomalies.csv'
    anomaly_count = _write_anomalies(anomalies_path, source.anomalies, overlap_anomalies)

    coverage = check_coverage(
        mapped.frame,
        config,
        str(unmapped_path),
        len(mapped.unmapped),
    )
    audit = member_count_audit(mapped.frame, config)
    audit_path = out_dir / 'member_count_audit.csv'
    audit.to_csv(audit_path, index=False)

    output = mapped.frame.copy()
    output['effective_from'] = pd.to_datetime(output['effective_from']).dt.date
    output['effective_to'] = pd.to_datetime(output['effective_to']).dt.date
    subset = deterministic_subset(
        output, int(config.universe.subset_n), int(config.universe.subset_seed)
    )
    subset = subset[list(CONSTITUENTS_COLUMNS)]
    subset.to_csv(constituents_path, index=False)

    # Hash the local copies so the next run can compare like with like and skip.
    input_hashes = current_input_hashes(config) or {
        key: str(value) for key, value in source.provenance.items() if key.endswith('_sha256')
    }
    report: dict[str, Any] = {
        'config_hash': run_hash,
        'source': config.universe.source,
        'inputs': source.provenance,
        'input_hashes': input_hashes,
        'row_counts': {
            'intervals': len(output),
            'written': len(subset),
            'companies': int(output['ticker'].nunique()),
            'unmapped': len(mapped.unmapped),
        },
        'anomaly_count': anomaly_count,
        'unmapped_count': len(mapped.unmapped),
        'cik_coverage': coverage,
        'member_count_audit': {
            'sample_dates': len(audit),
            'flagged_dates': int(audit['flagged'].sum()) if not audit.empty else 0,
            'min_members': int(audit['member_count'].min()) if not audit.empty else 0,
            'max_members': int(audit['member_count'].max()) if not audit.empty else 0,
            'path': str(audit_path),
        },
        'cik_sources': output['cik_source'].value_counts().to_dict(),
        'licence_note': config.universe.licence_note,
        'paths': {
            'constituents': str(constituents_path),
            'unmapped': str(unmapped_path),
            'anomalies': str(anomalies_path),
            'audit': str(audit_path),
        },
    }
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    LOGGER.info(
        'universe built: %d intervals, %d companies, CIK coverage %.3f, anomalies %d, unmapped %d',
        len(subset),
        output['ticker'].nunique(),
        coverage,
        anomaly_count,
        len(mapped.unmapped),
    )
    LOGGER.info('use it with: --set data.constituents_csv=%s', constituents_path)
    return constituents_path


def coverage_summary(config: Config) -> dict[str, float]:
    """Return the unresolved share from the latest build report."""
    report_path = universe_dir(config) / 'build_report.json'
    if not report_path.is_file():
        raise DataError(f'no build report at {report_path}; run build-constituents first')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    return {
        'cik_coverage': float(report.get('cik_coverage', 0.0)),
        'unmapped_count': float(report.get('unmapped_count', 0)),
    }


@dataclass(frozen=True)
class ScopeEstimate:
    """A labelled estimate; never a promise of document count or cost."""

    companies: int
    quarters: int
    company_quarters: int
    document_types: tuple[str, ...]
    documents: int
    input_tokens: int
    output_tokens: int
    models: tuple[str, ...]

    def as_lines(self) -> list[str]:
        """Render the estimate as printable lines, explicitly labelled an estimate."""
        lines = [
            'ESTIMATE ONLY - not a promise of cost or document count',
            f'  companies                 {self.companies}',
            f'  calendar quarters         {self.quarters}',
            f'  company-quarters          {self.company_quarters}',
            f'  document types            {", ".join(self.document_types) or "(none)"}',
            f'  expected documents        {self.documents}',
            f'  estimated input tokens    {self.input_tokens:,}',
            f'  estimated output tokens   {self.output_tokens:,}',
            f'  models                    {", ".join(self.models) or "(none)"}',
        ]
        free_only = bool(self.models) and all(
            model.endswith(FREE_MODEL_SUFFIX) for model in self.models
        )
        if free_only:
            lines.append(
                '  estimated cost            $0.00 (all configured models are free models)'
            )
        else:
            lines.append(
                '  estimated cost            unknown: only free models are permitted, and no '
                'price table is configured'
            )
        return lines


def _quarter_map(frame: pd.DataFrame, start: str, end: str) -> dict[pd.Period, set[str]]:
    """Map each quarter in the window to the tickers that were members during it."""
    first = pd.Timestamp(start)
    last = pd.Timestamp(end)
    quarters: dict[pd.Period, set[str]] = {}
    for record in frame.to_dict('records'):
        begin = max(pd.Timestamp(record['effective_from']), first)
        finish = record.get('effective_to')
        finish_stamp = (
            last if finish is None or pd.isna(finish) else min(pd.Timestamp(finish), last)
        )
        if begin > finish_stamp:
            continue
        for quarter in pd.period_range(begin, finish_stamp, freq='Q'):
            quarters.setdefault(quarter, set()).add(str(record['ticker']))
    return quarters


def estimate_scope(config: Config, constituents_path: Path | None = None) -> ScopeEstimate:
    """Estimate document counts and token load from constituents and config.

    Reads only local files and config: it makes no network calls.
    """
    if constituents_path is not None:
        path = constituents_path
        if not path.is_file():
            raise DataError(f'constituents file not found: {path}')
    else:
        found = _resolve_input(config, config.data.constituents_csv)
        if found is None:
            raise DataError(
                f'constituents file not found: {config.data.constituents_csv} '
                '(set data.constituents_csv, or build it with build-constituents)'
            )
        path = found
    frame = load_constituents(path)
    if frame.empty:
        raise DataError(f'constituents file {path} has no rows')
    if not config.data.start_date or not config.data.end_date:
        raise DataError('data.start_date and data.end_date must both be set for estimate-scope')

    companies = int(frame['ticker'].nunique())
    quarter_map = _quarter_map(frame, config.data.start_date, config.data.end_date)
    document_types = tuple(config.data.edgar_forms) or ('8-K',)
    company_quarters = sum(len(tickers) for tickers in quarter_map.values())
    # Company-quarters times document types: a company that joined mid-window is
    # counted only for the quarters it was actually an index member.
    documents = company_quarters * len(document_types)
    per_doc_in = int(config.universe.avg_tokens_per_doc_in)
    per_doc_out = int(config.universe.avg_tokens_per_doc_out)
    return ScopeEstimate(
        companies=companies,
        quarters=len(quarter_map),
        company_quarters=company_quarters,
        document_types=document_types,
        documents=documents,
        input_tokens=documents * per_doc_in,
        output_tokens=documents * per_doc_out,
        models=tuple(config.llm.models),
    )


def unresolved_tickers(config: Config) -> list[str]:
    """Return unresolved tickers from the last build's unmapped file."""
    path = universe_dir(config) / 'unmapped.csv'
    if not path.is_file():
        return []
    frame = pd.read_csv(path)
    if 'ticker' not in frame.columns:
        return []
    if 'cik' not in frame.columns:
        return []
    unresolved_mask = frame['cik'].astype(str) == UNRESOLVED
    values = frame.loc[unresolved_mask, 'ticker'].tolist()
    return sorted({str(value) for value in values})
