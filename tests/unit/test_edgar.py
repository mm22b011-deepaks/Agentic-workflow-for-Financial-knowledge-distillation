"""Unit tests for the EDGAR downloader, using a mocked transport."""

from __future__ import annotations

import dataclasses
import datetime
import json
from pathlib import Path

import httpx
import pytest

from nowcast.config import Config, data_root, load_config, raw_dir
from nowcast.errors import ConfigError, DataError
from nowcast.ingestion.edgar import (
    Disclosure,
    IngestReport,
    RateLimiter,
    build_client,
    download_document,
    ingest_edgar,
    user_agent,
)

SUBMISSIONS = {
    'filings': {
        'recent': {
            'accessionNumber': ['0000000001-26-000001'],
            'form': ['8-K'],
            'filingDate': ['2030-01-02'],
            'items': ['2.02,9.01'],
        }
    }
}
INDEX_JSON = {'directory': {'item': [{'name': 'ex991.htm'}, {'name': 'cover.htm'}]}}
HEADERS_HTML = (
    '<DOCUMENT><TYPE>8-K\n<SEQUENCE>1\n<FILENAME>aapl-20260102.htm</DOCUMENT>'
    '<DOCUMENT><TYPE>EX-99.1\n<SEQUENCE>2\n<FILENAME>dex991.htm</DOCUMENT>'
    '<DOCUMENT><TYPE>EX-101.SCH\n<SEQUENCE>3\n<FILENAME>x.xsd</DOCUMENT>'
)
EXHIBIT_HTML = '<html><body><p>Revenue was $5 million.</p></body></html>'
REPO = Path(__file__).resolve().parent.parent.parent


def _handler(request: httpx.Request) -> httpx.Response:
    """Serve canned EDGAR responses for submissions, index and archive URLs."""
    path = request.url.path
    if path.endswith('.json') and 'submissions' in path:
        return httpx.Response(200, json=SUBMISSIONS)
    if path.endswith('-index-headers.html'):
        return httpx.Response(200, text=HEADERS_HTML)
    if path.endswith('index.json'):
        return httpx.Response(200, json=INDEX_JSON)
    if path.endswith('ex991.htm'):
        return httpx.Response(200, text=EXHIBIT_HTML)
    return httpx.Response(404)


def _client() -> httpx.Client:
    """Build an httpx client bound to the canned transport."""
    return httpx.Client(transport=httpx.MockTransport(_handler))


