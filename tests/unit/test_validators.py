"""Unit tests for evidence validators."""

from __future__ import annotations

import dataclasses

import pytest

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


def test_missing_evidence_penalises_confidence(config: Config) -> None:
    """A value with no quote at all is penalized once, exactly like a bad quote."""
    record = _record(reported_eps={'value': 0.55, 'confidence': 1.0})
    issues, validated = validate_record(record, SOURCE, config)
    assert [issue.code for issue in issues] == ['quote_missing']
    assert validated.reported_eps.confidence == pytest.approx(
        config.extraction.confidence_penalty_on_issue
    )


def test_quote_at_exactly_the_threshold_is_accepted(config: Config) -> None:
    """The threshold is a floor: a quote scoring exactly at it is evidence, not a miss."""
    quote = 'quarter revenue was one point two billion'
    score = verify_quote(quote, SOURCE)
    assert score == pytest.approx(0.7)
    exact = dataclasses.replace(
        config,
        extraction=dataclasses.replace(config.extraction, quote_match_min_ratio=score),
    )
    issues, _validated = validate_record(
        _record(eps_basis={'value': 'gaap', 'evidence_quote': quote, 'confidence': 0.9}),
        SOURCE,
        exact,
    )
    assert not any(issue.code == 'quote_not_found' for issue in issues)


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


def test_mutated_digit_in_quote_is_flagged(config: Config) -> None:
    """A quote with one wrong digit matches the source fuzzily, but its number does not."""
    # 0.57 vs the printed 0.55: partial_ratio is high, so the quote check alone passes.
    mutated = _record(
        reported_eps={
            'value': 0.57,
            'evidence_quote': 'GAAP diluted earnings per share were $0.57',
            'confidence': 0.9,
        }
    )
    assert verify_quote(mutated.reported_eps.evidence_quote, SOURCE) > 0.85
    issues, _validated = validate_record(mutated, SOURCE, config)
    codes = {(issue.field, issue.code) for issue in issues}
    assert ('reported_eps', 'number_not_in_source') in codes


def test_correct_quote_with_scaled_number_passes(config: Config) -> None:
    """A printed 1.20 billion with value 1.2 is correct, and must not be flagged."""
    issues, _validated = validate_record(_record(), SOURCE, config)
    codes = {(issue.field, issue.code) for issue in issues}
    assert ('revenue', 'number_not_in_source') not in codes
    assert ('revenue', 'number_not_in_quote') not in codes


def test_every_prompt_vocabulary_value_is_accepted_downstream(config: Config) -> None:
    """Each configured vocabulary value validates; nothing the prompt offers is rejected."""
    for field, vocab in (
        ('eps_basis', config.extraction.eps_basis_vocab),
        ('guidance_direction', config.extraction.guidance_direction_vocab),
        ('tone', config.extraction.tone_vocab),
    ):
        for value in vocab:
            record = _record(
                **{field: {'value': value, 'evidence_quote': SOURCE, 'confidence': 0.9}}
            )
            issues, _validated = validate_record(record, SOURCE, config)
            assert not [issue for issue in issues if issue.code == 'vocab_invalid'], (
                f'{field}={value!r} is offered by the prompt but rejected by the validator'
            )


def test_value_outside_vocabulary_is_flagged(config: Config) -> None:
    """A model inventing a category gets a named issue, not a silent pass."""
    record = _record(
        tone={
            'value': 'ecstatic',
            'evidence_quote': 'GAAP diluted earnings per share',
            'confidence': 0.9,
        }
    )
    issues, _validated = validate_record(record, SOURCE, config)
    assert ('tone', 'vocab_invalid') in {(issue.field, issue.code) for issue in issues}


def test_low_confidence_text_field_queued(config: Config) -> None:
    """A low-confidence guidance_direction or tone reaches the queue like a number does."""
    record = _record(
        guidance_direction={
            'value': 'raised',
            'evidence_quote': 'up 4% year over year',
            'confidence': 0.1,
        },
        tone={'value': 'cautious', 'evidence_quote': 'up 4% year over year', 'confidence': 0.1},
    )
    reasons = needs_review(record, [], config)
    assert 'low_confidence:guidance_direction' in reasons
    assert 'low_confidence:tone' in reasons


def test_low_confidence_theme_mention_queued(config: Config) -> None:
    """A theme the model is unsure about is a claim a human should see."""
    record = _record(
        theme_mentions={
            'demand': {
                'mentioned': True,
                'direction': 'up',
                'evidence_quote': 'up 4% year over year',
                'confidence': 0.1,
            }
        }
    )
    assert 'low_confidence:theme.demand' in needs_review(record, [], config)


def test_eps_missing_flagged_separately(config: Config) -> None:
    """Revenue without EPS is partial, not empty: the two reasons must differ."""
    partial = _record(
        reported_eps={'value': None, 'null_reason': 'not_stated', 'confidence': 0.0},
        prior_year_eps={'value': None, 'null_reason': 'not_stated', 'confidence': 0.0},
    )
    reasons = needs_review(partial, [], config)
    assert 'eps_missing' in reasons
    assert 'empty_extraction' not in reasons

    empty = _record(
        reported_eps={'value': None, 'null_reason': 'not_stated', 'confidence': 0.0},
        revenue={'value': None, 'null_reason': 'not_stated', 'confidence': 0.0},
    )
    empty_reasons = needs_review(empty, [], config)
    assert 'empty_extraction' in empty_reasons
    assert 'eps_missing' not in empty_reasons


def test_truncated_document_queued_as_doc_truncated(config: Config) -> None:
    """A cut document is not a clean success, even when the record itself is fine."""
    reasons = needs_review(_record(), [], config, truncated=True)
    assert 'doc_truncated' in reasons
    assert 'doc_truncated' not in needs_review(_record(), [], config, truncated=False)
