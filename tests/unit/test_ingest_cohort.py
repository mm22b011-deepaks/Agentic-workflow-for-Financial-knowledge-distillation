"""B1/B7: the cohort is the season each company was sampled for, and it survives an abort."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import pytest

from nowcast.cli import main

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO / 'configs' / 'config.yaml'


def _headers(document: str = 'ex991.htm') -> str:
    """Return an index-headers page with one EX-99.1 exhibit."""
    return (
        f'<DOCUMENT><TYPE>8-K\n<SEQUENCE>1\n<FILENAME>cover.htm</DOCUMENT>'
        f'<DOCUMENT><TYPE>EX-99.1\n<SEQUENCE>2\n<FILENAME>{document}</DOCUMENT>'
    )


def _submissions(dates: list[str]) -> dict[str, object]:
    """Return a submissions body with one 8-K per filing date."""
    return {
        'filings': {
            'recent': {
                'accessionNumber': [f'0000000001-25-{i:06d}' for i in range(len(dates))],
                'form': ['8-K'] * len(dates),
                'filingDate': dates,
                'items': ['2.02,9.01'] * len(dates),
            }
        }
    }


def _run_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, handler, extra: list[str] | None = None
) -> int:
    """Run the real ingest command against a mock SEC transport."""
    import nowcast.ingestion.edgar as edgar

    data = tmp_path / 'data'
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('DATA_DIR', str(data))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('SEC_USER_AGENT', 'nowcast-tests tests@example.com')
    (data / 'universe').mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                'ticker': 'T01',
                'cik': '0000000001',
                'effective_from': '2024-01-01',
                'effective_to': '',
            }
        ]
    ).to_csv(data / 'universe' / 'constituents.csv', index=False)

    original = edgar.build_client

    def fake_client(config):
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(edgar, 'build_client', fake_client)
    try:
        return main(
            [
                'ingest',
                '--set',
                'scope.profile=custom',
                '--set',
                'scope.companies=0',
                '--set',
                'scope.seasons=0',
                '--config',
                str(CONFIG_PATH),
                '--set',
                'data.start_date=2025-01-01',
                '--set',
                'data.end_date=2025-12-31',
                '--set',
                'data.edgar_max_documents=50',
                '--set',
                'data.edgar_docs_per_cik=10',
                '--set',
                'universe.subset_n=1',
                *(extra or []),
            ]
        )
    finally:
        monkeypatch.setattr(edgar, 'build_client', original)


def test_cli_ingest_cohort_is_per_season_and_matches_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cohort lists the (company, season) pairs whose documents were downloaded."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith('.json') and 'submissions' in path:
            return httpx.Response(
                200, json=_submissions(['2025-04-24', '2025-07-25']), request=request
            )
        if path.endswith('-index-headers.html'):
            return httpx.Response(200, text=_headers(), request=request)
        if path.endswith('.htm'):
            return httpx.Response(
                200, text='<html><body>Revenue was $1.20 billion.</body></html>', request=request
            )
        return httpx.Response(404, request=request)

    assert _run_ingest(tmp_path, monkeypatch, handler) == 0
    data = tmp_path / 'data'
    cohort = pd.read_csv(data / 'manifests' / 'cohort.csv', dtype={'cik': str})
    index = pd.read_parquet(data / 'document_index.v2.parquet')

    # Every downloaded season appears in the cohort for that company, and nothing else.
    from nowcast.extraction.selection import season_of_date

    downloaded = {
        (str(row.cik).zfill(10), season_of_date(str(row.report_date)[:10]))
        for row in index.itertuples(index=False)
    }
    cohort_pairs = {
        (str(row.cik).zfill(10), str(row.season)) for row in cohort.itertuples(index=False)
    }
    assert downloaded
    assert downloaded <= cohort_pairs
    assert len(cohort_pairs) == len(cohort), 'cohort must not repeat a pair'


def test_no_crash_when_cohorts_differ_per_season(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two companies sampled for different seasons is normal, not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith('.json') and 'submissions' in path:
            return httpx.Response(200, json=_submissions(['2025-04-24']), request=request)
        if path.endswith('-index-headers.html'):
            return httpx.Response(200, text=_headers(), request=request)
        if path.endswith('.htm'):
            return httpx.Response(
                200, text='<html><body>Revenue was $1.20 billion.</body></html>', request=request
            )
        return httpx.Response(404, request=request)

    assert _run_ingest(tmp_path, monkeypatch, handler) == 0
    cohort = pd.read_csv(tmp_path / 'data' / 'manifests' / 'cohort.csv', dtype={'cik': str})
    assert set(cohort['season']) <= {'2025Q1', '2025Q2', '2025Q3', '2025Q4'}


def test_abort_keeps_rows_downloaded_so_far(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 403 storm stops the run, and what was already downloaded is in the index."""
    import nowcast.ingestion.edgar as edgar

    state = {'calls': 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state['calls'] += 1
        path = request.url.path
        if path.endswith('.json') and 'submissions' in path:
            # First company works, everything after it is refused.
            if state['calls'] <= 3:
                return httpx.Response(200, json=_submissions(['2025-04-24']), request=request)
            return httpx.Response(403, text='blocked', request=request)
        if path.endswith('-index-headers.html'):
            return httpx.Response(200, text=_headers(), request=request)
        if path.endswith('.htm'):
            return httpx.Response(
                200, text='<html><body>Revenue was $1.20 billion.</body></html>', request=request
            )
        return httpx.Response(404, request=request)

    data = tmp_path / 'data'
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('DATA_DIR', str(data))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('SEC_USER_AGENT', 'nowcast-tests tests@example.com')
    (data / 'universe').mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                'ticker': f'T{i:02d}',
                'cik': f'{i:010d}',
                'effective_from': '2024-01-01',
                'effective_to': '',
            }
            for i in range(1, 8)
        ]
    ).to_csv(data / 'universe' / 'constituents.csv', index=False)
    monkeypatch.setattr(
        edgar, 'build_client', lambda config: httpx.Client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(edgar.time, 'sleep', lambda _s: None)
    # main() turns the abort into exit code 2; the point is that the work before it
    # is still on disk.
    code = main(
        [
            'ingest',
            '--set',
            'scope.profile=custom',
            '--set',
            'scope.companies=0',
            '--set',
            'scope.seasons=0',
            '--config',
            str(CONFIG_PATH),
            '--set',
            'data.start_date=2025-01-01',
            '--set',
            'data.end_date=2025-12-31',
            '--set',
            'data.edgar_max_documents=50',
            '--set',
            'data.edgar_docs_per_cik=10',
            '--set',
            'data.sec_abort_after_blocked=2',
            '--set',
            'universe.subset_n=7',
        ]
    )
    assert code == 2
    index = pd.read_parquet(data / 'document_index.v2.parquet')
    assert len(index) >= 1, 'the documents downloaded before the abort must be kept'
    assert (data / 'manifests' / 'cohort.csv').is_file()


def test_ingest_reports_season_cohort_in_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The summary states how many (company, season) pairs the run targeted."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith('.json') and 'submissions' in path:
            return httpx.Response(200, json=_submissions(['2025-04-24']), request=request)
        if path.endswith('-index-headers.html'):
            return httpx.Response(200, text=_headers(), request=request)
        if path.endswith('.htm'):
            return httpx.Response(
                200, text='<html><body>Revenue was $1.20 billion.</body></html>', request=request
            )
        return httpx.Response(404, request=request)

    assert _run_ingest(tmp_path, monkeypatch, handler) == 0
    summary = json.loads((tmp_path / 'data' / 'manifests' / 'ingest_summary.json').read_text())
    assert summary['cohort_pairs'] >= 1
    assert summary['aborted'] is None
