"""Normalise the free-text `units` label and the percent convention for growth.

The model copies figures as printed, so `units` arrives as prose ("dollars",
"USD billions", "GBP millions"). A label that mixes currency and scale in free text
cannot be compared or aggregated, so it is rewritten into a two-part token:

    "<CCY>"           currency only, scale not stated
    "<CCY> <scale>"   e.g. "USD billion"

`revenue_yoy_growth` is a percentage as printed: a 4% increase is 4.0, never 0.04.
A model that returns the fraction for the same sentence is corrected here, because
the evidence quote shows which reading the document used. The correction only ever
fires when the printed number in the quote supports it.
"""

from __future__ import annotations

import re
from typing import Any

from nowcast.extraction.schema import ExtractionRecord
from nowcast.extraction.validators import number_in_quote

PERCENT_RE = re.compile(r'%|\b(?:percent|pct)\b', re.IGNORECASE)
TOKEN_RE = re.compile(r'[$£€¥]|[A-Za-z]+')

CURRENCY_ALIASES = {
    '$': 'USD',
    'usd': 'USD',
    'us dollar': 'USD',
    'us dollars': 'USD',
    'dollar': 'USD',
    'dollars': 'USD',
    'gbp': 'GBP',
    '£': 'GBP',
    'pound': 'GBP',
    'pounds': 'GBP',
    'sterling': 'GBP',
    'eur': 'EUR',
    '€': 'EUR',
    'euro': 'EUR',
    'euros': 'EUR',
    'jpy': 'JPY',
    '¥': 'JPY',
    'yen': 'JPY',
    'cad': 'CAD',
    'aud': 'AUD',
    'chf': 'CHF',
}

SCALE_ALIASES = {
    'thousand': 'thousand',
    'thousands': 'thousand',
    'k': 'thousand',
    'million': 'million',
    'millions': 'million',
    'mn': 'million',
    'mm': 'million',
    'm': 'million',
    'billion': 'billion',
    'billions': 'billion',
    'bn': 'billion',
    'trillion': 'trillion',
    'trillions': 'trillion',
    'tn': 'trillion',
}


def normalise_units(raw: str | None, currency: str | None = None) -> str | None:
    """Return a canonical `<CCY> [scale]` label, or the raw label when unrecognised.

    A recognised part is always preferred, so "dollars" becomes "USD" and
    "USD billions" becomes "USD billion". Text with neither a currency nor a scale
    is kept verbatim: dropping what the model said would be a silent loss of
    information, and a label nobody recognises is precisely the kind a human should
    see. `currency` supplies the currency when the label names only a scale.
    """
    text = '' if raw is None else str(raw).strip()
    recognised_currency: str | None = None
    recognised_scale: str | None = None
    for token in TOKEN_RE.findall(text):
        key = token.lower()
        if recognised_currency is None and key in CURRENCY_ALIASES:
            recognised_currency = CURRENCY_ALIASES[key]
        elif recognised_scale is None and key in SCALE_ALIASES:
            recognised_scale = SCALE_ALIASES[key]
    if recognised_currency is None and currency:
        fallback = str(currency).strip().lower()
        recognised_currency = CURRENCY_ALIASES.get(fallback)
        if recognised_currency is None and re.fullmatch(r'[a-z]{3}', fallback):
            recognised_currency = fallback.upper()
    if recognised_currency is None and recognised_scale is None:
        return text or None
    if recognised_scale is None:
        return recognised_currency
    if recognised_currency is None:
        return recognised_scale
    return f'{recognised_currency} {recognised_scale}'


def normalise_growth(value: float, quote: str | None) -> float:
    """Return a growth figure as a percentage of the printed figure.

    The quote decides the reading. When it prints a percent sign, the value is
    accepted if its digits appear in the quote; otherwise the fraction reading is
    tried. A 0.5% growth whose value is already 0.5 is left alone, because 0.5 is
    the number the quote shows. When neither reading matches the quote, the value
    is returned unchanged and validation reports the mismatch.
    """
    if not quote or not PERCENT_RE.search(quote):
        return value
    candidates = [value] if abs(value) >= 1 else [value, value * 100]
    for candidate in candidates:
        if number_in_quote(candidate, quote):
            return round(candidate, 6)
    return value


def normalise_record(record: ExtractionRecord) -> ExtractionRecord:
    """Return a copy of the record with a canonical units label and growth percent."""
    changes: dict[str, Any] = {}
    units = normalise_units(record.units, record.currency)
    if units != record.units:
        changes['units'] = units
    growth = record.revenue_yoy_growth
    if growth.value is not None:
        value = normalise_growth(float(growth.value), growth.evidence_quote)
        if value != growth.value:
            changes['revenue_yoy_growth'] = growth.model_copy(update={'value': value})
    return record.model_copy(update=changes) if changes else record
