from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import Config, load_config
from nowcast.extraction.review_queue import replace_rows, rows_for_record
from nowcast.extraction.schema import ExtractionRecord, NumField
from nowcast.extraction.validators import Issue, needs_review, number_in_quote
from nowcast.paths import Paths


def test_summary_review_reasons_do_not_withdraw_record(config: Config) -> None:
    from nowcast.aggregation.aggregate import _review_excluded

    record = ExtractionRecord(schema_version='v1', document_id='d', revenue=NumField(value=2))
    issues = [Issue('revenue', 'number_not_in_source', '')]
    rows = rows_for_record(
        'd', 'm:free', needs_review(record, issues, config), [('revenue', 'number_not_in_source')]
    )
    replace_rows(
        Paths.from_config(config).resolve(config.extraction.review_queue_path), 'd', 'm:free', rows
    )
    flags = _review_excluded(config, pd.DataFrame())
    assert flags[('d', 'm:free')] == {'reported_eps', 'revenue'}


@pytest.mark.parametrize(
    ('value', 'quote', 'expected'),
    [
        (2e6, 'Revenue $1 billion; expenses $2 million', True),
        (2e9, 'Revenue $1 billion; expenses $2 million', False),
        (-1.2, 'EPS $(1.20)', True),
        (1.2, 'EPS $(1.20)', False),
        (-1.2, 'EPS \u22121.20', True),
        (4, 'Revenue was $4 million', True),
        (0.04, 'Growth 4%', False),
        (4, 'Growth 4%', True),
    ],
)
def test_number_has_its_own_scale_and_sign(value: float, quote: str, expected: bool) -> None:
    assert number_in_quote(value, quote) is expected


def test_relocated_configuration_uses_its_actual_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    p = tmp_path / 'nested' / 'settings.yaml'
    p.parent.mkdir()
    p.write_text(
        (root / 'configs/config.yaml')
        .read_text()
        .replace("project_dir: '..'", "project_dir: '../checkout'")
    )
    monkeypatch.delenv('DATA_DIR', raising=False)
    config = load_config(p)
    assert Paths.from_config(config).root == tmp_path / 'checkout' / 'data'


def test_consolidation_does_not_move_stale_files(config: Config) -> None:
    import json

    from nowcast.extraction.runner import consolidate, model_slug

    folder = Paths.from_config(config).extractions(config) / model_slug('m:free')
    folder.mkdir(parents=True)
    path = folder / 'd.json'
    path.write_text(
        json.dumps(
            {
                'document_id': 'd',
                'sha256': 'abc',
                'prompt_digest': 'old',
                'fingerprint': 'old',
                'record': {},
            }
        )
    )
    before = {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    assert consolidate(config, ['m:free']).empty
    assert {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()} == before


def test_evidence_does_not_borrow_number_from_other_period(config: Config) -> None:
    from nowcast.extraction.validators import validate_record
    from nowcast.parsing.html import html_to_text

    source = html_to_text(
        '<table><tr><th></th><th>2025</th><th>2024</th></tr><tr><td>Revenue</td><td>$9,825</td><td>$11,510</td></tr></table>'
    )
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        revenue=NumField(value=11510, evidence_quote='Revenue $11,510', confidence=1),
    )
    issues, _ = validate_record(record, source, config)
    assert 'number_not_in_source' in {i.code for i in issues}


def test_table_preserves_cells_and_evidence_offsets(config: Config) -> None:
    from nowcast.extraction.validators import evidence_span, validate_record
    from nowcast.parsing.html import html_to_text

    source = html_to_text(
        '<table><tr><th></th><th>2025</th><th>2024</th></tr><tr><td>Total revenues</td><td>$49,725</td><td>$40,000</td></tr></table>'
    )
    quote = 'Total revenues $49,725'
    span = evidence_span(quote, source, year=2025)
    assert span is not None
    assert source[span.start : span.end] == span.text
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        revenue=NumField(value=49725, evidence_quote=quote, confidence=1),
    )
    issues, _ = validate_record(record, source, config)
    assert not issues


def test_index_receipts_survive_interruption(tmp_path: Path) -> None:
    from nowcast.ingestion.doc_index import INDEX_COLUMNS, IndexCheckpoint, load_index

    path = tmp_path / 'index.parquet'
    checkpoint = IndexCheckpoint(path)
    row = dict.fromkeys(INDEX_COLUMNS, '')
    row.update(document_id='one', report_date='2025-01-01')
    checkpoint.add(row)
    assert not path.exists()
    recovered = IndexCheckpoint(path)
    assert load_index(path)['document_id'].tolist() == ['one']
    assert not recovered.receipts.exists()


