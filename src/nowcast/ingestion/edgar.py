"""SEC EDGAR submissions downloader with rate limiting and resume."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from nowcast.config import Config, data_root, raw_dir
from nowcast.errors import ConfigError, DataError
from nowcast.ingestion.doc_index import file_sha256
from nowcast.parsing.html import html_to_text

LOGGER = logging.getLogger(__name__)
EXHIBIT_FORMS_PREFIX = 'EX-'
EARNINGS_EXHIBIT_TYPE = 'EX-99'
EXHIBIT_99_RE = re.compile(r'ex[-_]?99')


class RateLimiter:
    """Enforces a minimum interval between requests using a monotonic clock."""

    def __init__(self, max_requests_per_sec: float, clock: Any = time.monotonic) -> None:
        """Store the interval and the clock function used for sleeping."""
        if max_requests_per_sec <= 0:
            raise ValueError('max_requests_per_sec must be positive')
        self._interval = 1.0 / float(max_requests_per_sec)
        self._clock = clock
        self._last: float | None = None
        self._sleep = time.sleep

    def wait(self) -> None:
        """Block until the next request is allowed."""
        now = self._clock()
        if self._last is not None:
            remaining = self._interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


@dataclass(frozen=True)
class Disclosure:
    """One filing candidate found in the submissions feed."""

    cik: str
    accession: str
    filing_date: date
    form: str
    exhibit_type: str
    document: str


def user_agent(config: Config) -> str:
    """Return the SEC User-Agent from the configured environment variable."""
    value = os.environ.get(config.data.sec_user_agent_env, '')
    if not value:
        raise ConfigError(
            f'environment variable {config.data.sec_user_agent_env!r} is not set; '
            'SEC requires a User-Agent with a contact address'
        )
    return value


def build_client(config: Config, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Build an httpx client carrying the SEC User-Agent header."""
    return httpx.Client(
        headers={'User-Agent': user_agent(config), 'Accept-Encoding': 'gzip, deflate'},
        timeout=float(config.llm.timeout_seconds),
        transport=transport,
        follow_redirects=True,
    )


def _submissions_url(config: Config, cik: str) -> str:
    """Fill the configured submissions URL template for a padded CIK."""
    return config.data.edgar_submissions_url_template.format(cik_padded=cik.zfill(10))


def _archive_url(config: Config, cik: str, accession: str, filename: str) -> str:
    """Fill the configured archive URL template for one document."""
    return config.data.edgar_archive_url_template.format(
        cik=str(int(cik)), accession_nodash=accession.replace('-', ''), filename=filename
    )


EXHIBIT_TYPE_PREFIX = 'EX-99'
HEADERS_DOC_RE = re.compile(r'<DOCUMENT>(.*?)</DOCUMENT>', re.S)
TYPE_RE = re.compile(r'<TYPE>([^\n<]+)')
FILENAME_RE = re.compile(r'<FILENAME>([^\n<]+)')


def _headers_url(config: Config, cik: str, accession: str) -> str:
    """Return the filing index-headers URL for one accession."""
    return config.data.edgar_index_headers_url_template.format(
        cik=str(int(cik)), accession=accession
    )


def parse_exhibits(headers_html: str) -> list[tuple[str, str]]:
    """Return (type, filename) pairs for EX-99 documents in an index-headers page."""
    unescaped = headers_html.replace('&lt;', '<').replace('&gt;', '>')
    exhibits: list[tuple[str, str]] = []
    for block in HEADERS_DOC_RE.findall(unescaped):
        type_match = TYPE_RE.search(block)
        file_match = FILENAME_RE.search(block)
        if not type_match or not file_match:
            continue
        document_type = type_match.group(1).strip()
        if document_type.startswith(EXHIBIT_TYPE_PREFIX):
            exhibits.append((document_type, file_match.group(1).strip()))
    return exhibits


def is_text_document(filename: str, allowed: tuple[str, ...]) -> bool:
    """Return whether an exhibit filename has a suffix we can parse as text."""
    suffix = Path(filename).suffix.lower()
    return bool(allowed) and suffix in {item.lower() for item in allowed}


def _configured_date(config: Config, value: str) -> date | None:
    """Parse a configured ISO date, returning None when it is blank."""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise DataError(f'configured date {value!r} is not an ISO date (YYYY-MM-DD)') from exc


