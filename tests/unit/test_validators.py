"""Unit tests for evidence validators."""

from __future__ import annotations

from nowcast.config import Config
from nowcast.extraction.schema import ExtractionRecord
from nowcast.extraction.validators import (
    needs_review,
    number_in_quote,
    validate_record,
    verify_quote,
)

SOURCE = (
    'Third quarter revenue was $1.20 billion, up 4% year over year. '
    'GAAP diluted earnings per share were $0.55. '
    'Adjusted diluted earnings per share were $0.61.'
)


def _record(**overrides: object) -> ExtractionRecord:
    """Build a minimal B4 record with sensible defaults."""
    payload = {
        'schema_version': 'v1',
        'document_id': 'doc-1',
        'fiscal_year': 2026,
        'fiscal_quarter': 3,
        'currency': 'USD',
        'units': 'USD',
        'reported_eps': {
            'value': 0.55,
            'evidence_quote': 'GAAP diluted earnings per share were $0.55',
            'confidence': 0.9,
        },
        'eps_basis': {
            'value': 'gaap',
            'evidence_quote': 'GAAP diluted earnings per share',
            'confidence': 0.9,
        },
        'revenue': {
            'value': 1.2,
            'evidence_quote': 'Third quarter revenue was $1.20 billion',
            'confidence': 0.9,
        },
    }
    payload.update(overrides)
    return ExtractionRecord.model_validate(payload)


def test_quote_found_and_not_found(config: Config) -> None:
    """A verbatim quote scores high; an invented quote scores low."""
    assert verify_quote('GAAP diluted earnings per share were $0.55', SOURCE) > 0.95
    assert verify_quote('Operating cash flow reached $9 trillion', SOURCE) < 0.8
    issues, _validated = validate_record(
        _record(
            reported_eps={
                'value': 0.55,
                'evidence_quote': 'Operating cash flow reached $9 trillion',
                'confidence': 0.9,
            }
        ),
        SOURCE,
        config,
    )
    assert any(issue.code == 'quote_not_found' for issue in issues)


def test_number_not_in_quote_flagged(config: Config) -> None:
    """A numeric value whose digits are absent from its quote is flagged."""
    assert number_in_quote(1200000000.0, 'revenue was $1.20 billion')
    assert not number_in_quote(0.99, 'earnings per share were $0.55')
    issues, _validated = validate_record(
        _record(
            revenue={
                'value': 9.99,
                'evidence_quote': 'Third quarter revenue was $1.20 billion',
                'confidence': 0.9,
            }
        ),
        SOURCE,
        config,
    )
    assert any(issue.code == 'number_not_in_quote' for issue in issues)


def test_confidence_penalty_applied(config: Config) -> None:
    """Each issue multiplies the offending field's confidence by the penalty."""
    record = _record(
        reported_eps={
            'value': 0.99,
            'evidence_quote': 'nothing like this appears anywhere in the filing at all',
            'confidence': 1.0,
        }
    )
    issues, validated = validate_record(record, SOURCE, config)
    assert issues
    expected = 1.0 * config.extraction.confidence_penalty_on_issue**2
    assert validated.reported_eps.confidence <= expected + 1e-9
    assert validated.reported_eps.confidence < 1.0


def test_period_and_basis_issues(config: Config) -> None:
    """An out-of-range quarter and a missing basis are both flagged."""
    record = _record(
        fiscal_quarter=7,
        eps_basis={'value': None},
        reported_eps={
            'value': 0.55,
            'evidence_quote': 'GAAP diluted earnings per share were $0.55',
            'confidence': 0.9,
        },
    )
    issues, _validated = validate_record(record, SOURCE, config)
    codes = {issue.code for issue in issues}
    assert 'period_invalid' in codes
    assert 'basis_missing' in codes


def test_needs_review_lists_reasons(config: Config) -> None:
    """Low confidence and validation issues both trigger review."""
    record = _record(
        reported_eps={'value': 0.55, 'evidence_quote': 'invented line', 'confidence': 0.1}
    )
    issues, validated = validate_record(record, SOURCE, config)
    reasons = needs_review(validated, issues, config)
    assert 'low_confidence:reported_eps' in reasons
    assert 'validation_issues' in reasons


def test_clean_record_not_queued(config: Config) -> None:
    """A fully evidenced record needs no review."""
    issues, validated = validate_record(_record(), SOURCE, config)
    assert issues == []
    assert needs_review(validated, issues, config) == []


def test_all_null_earnings_record_flagged_empty_extraction(config: Config) -> None:
    """An earnings release with neither EPS nor revenue is not an honest pair of nulls."""
    from nowcast.extraction.schema import NullReason

    empty = _record(
        reported_eps={'value': None, 'null_reason': NullReason.not_stated},
        revenue={'value': None, 'null_reason': NullReason.not_stated},
    )
    issues, validated = validate_record(empty, SOURCE, config)
    reasons = needs_review(validated, issues, config)
    assert 'empty_extraction' in reasons
    # It is its own reason, not the per-field not_stated bookkeeping.
    assert not any(reason.startswith('null_reason_missing') for reason in reasons)


def test_partial_record_is_not_empty_extraction(config: Config) -> None:
    """One core number is enough to prove the document was an earnings release."""
    partial = _record(revenue={'value': None, 'null_reason': 'not_stated'})
    issues, validated = validate_record(partial, SOURCE, config)
    assert 'empty_extraction' not in needs_review(validated, issues, config)
