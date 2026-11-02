"""Resolve tickers to SEC CIKs without ever guessing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from nowcast.config import Config, data_root
from nowcast.errors import DataError
from nowcast.ingestion.universe.base import fetch_bytes, normalise_ticker, to_date, user_agent

UNRESOLVED = 'UNRESOLVED'
RULE_OVERRIDE = 'override'
RULE_HINT = 'hint'
RULE_SEC = 'sec_map'
CIK_LENGTH = 10


@dataclass
class MappingResult:
    """Resolved intervals plus the rows that could not be resolved."""

    frame: pd.DataFrame
    unmapped: pd.DataFrame


def load_overrides(config: Config, root: Path | None = None) -> pd.DataFrame:
    """Load the optional CIK override CSV keyed by ticker and date range.

    Relative paths are searched under each of `root`, the data root, and the
    working directory, so the same config works from the repo and from a notebook.
    """
    empty = pd.DataFrame(columns=['ticker', 'cik', 'effective_from', 'effective_to'])
    location = config.universe.cik_overrides_csv
    if not location:
        return empty
    candidate = Path(location)
    path: Path | None = None
    if candidate.is_absolute():
        path = candidate
    else:
        bases = [
            base
            for base in (
                root,
                data_root(config),
                Path(config.config_dir) / config.paths.project_dir,
            )
            if base is not None
        ]
        found = next((base / candidate for base in bases if (base / candidate).is_file()), None)
        if found is None:
            # The overrides file is optional: its absence means "no overrides", not an error.
            return empty
        path = found
    if not path.is_file():
        return empty
    frame = pd.read_csv(path, dtype={'cik': str})
    required = {'ticker', 'cik'}
    missing = required - set(frame.columns)
    if missing:
        raise DataError(f'CIK overrides {path} is missing columns: {", ".join(sorted(missing))}')
    frame['ticker'] = frame['ticker'].map(normalise_ticker)
    frame['effective_from'] = frame.get('effective_from', pd.Series([None] * len(frame))).map(
        to_date
    )
    frame['effective_to'] = frame.get('effective_to', pd.Series([None] * len(frame))).map(to_date)
    return frame


def load_sec_map(
    config: Config, cache_root: Path, transport: object | None = None
) -> dict[str, str]:
    """Load the SEC ticker-to-CIK map, cached on disk."""
    settings = config.universe
    if not settings.sec_ticker_map_url:
        raise DataError('universe.sec_ticker_map_url must be set')
    fetched = fetch_bytes(
        settings.sec_ticker_map_url,
        cache_root,
        user_agent(config),
        settings.refresh,
        transport=transport,  # type: ignore[arg-type]
    )
    payload = json.loads(fetched.cache_path.read_text(encoding='utf-8'))
    mapping: dict[str, str] = {}
    if isinstance(payload, dict):
        for item in payload.values():
            if isinstance(item, dict) and 'ticker' in item and 'cik_str' in item:
                mapping[normalise_ticker(item['ticker'])] = str(item['cik_str']).zfill(CIK_LENGTH)
    return mapping


def _override_for(overrides: pd.DataFrame, ticker: str, day: object) -> str | None:
    """Return the override CIK matching a ticker and date, if any."""
    if overrides.empty:
        return None
    stamp = pd.Timestamp(str(day)) if day is not None else None
    rows = overrides[overrides['ticker'] == ticker]
    for record in rows.to_dict('records'):
        start = record.get('effective_from')
        end = record.get('effective_to')
        if stamp is None:
            return str(record['cik']).zfill(CIK_LENGTH)
        if start is not None and pd.Timestamp(str(start)) > stamp:
            continue
        if end is not None and pd.Timestamp(str(end)) < stamp:
            continue
        return str(record['cik']).zfill(CIK_LENGTH)
    return None


def map_ciks(
    frame: pd.DataFrame,
    overrides: pd.DataFrame,
    sec_map: dict[str, str],
) -> MappingResult:
    """Resolve every interval's CIK using override, then hint, then SEC map."""
    resolved_rows: list[dict[str, object]] = []
    unmapped_rows: list[dict[str, object]] = []
    for record in frame.to_dict('records'):
        ticker = normalise_ticker(record['ticker'])
        cik: str | None = _override_for(overrides, ticker, record.get('effective_from'))
        source = RULE_OVERRIDE
        if cik is None:
            hint = record.get('cik_hint')
            if isinstance(hint, str) and hint.strip().isdigit():
                cik = hint.strip().zfill(CIK_LENGTH)
                source = RULE_HINT
            else:
                mapped = sec_map.get(ticker)
                if mapped:
                    cik = mapped.zfill(CIK_LENGTH)
                    source = RULE_SEC
        row: dict[str, object] = {str(key): value for key, value in record.items()}
        row['ticker'] = ticker
        if cik is None:
            row['cik'] = UNRESOLVED
            row['cik_source'] = UNRESOLVED
            unmapped_rows.append(row)
        else:
            row['cik'] = cik.zfill(CIK_LENGTH)
            row['cik_source'] = source
        resolved_rows.append(row)
    resolved = pd.DataFrame(resolved_rows)
    unmapped = pd.DataFrame(unmapped_rows)
    if resolved.empty:
        resolved = pd.DataFrame(
            columns=[
                'ticker',
                'company_name',
                'effective_from',
                'effective_to',
                'cik',
                'cik_source',
            ]
        )
    return MappingResult(frame=resolved, unmapped=unmapped)
