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


@dataclass(frozen=True)
class EvidenceSpan:
    """Offsets refer to the preserved source; matched_text selects the relevant column."""

    start: int
    end: int
    text: str
    matched_text: str
    unit_context: str = ''


def _period_matches(text: str, year: int | None, quarter: int | None) -> bool:
    years = re.findall(r'\b20\d{2}\b', text)
    quarters = re.findall(r'\bQ([1-4])\b', text, re.I)
    return (not years or year is None or str(year) in years) and (
        not quarters or quarter is None or str(quarter) in quarters
    )


def evidence_span(
    quote: str, source: str, year: int | None = None, quarter: int | None = None
) -> EvidenceSpan | None:
    """Select by row label and period before checking numbers, never by value alone."""
    if not quote or not source:
        return None
    exact = source.lower().find(quote.lower())
    if exact >= 0:
        start = source.rfind('\n', 0, exact) + 1
        end = source.find('\n', exact + len(quote))
        line = source[start : end if end >= 0 else len(source)]
        if ' | ' not in line and not _period_matches(quote, year, quarter):
            return EvidenceSpan(exact, exact + len(quote), source[exact : exact + len(quote)], '')
        if ' | ' not in line:
            return EvidenceSpan(
                exact,
                exact + len(quote),
                source[exact : exact + len(quote)],
                source[exact : exact + len(quote)],
            )
    candidates: list[tuple[float, EvidenceSpan]] = []
    offset = 0
    unit_context = ''
    for line in source.splitlines(keepends=True):
        text = line.rstrip('\r\n')
        if text.startswith('[table units:'):
            unit_context = text
        if ' | ' in text:
            cells = text.split(' | ')
            label = cells[0]
            periods = [cell for cell in cells[1:] if re.match(r'\[.*?20\d{2}.*?\]', cell)]
            if periods:
                chosen = [cell for cell in periods if year and str(year) in cell.split(']')[0]]
                if len(chosen) > 1:
                    chosen = [
                        cell
                        for cell in chosen
                        if quarter is not None
                        and re.search(r'\bQ' + str(quarter) + r'\b', cell.split(']')[0], re.I)
                    ]
                if len(chosen) > 1:
                    chosen = []

                projected = (
                    label + ' ' + ' '.join(re.sub(r'^\[.*?\]\s*', '', cell) for cell in chosen)
                )
            else:
                projected = ' '.join(cells)
            quote_label = re.sub(
                r'\b(?:thousands?|millions?|billions?|trillions?|USD|GBP|EUR)\b',
                '',
                quote,
                flags=re.I,
            )
            score = fuzz.ratio(
                re.sub(r'[\d\W]+', ' ', quote_label.lower()).strip(),
                re.sub(r'[\d\W]+', ' ', label.lower()).strip(),
            )
            candidates.append(
                (score, EvidenceSpan(offset, offset + len(text), text, projected, unit_context))
            )
        offset += len(line)
    if candidates:
        best_score, best = max(candidates, key=lambda pair: pair[0])
        # Only a table-label match can select a table row over surrounding prose.
        if best_score >= 85:
            tied = [span for score, span in candidates if score == best_score]
            if len({span.matched_text for span in tied}) > 1:
                return EvidenceSpan(best.start, best.end, best.text, '')
            return best
    if exact >= 0:
        return EvidenceSpan(exact, exact + len(quote), source[exact : exact + len(quote)], '')
    alignment = fuzz.partial_ratio_alignment(quote.lower(), source.lower())
    if alignment is None:
        return None
    start, end = alignment.dest_start, alignment.dest_end
    text = source[start:end]
    line_start = source.rfind('\n', 0, start) + 1
    line_end = source.find('\n', end)
    context = source[line_start : line_end if line_end >= 0 else len(source)]
    matched = text if ' | ' not in context and _period_matches(text, year, quarter) else ''
    return EvidenceSpan(start, end, text, matched)


def matched_window(quote: str, source: str) -> str:
    """Compatibility accessor for the selected evidence span."""
    span = evidence_span(quote, source)
    return span.matched_text if span else ''


TOKEN_NUMBER_RE = re.compile(
    r'(?<![\w.])(?P<open>\()?\s*[$€£]?\s*(?P<sign>[-\u2212+]?)'
    r'(?P<number>\d[\d,]*(?:\.\d+)?)(?P<close>\s*\))?'
    r'\s*(?P<scale>thousands?|millions?|billions?|trillions?)?'
    r'\s*(?P<percent>%|percent\b)?',
    re.I,
)


