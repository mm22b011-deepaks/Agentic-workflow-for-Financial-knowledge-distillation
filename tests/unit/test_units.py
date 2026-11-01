"""H5: units are canonicalised and growth is a percentage as printed."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from nowcast.config import Config, extractions_dir, resolve_data_path
from nowcast.extraction import runner
from nowcast.extraction.schema import ExtractionRecord
from nowcast.extraction.units import normalise_growth, normalise_record, normalise_units
from nowcast.llm.caller import LLMResult

MODEL = 'fake/model:free'


@pytest.mark.parametrize(
    ('raw', 'currency', 'expected'),
    [
        ('dollars', None, 'USD'),
        ('USD billions', None, 'USD billion'),
        ('GBP millions', None, 'GBP million'),
        ('millions of dollars', None, 'USD million'),
        ('£m', None, 'GBP million'),
        ('EUR millions', None, 'EUR million'),
        ('USD', None, 'USD'),
        # A scale with no currency takes the record's currency.
        ('millions', 'USD', 'USD million'),
        ('billion', 'gbp', 'GBP billion'),
        # Neither part is recognised: keep what the model said rather than drop it.
        ('per share', None, 'per share'),
        ('', None, None),
        (None, None, None),
    ],
)
def test_normalise_units(raw: str | None, currency: str | None, expected: str | None) -> None:
    """Free-text labels become `<CCY> [scale]`; unknown labels survive intact."""
    assert normalise_units(raw, currency) == expected


@pytest.mark.parametrize(
    ('value', 'quote', 'expected'),
    [
        # The convention: percent as printed.
        (4.0, 'up 4% year over year', 4.0),
        # The failure the normaliser exists for: the fraction for the same sentence.
        (0.04, 'up 4% year over year', 4.0),
        (0.08, 'up 8% from the prior year quarter', 8.0),
        (-0.04, 'down 4% year over year', -4.0),
        # A sub-1% figure is already the printed number and must not be scaled.
        (0.5, 'up 0.5% year over year', 0.5),
        (0.4, 'growth of 0.4%', 0.4),
        # Spelled-out numbers are not corrected; validation reports the mismatch.
        (0.08, 'grew eight percent', 0.08),
        # No percent marker in the quote: leave the value alone.
        (0.08, 'growth accelerated', 0.08),
        (0.08, None, 0.08),
    ],
)
def test_normalise_growth(value: float, quote: str | None, expected: float) -> None:
    """`4%` and `0.04` both become 4.0, but 0.5% stays 0.5."""
    assert normalise_growth(value, quote) == pytest.approx(expected)


def _record(**overrides: object) -> ExtractionRecord:
    """Build a minimal record with the fields these tests care about."""
    payload: dict[str, object] = {
        'schema_version': 'v1',
        'document_id': 'doc',
        'currency': 'USD',
        'units': 'dollars',
        'revenue': {'value': 1.2, 'evidence_quote': 'Revenue was $1.20 billion'},
        'revenue_yoy_growth': {
            'value': 0.08,
            'evidence_quote': 'up 8% from the prior year quarter',
        },
    }
    payload.update(overrides)
    return ExtractionRecord.model_validate(payload)


def test_normalise_record_fixes_units_and_growth() -> None:
    """One pass over a record yields a comparable label and a percent growth value."""
    record = normalise_record(_record())
    assert record.units == 'USD'
    assert record.revenue_yoy_growth.value == pytest.approx(8.0)
    # Nothing else is touched.
    assert record.revenue.value == pytest.approx(1.2)
    assert record.revenue_yoy_growth.evidence_quote == 'up 8% from the prior year quarter'


def test_normalise_record_leaves_a_correct_record_alone() -> None:
    """An already-canonical record comes back unchanged."""
    record = _record(
        units='USD million',
        revenue_yoy_growth={'value': 8.0, 'evidence_quote': 'up 8% year over year'},
    )
    assert normalise_record(record) == record


def test_prepare_text_records_how_much_was_sent(config: Config, tmp_path: Path) -> None:
    """The cut is measured, not guessed: total length and sent length are both kept."""
    path = tmp_path / 'doc.txt'
    path.write_text('x' * 500, encoding='utf-8')
    document = runner.Document(
        document_id='doc0',
        cik='0000000001',
        report_date='2026-01-15',
        document_type='EX-99.1',
        raw_path=path,
        sha256='h0',
    )
    short = dataclasses.replace(
        config, extraction=dataclasses.replace(config.extraction, max_doc_chars=100)
    )
    prepared = runner.prepare_text(short, document)
    assert prepared.chars_total >= 500
    # The packer keeps the head plus any windows; here there is no phrase to find, so
    # the head alone is sent and it never exceeds the configured limit.
    assert prepared.chars_sent <= 100
    assert prepared.chars_sent > 0
    assert prepared.truncated

    whole = dataclasses.replace(
        config, extraction=dataclasses.replace(config.extraction, max_doc_chars=100_000)
    )
    prepared = runner.prepare_text(whole, document)
    assert prepared.chars_sent == prepared.chars_total
    assert not prepared.truncated


SOURCE = (
    'Revenue was $1.20 billion, up 8% year over year. GAAP earnings per share were $0.55. '
) + 'Filler sentence for length. ' * 60

REPLY = json.dumps(
    {
        'schema_version': 'v1',
        'document_id': 'x',
        'fiscal_year': 2026,
        'fiscal_quarter': 1,
        'currency': 'USD',
        'units': 'dollars',
        'reported_eps': {
            'value': 0.55,
            'evidence_quote': 'earnings per share were $0.55',
            'confidence': 0.9,
        },
        'eps_basis': {
            'value': 'gaap',
            'evidence_quote': 'GAAP earnings per share',
            'confidence': 0.9,
        },
        'revenue': {
            'value': 1.2,
            'evidence_quote': 'Revenue was $1.20 billion',
            'confidence': 0.9,
        },
        'revenue_yoy_growth': {
            'value': 0.08,
            'evidence_quote': 'up 8% year over year',
            'confidence': 0.9,
        },
    }
)


class FakeCaller:
    """Return the canned reply and count calls."""

    def __init__(self) -> None:
        """Start with no calls made."""
        self.calls = 0

    def complete(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> LLMResult:
        """Return the canned reply."""
        self.calls += 1
        return LLMResult(text=REPLY, model=model)


def test_runner_stores_diagnostics_and_corrected_values(config: Config, tmp_path: Path) -> None:
    """The stored record and the consolidated frame both carry the corrected values."""
    import asyncio

    path = tmp_path / 'doc.txt'
    path.write_text(SOURCE, encoding='utf-8')
    document = runner.Document(
        document_id='doc0',
        cik='0000000001',
        report_date='2026-01-15',
        document_type='EX-99.1',
        raw_path=path,
        sha256='h0',
    )
    cut = dataclasses.replace(
        config, extraction=dataclasses.replace(config.extraction, max_doc_chars=120)
    )
    caller = FakeCaller()
    outcomes = asyncio.run(
        runner.run_extraction(
            cut,
            [document],
            caller_factory=lambda _model: caller,
            models=[MODEL],
            queue_path=resolve_data_path(cut, cut.extraction.review_queue_path),
        )
    )
    assert outcomes[0].status == 'ok'
    assert outcomes[0].truncated

    result = json.loads(
        (extractions_dir(cut) / runner.model_slug(MODEL) / 'doc0.json').read_text(encoding='utf-8')
    )
    assert result['diagnostics']['truncated'] is True
    # The head is a third of the limit, plus any windows that fit inside it.
    assert 0 < result['diagnostics']['chars_sent'] <= 120
    assert result['diagnostics']['chars_total'] > 120
    assert result['record']['units'] == 'USD'
    assert result['record']['revenue_yoy_growth']['value'] == pytest.approx(8.0)

    frame = runner.consolidate(cut, [MODEL])
    row = frame.iloc[0]
    assert row['revenue_yoy_growth_pct'] == pytest.approx(8.0)
    assert bool(row['truncated']) is True
    assert row['chars_sent'] < row['chars_total']


def test_no_pack_phrases_sends_the_document_whole(config: Config, tmp_path: Path) -> None:
    """With packing off, nothing is cut: the model sees the whole release."""
    import dataclasses as dc

    body = 'HEADLINE ' + ('filler ' * 2000) + 'Outlook: guidance unchanged. ' + ('tail ' * 2000)
    path = tmp_path / 'doc.txt'
    path.write_text(body, encoding='utf-8')
    document = runner.Document(
        document_id='doc0',
        cik='0000000001',
        report_date='2026-01-15',
        document_type='EX-99.1',
        raw_path=path,
        sha256='h0',
    )
    unpacked = dc.replace(
        config,
        extraction=dc.replace(config.extraction, max_doc_chars=24_000, pack_phrases=()),
    )
    prepared = runner.prepare_text(unpacked, document)
    assert prepared.chars_sent == prepared.chars_total
    assert not prepared.truncated
    assert 'HEADLINE' in prepared.text and 'Outlook: guidance unchanged.' in prepared.text


def test_pack_phrases_change_the_fingerprint(config: Config, tmp_path: Path) -> None:
    """Turning packing off must invalidate records written with it on."""
    import dataclasses as dc

    document = runner.Document(
        document_id='doc0',
        cik='0000000001',
        report_date='2026-01-15',
        document_type='EX-99.1',
        raw_path=tmp_path / 'doc.txt',
        sha256='h0',
    )
    packed = runner.fingerprint(config, document, 'model:free', 'digest')
    unpacked_config = dc.replace(config, extraction=dc.replace(config.extraction, pack_phrases=()))
    assert runner.fingerprint(unpacked_config, document, 'model:free', 'digest') != packed
