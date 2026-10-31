"""Point-in-time index membership from a constituents CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from nowcast.errors import DataError

REQUIRED_COLUMNS = ('ticker', 'cik', 'effective_from', 'effective_to')
OPEN_END = pd.Timestamp('2100-01-01')
OPTIONAL_COLUMNS = ('weight',)


def load_constituents(path: Path | str) -> pd.DataFrame:
    """Load and validate the constituents CSV, raising DataError naming what is missing."""
    target = Path(path)
    if not target.is_file():
        raise DataError(f'constituents file not found: {target}')
    frame = pd.read_csv(target, dtype={'cik': str, 'ticker': str})
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DataError(
            f'constituents file {target} is missing required columns: {", ".join(missing)}; '
            f'required: {", ".join(REQUIRED_COLUMNS)}; optional: {", ".join(OPTIONAL_COLUMNS)}'
        )
    frame['ticker'] = frame['ticker'].str.strip().str.upper()
    frame['cik'] = frame['cik'].str.strip().str.zfill(10)
    frame['effective_from'] = pd.to_datetime(frame['effective_from'])
    frame['effective_to'] = pd.to_datetime(frame['effective_to'])
    if (frame['effective_to'] < frame['effective_from']).any():
        raise DataError('constituents file has effective_to earlier than effective_from')
    if 'weight' not in frame.columns:
        frame['weight'] = 1.0
    frame['weight'] = pd.to_numeric(frame['weight'], errors='coerce').fillna(1.0)
    return frame.sort_values(['ticker', 'effective_from']).reset_index(drop=True)


def active_on(frame: pd.DataFrame, as_of: pd.Timestamp | str) -> pd.DataFrame:
    """Return constituents whose membership window contains the given date.

    An empty effective_to means "still a member", and NaT compares False against
    every date, so it must be filled with an open-ended sentinel rather than
    relied on to sort itself out.
    """
    stamp = pd.Timestamp(as_of).normalize()
    starts = pd.to_datetime(frame['effective_from'])
    ends = pd.to_datetime(frame['effective_to']).fillna(OPEN_END)
    mask = (starts <= stamp) & (ends >= stamp)
    return frame.loc[mask].reset_index(drop=True)


def cik_list(frame: pd.DataFrame, as_of: pd.Timestamp | str | None = None) -> list[str]:
    """Return unique zero-padded CIK strings, optionally restricted to one date."""
    subset = active_on(frame, as_of) if as_of is not None else frame
    return sorted({str(value) for value in subset['cik'].tolist()})