def test_edgar_requires_user_agent(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing User-Agent environment variable raises ConfigError."""
    monkeypatch.delenv(config.data.sec_user_agent_env, raising=False)
    with pytest.raises(ConfigError) as excinfo:
        user_agent(config)
    assert config.data.sec_user_agent_env in str(excinfo.value)
    with pytest.raises(ConfigError):
        build_client(config)


def test_edgar_skips_existing_download(config: Config, tmp_path: Path) -> None:
    """A document already on disk is not fetched again."""
    calls = {'count': 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls['count'] += 1
        return httpx.Response(200, text=EXHIBIT_HTML)

    disclosure = Disclosure(
        cik='1',
        accession='0000000001-26-000001',
        filing_date=datetime.date(2026, 1, 2),
        form='8-K',
        exhibit_type='EX-99',
        document='dex991.htm',
    )
    target_dir = raw_dir(config) / '0000000001' / disclosure.accession
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / 'dex991.htm').write_text(EXHIBIT_HTML, encoding='utf-8')
    client = httpx.Client(transport=httpx.MockTransport(handler))
    download_document(config, disclosure, client, RateLimiter(1000.0))
    assert calls['count'] == 0


def test_edgar_rate_limit_enforced() -> None:
    """The limiter sleeps so calls are never closer than the configured interval."""
    now = {'t': 0.0}
    sleeps: list[float] = []

    def clock() -> float:
        return now['t']

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now['t'] += seconds

    limiter = RateLimiter(2.0, clock=clock)
    limiter._sleep = fake_sleep  # type: ignore[attr-defined]
    limiter.wait()
    now['t'] += 0.1
    limiter.wait()
    assert sleeps and sleeps[0] == pytest.approx(0.4)


def test_edgar_ingest_builds_index_rows(config: Config) -> None:
    """Ingesting one CIK yields one row for the EX-99 exhibit."""
    rows = ingest_edgar(
        config,
        ['1'],
        client=_client(),
        limiter=RateLimiter(1000.0),
        max_documents=5,
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row['cik'] == '0000000001'
    assert row['document_type'] == 'EX-99.1'
    assert row['source'] == 'edgar'
    stored = data_root(config) / str(row['raw_path'])
    assert stored.is_file()
    assert 'Revenue was $5 million.' in stored.read_text(encoding='utf-8')


def test_edgar_ingest_unknown_cik_returns_empty(config: Config) -> None:
    """A 404 submissions response yields no rows instead of raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = ingest_edgar(
        config,
        ['9'],
        client=client,
        limiter=RateLimiter(1000.0),
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
    )
    assert rows == []


def test_edgar_index_json_shape_error_is_skipped(config: Config) -> None:
    """A filing whose index.json does not parse is skipped, not fatal."""

    def handler(request: httpx.Request) -> httpx.Response:
        if 'submissions' in request.url.path:
            return httpx.Response(200, json=SUBMISSIONS)
        return httpx.Response(200, text='not json')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = ingest_edgar(
        config,
        ['1'],
        client=client,
        limiter=RateLimiter(1000.0),
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
    )
    assert rows == []


def test_submissions_payload_shape() -> None:
    """The canned payload matches the EDGAR recent-filings shape."""
    recent = json.loads(json.dumps(SUBMISSIONS))['filings']['recent']
    assert len(recent['accessionNumber']) == len(recent['form']) == len(recent['filingDate'])
    assert len(recent['items']) == len(recent['form'])


def test_parse_exhibits_picks_ex99_by_type() -> None:
    """Exhibit selection uses the TYPE field, so dex991.htm style names are found."""
    from nowcast.ingestion.edgar import parse_exhibits

    assert parse_exhibits(HEADERS_HTML) == [('EX-99.1', 'dex991.htm')]


def test_items_filter_skips_non_earnings_8k(config: Config) -> None:
    """An 8-K without item 2.02 is ignored."""
    payload = {
        'filings': {
            'recent': {
                'accessionNumber': ['0000000001-26-000002'],
                'form': ['8-K'],
                'filingDate': ['2030-03-04'],
                'items': ['5.02'],
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if 'submissions' in request.url.path:
            return httpx.Response(200, json=payload)
        return httpx.Response(200, text=HEADERS_HTML)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = ingest_edgar(
        config,
        ['1'],
        client=client,
        limiter=RateLimiter(1000.0),
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
    )
    assert rows == []


def test_ingest_uses_configured_window_not_today(config: Config) -> None:
    """The filing window comes from config, so a run is reproducible on any date.

    The fixture filing is dated 2030: it is inside a 2029-2031 window and must be
    rejected by a 2020 window, regardless of what today's date happens to be.
    """
    inside = ingest_edgar(
        config,
        ['1'],
        client=_client(),
        limiter=RateLimiter(1000.0),
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
    )
    assert len(inside) == 1

    outside = ingest_edgar(
        config,
        ['1'],
        client=_client(),
        limiter=RateLimiter(1000.0),
        start_date=datetime.date(2020, 1, 1),
        end_date=datetime.date(2020, 12, 31),
    )
    assert outside == []


def test_ingest_without_any_window_raises(config: Config) -> None:
    """With no window supplied or configured, ingest fails instead of guessing today."""
    from nowcast.errors import DataError
    from nowcast.ingestion.edgar import fetch_disclosures

    blank = load_config(
        REPO / 'configs' / 'config.yaml',
        overrides={'data.start_date': '', 'data.end_date': ''},
    )
    with pytest.raises(DataError) as excinfo:
        fetch_disclosures(blank, '1', _client(), RateLimiter(1000.0))
    assert 'reproducible' in str(excinfo.value)


def test_raw_path_is_stored_relative_to_data_dir(config: Config) -> None:
    """Indexed raw paths stay portable: relative to DATA_DIR, not absolute."""
    rows = ingest_edgar(
        config,
        ['1'],
        client=_client(),
        limiter=RateLimiter(1000.0),
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
    )
    stored = str(rows[0]['raw_path'])
    assert not Path(stored).is_absolute()
    assert stored.startswith('raw/')
    assert (data_root(config) / stored).is_file()


IMAGE_HEADERS_HTML = (
    '<DOCUMENT><TYPE>EX-99.1\n<SEQUENCE>2\n<FILENAME>dex991.htm</DOCUMENT>'
    '<DOCUMENT><TYPE>EX-99.1\n<SEQUENCE>3\n<FILENAME>ibm_ex991001.jpg</DOCUMENT>'
)


def test_non_text_exhibits_are_never_downloaded(config: Config) -> None:
    """An EX-99 image is skipped: decoding a scan as HTML burns a document slot."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith('.json') and 'submissions' in path:
            return httpx.Response(200, json=SUBMISSIONS)
        if path.endswith('-index-headers.html'):
            return httpx.Response(200, text=IMAGE_HEADERS_HTML)
        if path.endswith('dex991.htm'):
            return httpx.Response(200, text=EXHIBIT_HTML)
        if path.endswith('.jpg'):
            raise AssertionError('an image exhibit was downloaded')
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = ingest_edgar(
        config,
        ['0000000001'],
        client=client,
        limiter=RateLimiter(1000.0),
        max_documents=10,
        per_cik_limit=10,
        # The canned submissions feed files on 2030-01-02, so widen the window to it.
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
    )
    assert [row['document_type'] for row in rows] == ['EX-99.1']
    assert rows[0]['document_id'].endswith('dex991.htm')
    assert rows[0]['chars'] > 0


def test_text_suffix_check_is_case_insensitive() -> None:
    """Suffix matching ignores case and requires membership in the configured list."""
    from nowcast.ingestion.edgar import is_text_document

    allowed = ('.htm', '.txt')
    assert is_text_document('EX-99.HTM', allowed)
    assert is_text_document('body.txt', allowed)
    assert not is_text_document('chart.jpg', allowed)
    assert not is_text_document('archive.htm.zip', allowed)
    # An empty allow-list means "parse nothing", never "parse everything".
    assert not is_text_document('anything.htm', ())


def test_headers_url_carries_the_accession_directory(config: Config) -> None:
    """The index-headers URL includes the accession directory EDGAR requires.

    Live check on 2026-10-31: without that segment the CDN answers 403, not 404, which
    makes the defect look like a permissions problem instead of a wrong URL.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if 'submissions' in request.url.path:
            return httpx.Response(200, json=SUBMISSIONS)
        seen.append(request.url.path)
        if request.url.path.endswith('-index-headers.html'):
            return httpx.Response(200, text=HEADERS_HTML)
        return httpx.Response(200, text=EXHIBIT_HTML)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ingest_edgar(
        config,
        ['1'],
        client=client,
        limiter=RateLimiter(1000.0),
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
    )
    headers_paths = [path for path in seen if path.endswith('-index-headers.html')]
    assert headers_paths, 'no index-headers request was made'
    for path in headers_paths:
        # /Archives/edgar/data/<cik>/<accession-nodash>/<accession>-index-headers.html
        assert path.split('/')[-2] == '000000000126000001', path


def test_ingest_report_counts_by_status(config: Config) -> None:
    """Every request's status and every skip lands in the report, not only in a log line."""
    report = IngestReport()
    rows = ingest_edgar(
        config,
        ['1'],
        client=_client(),
        limiter=RateLimiter(1000.0),
        max_documents=5,
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
        report=report,
    )
    assert len(rows) == 1
    assert report.companies == 1
    assert report.documents == 1
    # submissions + index-headers + the exhibit itself
    assert report.attempts == 3
    assert report.status_counts == {'200': 3}
    assert report.as_dict()['documents'] == 1
    assert 'aborted' not in report.as_dict() or report.aborted is None


def test_report_records_zero_disclosure_company(config: Config) -> None:
    """A company whose 8-Ks are all non-earnings is named, not silently absent."""
    payload = {
        'filings': {
            'recent': {
                'accessionNumber': ['0000000001-26-000002'],
                'form': ['8-K'],
                'filingDate': ['2030-03-04'],
                'items': ['5.02'],
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = IngestReport()
    rows = ingest_edgar(
        config,
        ['1'],
        client=client,
        limiter=RateLimiter(1000.0),
        start_date=datetime.date(2029, 1, 1),
        end_date=datetime.date(2031, 1, 1),
        report=report,
    )
    assert rows == []
    assert report.zero_disclosure_ciks == ['0000000001']
    assert report.status_counts == {'200': 1}


def test_consecutive_403_aborts(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run of blocked answers stops the ingest instead of asking every company."""
    # Config sections are frozen dataclasses, so the limit is rebuilt rather than set.
    config = dataclasses.replace(
        config,
        data=dataclasses.replace(config.data, sec_abort_after_blocked=3),
    )
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(403, text='forbidden')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = IngestReport()
    with pytest.raises(DataError, match='consecutive blocked'):
        ingest_edgar(
            config,
            [str(index) for index in range(1, 8)],
            client=client,
            limiter=RateLimiter(1000.0),
            start_date=datetime.date(2029, 1, 1),
            end_date=datetime.date(2031, 1, 1),
            report=report,
        )
    assert len(requested) == 3, requested
    assert report.aborted is not None
    assert report.status_counts == {'403': 3}


def test_partial_download_not_treated_as_complete(config: Config) -> None:
    """A body shorter than its Content-Length never becomes the stored document."""
    from nowcast.ingestion.edgar import download_document

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'short', headers={'content-length': '9999'})

    disclosure = Disclosure(
        cik='1',
        accession='0000000001-26-000001',
        filing_date=datetime.date(2026, 1, 2),
        form='8-K',
        exhibit_type='EX-99',
        document='dex991.htm',
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPError, match='truncated download'):
        download_document(config, disclosure, client, RateLimiter(1000.0))
    target = raw_dir(config) / '0000000001' / disclosure.accession / 'dex991.htm'
    assert not target.exists()
    assert not target.with_name('dex991.htm.part').exists()


def test_sgml_wrapper_stripped() -> None:
    """The EDGAR SGML envelope never reaches the document text."""
    from nowcast.parsing.html import html_to_text, strip_sgml_wrapper

    raw = (
        '<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>3\n<FILENAME>d123dex991.htm\n'
        '<DESCRIPTION>EX-99.1\n<TEXT>\n<HTML><BODY><P>Revenue was $5 million.</P>'
        '</BODY></HTML>\n</TEXT>\n</DOCUMENT>'
    )
    text = html_to_text(raw)
    assert 'Revenue was $5 million.' in text
    for metadata in ('EX-99.1', 'd123dex991.htm', 'SEQUENCE', 'DESCRIPTION'):
        assert metadata not in text, metadata
    assert strip_sgml_wrapper('plain text') == 'plain text'
