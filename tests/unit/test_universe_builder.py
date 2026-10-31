"""End-to-end tests for the universe builder against a mocked network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

from nowcast.config import Config, load_config
from nowcast.errors import DataError
from nowcast.ingestion.universe.builder import build_constituents

FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures' / 'universe'
REPO = Path(__file__).resolve().parent.parent.parent
CURRENT_URL = 'https://example.test/wiki/current'
CHANGES_URL = 'https://example.test/wiki/changes'
SEC_MAP_URL = 'https://example.test/sec/company_tickers.json'


class CountingTransport:
    """An httpx transport that serves fixtures and counts requests."""

    def __init__(self) -> None:
        """Serve each known URL from its fixture file."""
        self.calls: list[str] = []
        self._routes = {
            CURRENT_URL: (FIXTURES / 'current_table.html').read_text(encoding='utf-8'),
            CHANGES_URL: (FIXTURES / 'changes_table.html').read_text(encoding='utf-8'),
            SEC_MAP_URL: (FIXTURES / 'sec_ticker_map.json').read_text(encoding='utf-8'),
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Return the fixture for the requested URL, recording the call."""
        url = str(request.url)
        self.calls.append(url)
        if url not in self._routes:
            return httpx.Response(404, text='not found')
        return httpx.Response(200, text=self._routes[url])

    def transport(self) -> httpx.MockTransport:
        """Return an httpx transport backed by the handler."""
        return httpx.MockTransport(self.handler)


def _config(**overrides: Any) -> Config:
    """Load the project config pointed at the fixture URLs and a small universe."""
    values: dict[str, Any] = {
        'universe.current_table_url': CURRENT_URL,
        'universe.changes_table_url': CHANGES_URL,
        'universe.sec_ticker_map_url': SEC_MAP_URL,
        'universe.cik_overrides_csv': str(FIXTURES / 'cik_overrides.csv'),
        'universe.expected_members': 3,
        'universe.member_count_tolerance': 4,
        'universe.as_of_sample_freq': 'YS',
        'universe.subset_n': 0,
        'data.start_date': '2022-01-01',
        'data.end_date': '2024-01-01',
        'universe.refresh': 'false',
    }
    values.update(overrides)
    return load_config(REPO / 'configs' / 'config.yaml', overrides=values)


@pytest.fixture
def uni_config(workdir: Path) -> Config:
    """Return the fixture-URL config bound to the temp data directory."""
    del workdir
    return _config()


@pytest.fixture
def built(uni_config: Config) -> Path:
    """Run one build against the mocked network and return the constituents path."""
    net = CountingTransport()
    return build_constituents(uni_config, transport=net.transport())


def test_builder_writes_constituents_and_artifacts(uni_config: Config) -> None:
    """A build writes constituents, report, audit, anomalies and unmapped files."""
    net = CountingTransport()
    path = build_constituents(uni_config, transport=net.transport())
    frame = pd.read_csv(path, dtype={'cik': str})
    assert list(frame.columns) == [
        'ticker',
        'cik',
        'effective_from',
        'effective_to',
        'company_name',
        'cik_source',
    ]
    assert (frame['cik'].str.len() == 10).all()
    assert set(frame['ticker']) == {'AAA', 'BBB', 'CCC', 'DDD', 'ZZZ'}
    out = path.parent
    assert (out / 'build_report.json').is_file()
    assert (out / 'member_count_audit.csv').is_file()
    assert (out / 'anomalies.csv').is_file()
    # Every fixture ticker resolves, so no unmapped file is left behind.
    assert not (out / 'unmapped.csv').exists()
    assert len(net.calls) == 3


def test_builder_idempotent_skips_when_hashes_match(uni_config: Config) -> None:
    """A second build with unchanged inputs skips every network call."""
    net = CountingTransport()
    first = build_constituents(uni_config, transport=net.transport())
    first_mtime = first.stat().st_mtime_ns
    assert len(net.calls) == 3

    second_net = CountingTransport()
    second = build_constituents(uni_config, transport=second_net.transport())
    assert second == first
    assert second.stat().st_mtime_ns == first_mtime
    assert second_net.calls == []


def test_builder_rebuilds_when_input_changes(uni_config: Config, workdir: Path) -> None:
    """A different source hash forces a rebuild even when the config is identical."""
    net = CountingTransport()
    first = build_constituents(uni_config, transport=net.transport())
    cache = workdir / 'raw' / 'universe'
    changed = next(cache.glob('*.html'))
    changed.write_text(changed.read_text(encoding='utf-8') + '\n<!-- edited -->', encoding='utf-8')
    before = json.loads((first.parent / 'build_report.json').read_text(encoding='utf-8'))
    again = CountingTransport()
    build_constituents(uni_config, transport=again.transport())
    after = json.loads((first.parent / 'build_report.json').read_text(encoding='utf-8'))
    # The edited input changes its recorded hash, so the build is no longer a no-op.
    assert after['input_hashes'] != before['input_hashes']


def test_build_report_contains_hashes_and_licence_note(uni_config: Config) -> None:
    """The report records input hashes, coverage and the configured licence note."""
    note = 'Wikipedia text is CC BY-SA; SEC filings are public domain.'
    configured = _config(**{'universe.licence_note': note})
    net = CountingTransport()
    path = build_constituents(configured, transport=net.transport())
    report = json.loads((path.parent / 'build_report.json').read_text(encoding='utf-8'))
    hashes = report['input_hashes']
    assert hashes['current_sha256'] == _sha256(FIXTURES / 'current_table.html')
    assert hashes['changes_sha256'] == _sha256(FIXTURES / 'changes_table.html')
    assert hashes['sec_map_sha256'] == _sha256(FIXTURES / 'sec_ticker_map.json')
    assert all(len(value) == 64 for value in hashes.values())
    assert report['licence_note'] == note
    assert report['cik_coverage'] == 1.0
    assert report['member_count_audit']['flagged_dates'] == 0
    assert report['config_hash']


def test_build_fails_when_coverage_below_threshold(uni_config: Config) -> None:
    """Unresolvable tickers fail the build and name the unmapped file."""
    strict = _config(
        **{
            'universe.min_cik_coverage': 1.0,
            # An empty SEC map leaves only the CCC override to resolve anything.
            'universe.sec_ticker_map_url': 'https://example.test/sec/empty.json',
        }
    )
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, text='{}')
            if 'empty.json' in str(request.url)
            else CountingTransport().handler(request)
        )
    )
    with pytest.raises(DataError) as excinfo:
        build_constituents(strict, transport=transport)
    message = str(excinfo.value)
    assert 'unmapped.csv' in message
    assert 'coverage' in message.lower()


def _sha256(path: Path) -> str:
    """Hash a fixture file."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
