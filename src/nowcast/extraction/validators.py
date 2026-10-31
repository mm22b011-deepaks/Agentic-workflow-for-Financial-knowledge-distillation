"""Evidence and consistency checks for extracted records."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from rapidfuzz import fuzz

from nowcast.config import Config
from nowcast.extraction.schema import ExtractionRecord, NumField, TextField

NUMBER_RE = re.compile(r'-?\d[\d,]*\.?\d*')
SCALE_SUFFIXES = (
    (1.0, ''),
    (1e3, 'thousand'),
    (1e6, 'million'),
    (1e9, 'billion'),
    (1e12, 'trillion'),
)


@dataclass(frozen=True)
class Issue:
    """One validation problem tied to a field path."""

    field: str
    code: str
    detail: str


def verify_quote(quote: str, source: str) -> float:
    """Return a 0..1 similarity between a quote and the source text."""
    if not quote or not source:
        return 0.0
    return round(fuzz.partial_ratio(quote.lower(), source.lower()) / 100.0, 4)


def _digits_in(text: str) -> set[str]:
    """Return the numeric tokens of a string with commas and signs stripped."""
    tokens: set[str] = set()
    for match in NUMBER_RE.findall(text):
        token = match.replace(',', '').lstrip('-').rstrip('.')
        if token:
            tokens.add(token)
    return tokens


def number_in_quote(value: float, quote: str) -> bool:
    """Return True when the digits of a number appear in its evidence quote."""
    if not quote:
        return False
    magnitude = abs(float(value))
    candidates = {repr(magnitude), f'{magnitude:.2f}', f'{magnitude:.4f}'.rstrip('0').rstrip('.')}
    for divisor, suffix in SCALE_SUFFIXES:
        scaled = magnitude / divisor
        candidates.add(f'{scaled:.2f}'.rstrip('0').rstrip('.'))
        if suffix and suffix in quote.lower():
            candidates.add(f'{scaled:.2f}')
    quote_tokens = _digits_in(quote)
    return any(candidate and candidate in quote_tokens for candidate in candidates)


def _check_field_quote(
    field: str,
    quote: str | None,
    source: str,
    config: Config,
    issues: list[Issue],
    adjust: Callable[[float], None],
    confidence: float,
) -> None:
    """Record quote issues for one field and apply the confidence penalty."""
    penalty = float(config.extraction.confidence_penalty_on_issue)
    if not quote:
        issues.append(Issue(field, 'quote_missing', 'value present without evidence'))
        adjust(confidence * penalty)
        return
    if len(quote.split()) > config.extraction.max_evidence_words:
        issues.append(Issue(field, 'quote_too_long', f'{len(quote.split())} words'))
        confidence = confidence * penalty
        adjust(confidence)
    if verify_quote(quote, source) < float(config.extraction.quote_match_min_ratio):
        issues.append(Issue(field, 'quote_not_found', quote[:80]))
        adjust(confidence * penalty)


NUMERIC_FIELDS = (
    'reported_eps',
    'prior_year_eps',
    'consensus_eps',
    'revenue',
    'revenue_yoy_growth',
)
TEXT_FIELDS = ('eps_basis', 'guidance_direction', 'guidance_metric', 'tone')


def validate_record(
    record: ExtractionRecord, source: str, config: Config
) -> tuple[list[Issue], ExtractionRecord]:
    """Return issue codes and a copy of the record with penalized confidences."""
    issues: list[Issue] = []
    penalty = float(config.extraction.confidence_penalty_on_issue)

    for name in NUMERIC_FIELDS:
        field = getattr(record, name)
        if field.value is None:
            continue

        def adjust(value: float, target: NumField = field) -> None:
            target.confidence = value

        _check_field_quote(
            name, field.evidence_quote, source, config, issues, adjust, field.confidence
        )
        if field.evidence_quote and not number_in_quote(float(field.value), field.evidence_quote):
            issues.append(Issue(name, 'number_not_in_quote', (field.evidence_quote or '')[:80]))
            field.confidence = field.confidence * penalty

    for name in TEXT_FIELDS:
        field = getattr(record, name)
        if field.value is None:
            continue

        def adjust_text(value: float, target: TextField = field) -> None:
            target.confidence = value

        _check_field_quote(
            name, field.evidence_quote, source, config, issues, adjust_text, field.confidence
        )

    for theme, mention in record.theme_mentions.items():
        if not mention.mentioned:
            continue
        if mention.evidence_quote and verify_quote(mention.evidence_quote, source) < float(
            config.extraction.quote_match_min_ratio
        ):
            issues.append(Issue(f'theme.{theme}', 'quote_not_found', mention.evidence_quote[:80]))
            mention.confidence = mention.confidence * penalty
        elif not mention.evidence_quote:
            issues.append(Issue(f'theme.{theme}', 'quote_missing', 'mention without evidence'))
            mention.confidence = mention.confidence * penalty

    quarter = record.fiscal_quarter
    if quarter is not None and not 1 <= quarter <= 4:
        issues.append(Issue('fiscal_quarter', 'period_invalid', str(quarter)))
    if record.reported_eps.value is not None and record.eps_basis.value is None:
        issues.append(Issue('eps_basis', 'basis_missing', 'reported_eps present without basis'))
        record.reported_eps.confidence = record.reported_eps.confidence * penalty
    if (
        record.reported_eps.value is not None
        and record.eps_basis.value
        and (str(record.eps_basis.value).lower() not in {'gaap', 'adjusted'})
    ):
        issues.append(Issue('eps_basis', 'basis_invalid', str(record.eps_basis.value)))
    return issues, record


CORE_NUMERIC_FIELDS = ('reported_eps', 'revenue')


def is_empty_extraction(record: ExtractionRecord) -> bool:
    """Return True when an earnings release yielded none of its core numbers.

    A 2.02 filing that produces no reported EPS and no revenue is not a `not_stated`
    record with two honest nulls: either the document was not a release, or the text
    handed to the model did not contain the figures. Either way it must not pass as a
    clean success, so it is named separately in the review queue.
    """
    return all(getattr(record, name).value is None for name in CORE_NUMERIC_FIELDS)


def needs_review(record: ExtractionRecord, issues: list[Issue], config: Config) -> list[str]:
    """Return the reasons a record must go to the review queue."""
    reasons: list[str] = []
    minimum = float(config.extraction.min_confidence)
    if is_empty_extraction(record):
        reasons.append('empty_extraction')
    for name in NUMERIC_FIELDS:
        field = getattr(record, name)
        if field.value is not None and field.confidence < minimum:
            reasons.append(f'low_confidence:{name}')
        if field.value is None and field.null_reason is None and field.evidence_quote is not None:
            reasons.append(f'null_reason_missing:{name}')
    if issues:
        reasons.append('validation_issues')
    return reasons