def fetch_disclosures(
    config: Config,
    cik: str,
    client: httpx.Client,
    limiter: RateLimiter,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[Disclosure]:
    """Fetch earnings 8-K filings for one CIK and locate their EX-99 exhibits."""
    limiter.wait()
    response = client.get(_submissions_url(config, cik))
    if response.status_code == 404:
        LOGGER.warning('CIK %s not found on EDGAR', cik)
        return []
    response.raise_for_status()
    payload = response.json()
    recent = (payload.get('filings') or {}).get('recent') or {}
    accessions = recent.get('accessionNumber') or []
    forms = recent.get('form') or []
    dates = recent.get('filingDate') or []
    items = recent.get('items') or []
    # The window comes from the caller or from the configured data dates, never from
    # the wall clock: a run must be reproducible on any day it is repeated.
    lower = start_date or _configured_date(config, config.data.start_date)
    if lower is None:
        raise DataError(
            'no filing window: set data.start_date or pass start_date, so the run is '
            "reproducible instead of depending on today's date"
        )
    upper = end_date or _configured_date(config, config.data.end_date) or date.today()
    wanted = set(config.data.edgar_forms)
    wanted_items = list(config.data.edgar_earnings_items)
    found: list[Disclosure] = []
    for index, accession in enumerate(accessions):
        form = str(forms[index]) if index < len(forms) else ''
        if form not in wanted:
            continue
        filing_date = date.fromisoformat(str(dates[index])[:10])
        if not lower <= filing_date <= upper:
            continue
        item_text = str(items[index]) if index < len(items) else ''
        item_codes = {code.strip() for code in item_text.split(',') if code.strip()}
        if wanted_items and not item_codes.intersection(wanted_items):
            continue
        limiter.wait()
        try:
            headers_response = client.get(_headers_url(config, cik, accession))
            headers_response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.warning('index headers failed cik=%s accession=%s error=%s', cik, accession, exc)
            continue
        allowed = config.data.edgar_document_suffixes
        for document_type, filename in parse_exhibits(headers_response.text):
            if not is_text_document(filename, allowed):
                # An EX-99 image ("..._ex99-1img001.jpg") is a scanned release; decoding
                # it as HTML yields binary noise and burns a document slot.
                LOGGER.info('skip non-text exhibit cik=%s file=%s', cik, filename)
                continue
            found.append(
                Disclosure(
                    cik=cik,
                    accession=accession,
                    filing_date=filing_date,
                    form=form,
                    exhibit_type=document_type,
                    document=filename,
                )
            )
    return found


def _document_text(path: Path) -> str:
    """Return a downloaded file's text, treating it as HTML only when it looks like HTML."""
    suffix = path.suffix.lower()
    raw = path.read_text(encoding='utf-8', errors='replace')
    if suffix in {'.htm', '.html'}:
        return html_to_text(raw)
    return raw


def download_document(
    config: Config, disclosure: Disclosure, client: httpx.Client, limiter: RateLimiter
) -> Path:
    """Download one document, skipping the request when the file already exists."""
    target_dir = raw_dir(config) / disclosure.cik.zfill(10) / disclosure.accession
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / disclosure.document
    if target.is_file() and target.stat().st_size > 0:
        LOGGER.info('skip existing cik=%s accession=%s', disclosure.cik, disclosure.accession)
        return target
    url = _archive_url(config, disclosure.cik, disclosure.accession, disclosure.document)
    limiter.wait()
    response = client.get(url)
    response.raise_for_status()
    target.write_bytes(response.content)
    LOGGER.info(
        'downloaded cik=%s accession=%s bytes=%d',
        disclosure.cik,
        disclosure.accession,
        len(response.content),
    )
    return target


def ingest_edgar(
    config: Config,
    ciks: list[str],
    client: httpx.Client | None = None,
    limiter: RateLimiter | None = None,
    max_documents: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    per_cik_limit: int | None = None,
) -> list[dict[str, object]]:
    """Download earnings exhibits for the given CIKs and return document index rows."""
    own_client = client is None
    active_client = client or build_client(config)
    active_limiter = limiter or RateLimiter(config.data.sec_max_requests_per_sec)
    limit = max_documents if max_documents is not None else int(config.data.edgar_max_documents)
    per_cik = per_cik_limit if per_cik_limit is not None else int(config.data.edgar_docs_per_cik)
    window_start = start_date or _configured_date(config, config.data.start_date)
    window_end = end_date or _configured_date(config, config.data.end_date)
    rows: list[dict[str, object]] = []
    try:
        for cik in ciks:
            if len(rows) >= limit:
                break
            taken = 0
            try:
                disclosures = fetch_disclosures(
                    config, cik, active_client, active_limiter, window_start, window_end
                )
                disclosures.sort(key=lambda item: item.filing_date, reverse=True)
                for disclosure in disclosures:
                    if len(rows) >= limit or (per_cik and taken >= per_cik):
                        break
                    try:
                        path = download_document(config, disclosure, active_client, active_limiter)
                    except httpx.HTTPError as exc:
                        LOGGER.warning(
                            'download failed cik=%s accession=%s error=%s',
                            cik,
                            disclosure.accession,
                            exc,
                        )
                        continue
                    taken += 1
                    text = _document_text(path)
                    rows.append(
                        {
                            'document_id': f'{cik.zfill(10)}-{disclosure.accession}-{disclosure.document}',
                            'cik': cik.zfill(10),
                            'report_date': disclosure.filing_date.isoformat(),
                            'document_type': disclosure.exhibit_type,
                            'source': 'edgar',
                            # Relative to the data root so a copied data directory
                            # stays usable; loaders resolve it against DATA_DIR.
                            'raw_path': str(path.relative_to(data_root(config))),
                            'sha256': file_sha256(path),
                            'chars': len(text),
                            'downloaded_at': datetime.now(timezone.utc).isoformat(),
                        }
                    )
            except (httpx.HTTPError, DataError) as exc:
                LOGGER.warning('cik failed cik=%s error=%s', cik, exc)
                continue
    finally:
        if own_client:
            active_client.close()
    return rows