def test_pagination_fetches_older_pages(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from nowcast.ingestion.edgar import IngestReport, RateLimiter, fetch_disclosures

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if 'older.json' in str(request.url):
            return httpx.Response(200, json={'accessionNumber': [], 'filingDate': ['2024-12-01']})
        return httpx.Response(
            200,
            json={
                'filings': {
                    'recent': {'filingDate': ['2026-09-01']},
                    'files': [
                        {'name': 'older.json', 'filingFrom': '2024-01-01', 'filingTo': '2026-08-31'}
                    ],
                }
            },
        )

    report = IngestReport()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_disclosures(config, '1', client, RateLimiter(100000), report=report)
    assert any('older.json' in url for url in seen)
    assert report.attempts == 2


def test_table_unit_context_is_bound_to_evidence(config: Config) -> None:
    from nowcast.extraction.validators import validate_record
    from nowcast.parsing.html import html_to_text

    source = html_to_text(
        '<table><caption>In millions</caption><tr><th></th><th>2025</th></tr><tr><td>Revenue</td><td>120</td></tr></table>'
    )
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        revenue=NumField(value=120e6, evidence_quote='Revenue 120', confidence=1),
    )
    assert not validate_record(record, source, config)[0]


def test_period_and_theme_vocabulary_are_checked(config: Config) -> None:
    from nowcast.extraction.schema import ThemeMention
    from nowcast.extraction.validators import validate_record

    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2020,
        fiscal_quarter=5,
        theme_mentions={'demand': ThemeMention(mentioned=True, direction='invented')},
    )
    issues, _ = validate_record(record, 'source', config, report_date='2025-04-15')
    assert {'period_not_near_filing', 'vocab_invalid'} <= {i.code for i in issues}


def test_reply_budget_covers_measured_successful_completions(config: Config) -> None:
    # Maximum observed completion in the original 60 successful requests.
    measured_maximum = 30_973
    assert measured_maximum <= config.llm.max_tokens <= config.llm.max_tokens_ceiling


def test_schema_invalid_reply_is_not_cacheable() -> None:
    from nowcast.llm.composition import cacheable_reply

    assert not cacheable_reply('{"unrelated":123}')
    assert not cacheable_reply(
        '{"schema_version":"v1","document_id":"d","revenue":{"value":1e999}}'
    )
    assert not cacheable_reply(
        '{"schema_version":"v1","document_id":"d","reported_eps":{"confidence":2}}'
    )


def test_dedupe_not_decided_by_self_confidence(config: Config) -> None:
    from nowcast.aggregation.aggregate import aggregate_index

    paths = Paths.from_config(config)
    membership = paths.resolve(config.data.constituents_csv)
    membership.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [{'ticker': 'SYN', 'cik': '0000000001', 'effective_from': '2024-01-01', 'effective_to': ''}]
    ).to_csv(membership, index=False)
    rows = []
    for model, eps, confidence in [('preferred:free', 1.0, 0.1), ('other:free', 100.0, 1.0)]:
        rows.append(
            {
                'document_id': 'd',
                'cik': '0000000001',
                'report_date': '2025-04-15',
                'model': model,
                'reported_eps': eps,
                'prior_year_eps': 1.0,
                'consensus_eps': None,
                'eps_basis': 'gaap',
                'guidance_direction': 'maintained',
                'tone': 'neutral',
                'record_confidence': confidence,
            }
        )
    import dataclasses

    variant = dataclasses.replace(
        config,
        aggregation=dataclasses.replace(
            config.aggregation,
            dedupe_rule='model_priority',
            model_priority=('preferred:free', 'other:free'),
            min_constituents=1,
            min_observations=1,
        ),
    )
    result = aggregate_index(variant, pd.DataFrame(rows))
    assert result.eps_growth_agg.iloc[0] == 0


def test_same_year_other_quarter_cannot_supply_number(config: Config) -> None:
    from nowcast.extraction.validators import validate_record
    from nowcast.parsing.html import html_to_text

    source = html_to_text(
        '<table><tr><th></th><th>Q1 2025</th><th>Q2 2025</th></tr><tr><td>Revenue</td><td>100</td><td>200</td></tr></table>'
    )
    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        fiscal_year=2025,
        fiscal_quarter=1,
        revenue=NumField(value=200, evidence_quote='Revenue 200', confidence=1),
    )
    assert 'number_not_in_source' in {i.code for i in validate_record(record, source, config)[0]}


def test_http_failures_capabilities_and_cache_outcomes_are_measured(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from nowcast.llm.caller import LLMCaller
    from nowcast.llm.ledger import BudgetLedger

    ledger = BudgetLedger(tmp_path / 'attempts.parquet', 1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'GET':
            return httpx.Response(200, json={'data': []})
        return httpx.Response(429, json={'error': {'message': 'busy'}})

    with LLMCaller(config.llm, ledger=ledger, transport=httpx.MockTransport(handler)) as caller:
        from nowcast.errors import RateLimited

        with pytest.raises(RateLimited):
            caller.complete('fake:free', [{'role': 'user', 'content': 'hello'}])
        caller.note_cache_hit('fake:free', 0.001)
    frame = pd.read_parquet(tmp_path / 'attempts.parquet')
    assert frame.request_kind.tolist() == ['capabilities', 'completion', 'cache']
    assert frame.status_code.iloc[:2].tolist() == [200, 429]
    assert frame.latency_seconds.notna().all()


def test_percentage_cannot_be_used_as_currency_evidence(config: Config) -> None:
    from nowcast.extraction.validators import validate_record

    record = ExtractionRecord(
        schema_version='v1',
        document_id='d',
        revenue=NumField(value=4, evidence_quote='Revenue growth 4%', confidence=1),
    )
    issues, _ = validate_record(record, 'Revenue growth 4%', config)
    assert 'number_not_in_quote' in {i.code for i in issues}
