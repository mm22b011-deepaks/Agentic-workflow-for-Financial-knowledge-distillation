"""Shared types and helpers for universe membership sources."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx
import pandas as pd

from nowcast.config import Config, UniverseConfig
from nowcast.errors import ConfigError

LOGGER = logging.getLogger(__name__)
MEMBERSHIP_COLUMNS = ('ticker', 'company_name', 'effective_from', 'effective_to', 'cik_hint')


@dataclass(frozen=True)
class FetchResult:
    """One fetched table, with provenance."""

    url: str
    sha256: str
    fetched_at: str
    cache_path: Path
    from_cache: bool


@dataclass
class Anomaly:
    """One problem found while reconstructing membership."""

    kind: str
    detail: str
    ticker: str = ''
    company_name: str = ''
    event_date: str = ''
    source: str = ''


@dataclass
class MembershipSource:
    """A source of index membership intervals."""

    frame: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=list(MEMBERSHIP_COLUMNS))
    )
    anomalies: list[Anomaly] = field(default_factory=list)
    provenance: dict[str, object] = field(default_factory=dict)


class MembershipSourceProtocol(Protocol):
    """Anything that can produce membership intervals."""

    def fetch(self) -> MembershipSource:
        """Fetch and return membership intervals."""


def user_agent(config: Config | UniverseConfig) -> str:
    """Return the User-Agent named by the universe config, raising if unset."""
    env_name = (
        config.http_user_agent_env
        if isinstance(config, UniverseConfig)
        else config.universe.http_user_agent_env
    )
    value = os.environ.get(env_name, '')
    if not value:
        raise ConfigError(f'environment variable {env_name!r} is not set')
    return value


def cache_path_for(directory: Path, url: str) -> Path:
    """Return the cache file path for a URL, keyed by its hash."""
    digest = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
    return directory / f'{digest}.html'


def fetch_html(
    url: str,
    directory: Path,
    agent: str,
    refresh: bool,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> FetchResult:
    """Fetch a URL through the on-disk cache and return the text with provenance."""
    directory.mkdir(parents=True, exist_ok=True)
    cache_path = cache_path_for(directory, url)
    meta_path = cache_path.with_suffix('.json')
    stamp = datetime.now(timezone.utc).isoformat()
    if not refresh and cache_path.is_file() and meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        return FetchResult(
            url=url,
            sha256=str(meta.get('sha256', '')),
            fetched_at=str(meta.get('fetched_at', '')),
            cache_path=cache_path,
            from_cache=True,
        )
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers={'User-Agent': agent})
        response.raise_for_status()
    text = response.text
    cache_path.write_text(text, encoding='utf-8')
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    meta_path.write_text(
        json.dumps({'url': url, 'sha256': digest, 'fetched_at': stamp}), encoding='utf-8'
    )
    return FetchResult(
        url=url, sha256=digest, fetched_at=stamp, cache_path=cache_path, from_cache=False
    )


def fetch_bytes(
    url: str,
    directory: Path,
    agent: str,
    refresh: bool,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> FetchResult:
    """Fetch a URL (any content type) through the on-disk cache."""
    directory.mkdir(parents=True, exist_ok=True)
    cache_path = cache_path_for(directory, url).with_suffix('.raw')
    meta_path = cache_path.with_suffix('.json')
    stamp = datetime.now(timezone.utc).isoformat()
    if not refresh and cache_path.is_file() and meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        return FetchResult(
            url=url,
            sha256=str(meta.get('sha256', '')),
            fetched_at=str(meta.get('fetched_at', '')),
            cache_path=cache_path,
            from_cache=True,
        )
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers={'User-Agent': agent})
        response.raise_for_status()
    cache_path.write_bytes(response.content)
    digest = hashlib.sha256(response.content).hexdigest()
    meta_path.write_text(
        json.dumps({'url': url, 'sha256': digest, 'fetched_at': stamp}), encoding='utf-8'
    )
    return FetchResult(
        url=url, sha256=digest, fetched_at=stamp, cache_path=cache_path, from_cache=False
    )


def to_date(value: object) -> date | None:
    """Parse a date-like value, returning None when it cannot be parsed."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {'nan', 'nat', 'none'}:
        return None
    try:
        return pd.Timestamp(text).date()
    except (ValueError, TypeError):
        return None


NULL_TEXT = {'', 'nan', 'nat', 'none', 'null'}


def normalise_ticker(value: object) -> str:
    """Normalise a ticker to upper case with dots replaced by dashes.

    Missing values (an empty cell, NaN from the HTML parse) become an empty string
    rather than a ticker literally named ``NAN``.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    text = str(value).strip().upper()
    if text.lower() in NULL_TEXT:
        return ''
    return text.replace('.', '-')


def empty_membership() -> pd.DataFrame:
    """Return an empty membership frame with the canonical columns."""
    return pd.DataFrame(columns=list(MEMBERSHIP_COLUMNS))