def number_in_quote(
    value: float, quote: str, unit_context: str = '', percent: bool | None = None
) -> bool:
    """Bind sign and scale to each printed number; percentages remain printed percent."""
    import math

    context_scale = next(
        (scale for scale, word in SCALE_SUFFIXES if word and word in unit_context.lower()), 1.0
    )
    for match in TOKEN_NUMBER_RE.finditer(quote):
        if percent is not None and bool(match['percent']) != percent:
            continue
        printed = float(match['number'].replace(',', ''))
        prefix = quote[max(0, match.start() - 24) : match.start()].lower()
        decreasing = match['percent'] and re.search(
            r'(?:down|declined|decreased|fell)(?: by)?\s*$', prefix
        )
        if match['sign'] in ('-', '\u2212') or (match['open'] and match['close']) or decreasing:
            printed = -printed
        word = (match['scale'] or '').rstrip('s').lower()
        scale = (
            next((scale for scale, suffix in SCALE_SUFFIXES if suffix == word), context_scale)
            if word
            else context_scale
        )
        readings = (printed,) if match['percent'] else (printed, printed * scale)
        if any(math.isclose(value, reading, rel_tol=1e-10, abs_tol=1e-10) for reading in readings):
            return True
    return False


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
TEXT_FIELDS = (
    'eps_basis',
    'prior_year_basis',
    'guidance_presence',
    'guidance_direction',
    'guidance_metric',
    'tone',
)


def validate_record(
    record: ExtractionRecord, source: str, config: Config, report_date: str | None = None
) -> tuple[list[Issue], ExtractionRecord]:
    """Return issue codes and a copy of the record with penalized confidences."""
    issues: list[Issue] = []
    penalty = float(config.extraction.confidence_penalty_on_issue)
    if report_date and record.fiscal_year is not None and record.fiscal_quarter is not None:
        from datetime import date

        stamp = date.fromisoformat(report_date[:10])
        reported_period = record.fiscal_year * 4 + record.fiscal_quarter
        filing_period = stamp.year * 4 + (stamp.month - 1) // 3 + 1
        if not 1 <= record.fiscal_quarter <= 4 or abs(filing_period - reported_period) > 1:
            issues.append(Issue('fiscal_period', 'period_not_near_filing', report_date))

    for name in NUMERIC_FIELDS:
        field = getattr(record, name)
        if field.value is None:
            continue

        def adjust(value: float, target: NumField = field) -> None:
            target.confidence = value

        span = evidence_span(
            field.evidence_quote or '',
            source,
            year=record.fiscal_year,
            quarter=record.fiscal_quarter,
        )
        selected_source = span.matched_text if span else ''
        _check_field_quote(
            name, field.evidence_quote, selected_source, config, issues, adjust, field.confidence
        )
        if field.evidence_quote and not number_in_quote(
            float(field.value),
            field.evidence_quote,
            span.unit_context if span is not None and name == 'revenue' else '',
            percent=name == 'revenue_yoy_growth',
        ):
            issues.append(Issue(name, 'number_not_in_quote', (field.evidence_quote or '')[:80]))
            field.confidence = field.confidence * penalty
        elif field.evidence_quote:
            window = selected_source
            if not number_in_quote(
                float(field.value),
                window,
                span.unit_context if span is not None and name == 'revenue' else '',
                percent=name == 'revenue_yoy_growth',
            ):
                # The quote resembles the source (possibly with a changed digit) but the
                # number is not in the text it matched. Checking the model's own quote
                # only ever proves the model is consistent with itself.
                issues.append(Issue(name, 'number_not_in_source', window[:80]))
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
        vocabulary = config.extraction.vocab(name)
        if vocabulary and str(field.value).lower().strip() not in set(vocabulary):
            # The prompt offers these values; a reply outside them is either a model
            # inventing a category or a prompt drifting from config.
            issues.append(Issue(name, 'vocab_invalid', str(field.value)[:80]))
            field.confidence = field.confidence * penalty

    for theme, mention in record.theme_mentions.items():
        if (
            mention.direction is not None
            and mention.direction not in config.extraction.theme_direction_vocab
        ):
            issues.append(Issue(f'theme.{theme}', 'vocab_invalid', str(mention.direction)))
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


def needs_review(
    record: ExtractionRecord,
    issues: list[Issue],
    config: Config,
    truncated: bool = False,
) -> list[str]:
    """Return the reasons a record must go to the review queue.

    Every field with a value is checked for confidence, not just the numeric ones: a
    low-confidence `tone` or `guidance_direction` is exactly the claim a human should
    look at, and it was silently accepted before.
    """
    reasons: list[str] = []
    minimum = float(config.extraction.min_confidence)
    if is_empty_extraction(record):
        reasons.append('empty_extraction')
    elif record.reported_eps.value is None:
        # Revenue without EPS is a real, partial release; name the gap rather than
        # calling the whole extraction empty.
        reasons.append('eps_missing')
    for name in (*NUMERIC_FIELDS, *TEXT_FIELDS):
        field = getattr(record, name)
        if field.value is not None and field.confidence < minimum:
            reasons.append(f'low_confidence:{name}')
        if field.value is None and field.null_reason is None and field.evidence_quote is not None:
            reasons.append(f'null_reason_missing:{name}')
    for theme, mention in record.theme_mentions.items():
        if mention.mentioned and mention.confidence < minimum:
            reasons.append(f'low_confidence:theme.{theme}')
    if truncated:
        reasons.append('doc_truncated')
    if issues:
        reasons.append('validation_issues')
    return reasons
