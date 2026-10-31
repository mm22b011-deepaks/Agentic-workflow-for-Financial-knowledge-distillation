"""SEC EDGAR submissions downloader with rate limiting and resume."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from nowcast.config import Config, data_root, raw_dir
from nowcast.errors import ConfigError, DataError
from nowcast.ingestion.doc_index import file_sha256
from nowcast.parsing.html import html_to_text, strip_sgml_wrapper

LOGGER = logging.getLogger(__name__)
EXHIBIT_FORMS_PREFIX = 'EX-'
EARNINGS_EXHIBIT_TYPE = 'EX-99'
EXHIBIT_99_RE = re.compile(r'ex[-_]?99')


@dataclass
class IngestReport:
    """What an ingest run actually did, including everything it silently skipped.

    Without this, a run that 403s on every request and a run that legitimately found
    nothing produce the same empty list, and the difference is only in a log file.
    """

    companies: int = 0
    documents: int = 0
    attempts: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    skip_reasons: dict[str, int] = field(default_factory=dict)
    zero_disclosure_ciks: list[str] = field(default_factory=list)
    aborted: str | None = None
    # Not serialised: the run fails on it rather than reporting it afterwards.
    consecutive_blocked: int = field(default=0, repr=False)

    def record_status(self, status: int) -> None:
        """Count one HTTP status code and track a run of 403/429 answers."""
        key = str(int(status))
        self.status_counts[key] = self.status_counts.get(key, 0) + 1
        if int(status) in BLOCKING_STATUSES:
            self.consecutive_blocked += 1
        elif 200 <= int(status) < 400:
            # Only a success proves the client is welcome again; a 404 does not.
            self.consecutive_blocked = 0

    def record_skip(self, reason: str) -> None:
        """Count one skipped company, filing, exhibit or download by reason."""
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def as_dict(self) -> dict[str, object]:
        """Return the report as JSON-serialisable data."""
        return {
            'companies': self.companies,
            'documents': self.documents,
            'attempts': self.attempts,
            'status_counts': dict(sorted(self.status_counts.items())),
            'skip_reasons': dict(sorted(self.skip_reasons.items())),
            'zero_disclosure_ciks': list(self.zero_disclosure_ciks),
            'aborted': self.aborted,
        }


# The statuses that mean "this client is not welcome right now". A handful in a row is
# a real stop: continuing produces one warning per company and an empty index that
# looks like an honest zero.
BLOCKING_STATUSES = (403, 429)


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
    items: str = ''


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
        cik=str(int(cik)),
        accession=accession,
        accession_nodash=accession.replace('-', ''),
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
    report: IngestReport | None = None,
) -> list[Disclosure]:
    """Fetch earnings 8-K filings for one CIK and locate their EX-99 exhibits."""
    limiter.wait()
    response = client.get(_submissions_url(config, cik))
    if report is not None:
        report.attempts += 1
        report.record_status(response.status_code)
    if response.status_code == 404:
        LOGGER.warning('CIK %s not found on EDGAR', cik)
        if report is not None:
            report.record_skip('submissions_404')
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
            if report is not None:
                report.attempts += 1
                report.record_status(headers_response.status_code)
            headers_response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.warning('index headers failed cik=%s accession=%s error=%s', cik, accession, exc)
            if report is not None:
                report.record_skip(f'index_headers_failed:{_status_of(exc)}')
            continue
        allowed = config.data.edgar_document_suffixes
        for document_type, filename in parse_exhibits(headers_response.text):
            if not is_text_document(filename, allowed):
                # An EX-99 image ("..._ex99-1img001.jpg") is a scanned release; decoding
                # it as HTML yields binary noise and burns a document slot.
                LOGGER.info('skip non-text exhibit cik=%s file=%s', cik, filename)
                if report is not None:
                    report.record_skip('non_text_exhibit')
                continue
            found.append(
                Disclosure(
                    cik=cik,
                    accession=accession,
                    filing_date=filing_date,
                    form=form,
                    exhibit_type=document_type,
                    document=filename,
                    items=item_text,
                )
            )
    return found


def _status_of(exc: httpx.HTTPError) -> str:
    """Return the HTTP status behind an httpx error, or 'x' when there is none."""
    response = getattr(exc, 'response', None)
    return str(getattr(response, 'status_code', 'x')) if response is not None else 'x'


def _document_text(path: Path) -> str:
    """Return a downloaded file's text, treating it as HTML only when it looks like HTML."""
    suffix = path.suffix.lower()
    raw = path.read_text(encoding='utf-8', errors='replace')
    if suffix in {'.htm', '.html'}:
        return html_to_text(raw)
    return strip_sgml_wrapper(raw)


def download_document(
    config: Config,
    disclosure: Disclosure,
    client: httpx.Client,
    limiter: RateLimiter,
    report: IngestReport | None = None,
) -> Path:
    """Download one document, skipping the request when the file already exists.

    The bytes land in a temporary file that is renamed only once complete: a connection
    dropped mid-body must not leave a truncated file that the next run then "resumes"
    from because it is non-empty.
    """
    target_dir = raw_dir(config) / disclosure.cik.zfill(10) / disclosure.accession
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / disclosure.document
    if target.is_file() and target.stat().st_size > 0:
        LOGGER.info('skip existing cik=%s accession=%s', disclosure.cik, disclosure.accession)
        if report is not None:
            report.record_skip('already_downloaded')
        return target
    url = _archive_url(config, disclosure.cik, disclosure.accession, disclosure.document)
    limiter.wait()
    response = client.get(url)
    if report is not None:
        report.attempts += 1
        report.record_status(response.status_code)
    response.raise_for_status()
    expected = int(response.headers.get('content-length') or 0)
    if expected and len(response.content) != expected:
        raise httpx.HTTPError(
            f'truncated download: {len(response.content)} of {expected} bytes from {url}'
        )
    temporary = target.with_name(target.name + '.part')
    temporary.write_bytes(response.content)
    temporary.replace(target)
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
    report: IngestReport | None = None,
) -> list[dict[str, object]]:
    """Download earnings exhibits for the given CIKs and return document index rows.

    When a `report` is passed, every status, skip and zero-disclosure company is counted
    on it. Consecutive 403/429 answers abort the run: once EDGAR has decided this client
    is not welcome, asking the other 480 companies only multiplies the same refusal.
    """
    own_client = client is None
    active_client = client or build_client(config)
    active_limiter = limiter or RateLimiter(config.data.sec_max_requests_per_sec)
    limit = max_documents if max_documents is not None else int(config.data.edgar_max_documents)
    per_cik = per_cik_limit if per_cik_limit is not None else int(config.data.edgar_docs_per_cik)
    window_start = start_date or _configured_date(config, config.data.start_date)
    window_end = end_date or _configured_date(config, config.data.end_date)
    abort_after = int(config.data.sec_abort_after_blocked)
    # The run always counts; the caller only decides whether it gets to keep the counts.
    active_report = report if report is not None else IngestReport()
    rows: list[dict[str, object]] = []
    try:
        for cik in ciks:
            if len(rows) >= limit:
                break
            active_report.companies += 1
            taken = 0
            try:
                disclosures = fetch_disclosures(
                    config,
                    cik,
                    active_client,
                    active_limiter,
                    window_start,
                    window_end,
                    active_report,
                )
                disclosures.sort(key=lambda item: item.filing_date, reverse=True)
                if not disclosures:
                    active_report.zero_disclosure_ciks.append(cik.zfill(10))
                for disclosure in disclosures:
                    if len(rows) >= limit or (per_cik and taken >= per_cik):
                        break
                    try:
                        path = download_document(
                            config, disclosure, active_client, active_limiter, active_report
                        )
                    except httpx.HTTPError as exc:
                        LOGGER.warning(
                            'download failed cik=%s accession=%s error=%s',
                            cik,
                            disclosure.accession,
                            exc,
                        )
                        active_report.record_skip(f'download_failed:{_status_of(exc)}')
                        continue
                    taken += 1
                    active_report.documents += 1
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
                            # The earnings-item proof travels with the row so extraction
                            # can refuse anything that was not a 2.02 filing.
                            'items': disclosure.items,
                        }
                    )
            except (httpx.HTTPError, DataError) as exc:
                LOGGER.warning('cik failed cik=%s error=%s', cik, exc)
            # Checked outside the per-CIK handler: a 403 on the submissions request
            # raises out of fetch_disclosures, and the abort must still see it.
            if active_report.consecutive_blocked >= abort_after:
                active_report.aborted = (
                    f'{active_report.consecutive_blocked} consecutive blocked responses '
                    f'({"/".join(str(code) for code in BLOCKING_STATUSES)}) after '
                    f'{active_report.attempts} requests; stopping before the remaining companies'
                )
                LOGGER.error('ingest aborted: %s', active_report.aborted)
                raise DataError(active_report.aborted)
    finally:
        if own_client:
            active_client.close()
    return rows
