"""S&P 500 membership reconstructed from Wikipedia's current and changes tables."""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path
from typing import TypedDict

import pandas as pd

from nowcast.config import Config
from nowcast.errors import DataError
from nowcast.ingestion.universe.base import (
    Anomaly,
    FetchResult,
    MembershipSource,
    empty_membership,
    fetch_html,
    normalise_ticker,
    to_date,
    user_agent,
)

CURRENT_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    'ticker': ('symbol', 'ticker', 'ticker symbol'),
    'company_name': ('security', 'company', 'company name', 'name'),
    'date_added': ('date added', 'added'),
}
CHANGES_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    # Grouped tables flatten to 'added ticker' / 'removed security' / 'effective date';
    # older single-level versions used bare 'added' / 'removed' / 'date'.
    'date': ('effective date', 'date'),
    'added_ticker': ('added ticker', 'added'),
    'added_name': ('added security', 'added company', 'added name'),
    'removed_ticker': ('removed ticker', 'removed'),
    'removed_name': ('removed security', 'removed company', 'removed name'),
}
OPEN_END = date(2100, 1, 1)


class _Entry(TypedDict):
    """A membership under reconstruction, before its start date is known."""

    company_name: str
    start: date | None
    end: date | None


def _flatten_column(column: object) -> str:
    """Flatten a two-level header into the alias the parser expects.

    Wikipedia's changes table is a grouped table: the top row says "Added" and
    "Removed" while the second row says "Ticker" and "Security", so the real
    column names are 'Added Ticker', 'Added Security', 'Removed Ticker' and so on.
    Reading only the top level loses the ticker/security distinction.
    """
    parts = [str(part) for part in column] if isinstance(column, tuple) else [str(column)]
    # Grouped tables repeat a single-level heading on both rows
    # (('Effective Date', 'Effective Date')), so keep only distinct labels.
    seen: list[str] = []
    for part in parts:
        text = part.strip()
        if text and text != 'nan' and text not in seen:
            seen.append(text)
    return re.sub(r'\s+', ' ', ' '.join(seen))


def _normalise_header(value: str) -> str:
    """Lower-case a table header and collapse whitespace."""
    return re.sub(r'\s+', ' ', str(value)).strip().lower()


def _locate_table(
    tables: list[pd.DataFrame], aliases: dict[str, tuple[str, ...]], label: str
) -> pd.DataFrame:
    """Return the first table whose headers satisfy every alias group."""
    errors: list[str] = []
    for table in tables:
        if isinstance(table.columns, pd.MultiIndex):
            table = table.copy()
            table.columns = [_flatten_column(column) for column in table.columns]
        headers = {_normalise_header(column) for column in table.columns}
        mapping: dict[str, str] = {}
        missing: list[str] = []
        for target, candidates in aliases.items():
            found = next((candidate for candidate in candidates if candidate in headers), None)
            if found is None:
                missing.append(target)
            else:
                mapping[target] = found
        if not missing:
            renamed = table.rename(
                columns={
                    original: key
                    for original in table.columns
                    for key, header in mapping.items()
                    if _normalise_header(original) == header
                }
            )
            return renamed[list(aliases)]
        errors.append(f'{label} table missing {sorted(set(missing))}')
    found_columns: set[str] = set()
    for table in tables:
        found_columns.update(_normalise_header(column) for column in table.columns)
    detail = ', '.join(sorted(found_columns))
    raise DataError(
        f'could not locate the {label} table; columns found on the page: {detail}; '
        f'required one of {sorted(aliases)}; ' + ' | '.join(errors[:3])
    )


def parse_current_table(html: str) -> pd.DataFrame:
    """Parse the current constituents table into ticker/company_name/date_added."""
    tables = pd.read_html(io.StringIO(html))
    table = _locate_table(tables, CURRENT_COLUMN_ALIASES, 'current constituents')
    frame = pd.DataFrame(
        {
            'ticker': table['ticker'].map(normalise_ticker),
            'company_name': table['company_name'].astype(str).str.strip(),
            'date_added': table['date_added'],
        }
    )
    return frame[frame['ticker'] != '']


def parse_changes_table(html: str) -> pd.DataFrame:
    """Parse the add/remove changes table into normalised events."""
    tables = pd.read_html(io.StringIO(html))
    table = _locate_table(tables, CHANGES_COLUMN_ALIASES, 'changes')
    frame = pd.DataFrame(
        {
            'event_date': table['date'].map(to_date),
            'added_ticker': table['added_ticker'].map(normalise_ticker),
            'added_name': table['added_name'].fillna('').astype(str).str.strip(),
            'removed_ticker': table['removed_ticker'].map(normalise_ticker),
            'removed_name': table['removed_name'].fillna('').astype(str).str.strip(),
        }
    )
    return frame


LEGAL_SUFFIXES = (
    'incorporated',
    'inc',
    'corporation',
    'corp',
    'company',
    'co',
    'plc',
    'ltd',
    'limited',
    'llc',
    'lp',
    'holdings',
    'holding',
    'group',
    'the',
    '&',
)
NAME_PUNCTUATION = re.compile(r'[^a-z0-9 ]+')


def _same_company(left: str, right: str) -> bool:
    """Compare two company names ignoring legal suffixes, punctuation and case.

    The changes table says "KKR" while the current table says "KKR & Co."; that is
    the same company and must not be reported as a name mismatch, or the real
    anomalies are buried in noise.
    """

    def core(text: str) -> str:
        cleaned = NAME_PUNCTUATION.sub(' ', text.lower())
        words = [word for word in cleaned.split() if word not in LEGAL_SUFFIXES]
        return ' '.join(words)

    a, b = core(left), core(right)
    if not a or not b:
        return True
    return a == b or a in b or b in a


def _open_before(entry: _Entry, event_day: date) -> bool:
    """Return whether an entry's membership is still open at the given event date."""
    end = entry['end']
    if end is None:
        return True
    return isinstance(end, date) and end > event_day


def _pick_entry(entries: list[_Entry], company_name: str, event_day: date) -> _Entry | None:
    """Pick the open membership entry an add event is undoing.

    Prefer a name match, then any entry whose start equals the event date (its
    interval starts there), else the most recent entry, which is the one a later
    removal would have closed.
    """
    if not entries:
        return None
    if company_name:
        named = [entry for entry in entries if entry['company_name'] == company_name]
        if named:
            return named[-1]
    matching = [
        entry for entry in entries if entry['start'] is not None and entry['start'] == event_day
    ]
    if matching:
        return matching[-1]
    return entries[-1]


def _remove_entry(pending: dict[str, list[_Entry]], ticker: str, entry: _Entry) -> None:
    """Remove one entry from the pending map, dropping the ticker when it empties."""
    remaining = [item for item in pending.get(ticker, []) if item is not entry]
    if remaining:
        pending[ticker] = remaining
    else:
        pending.pop(ticker, None)


def reconstruct_membership(
    current: pd.DataFrame, changes: pd.DataFrame, as_of: date | None = None
) -> tuple[pd.DataFrame, list[Anomaly]]:
    """Walk change events backward from the current list to build intervals.

    A ticker can name more than one company over time (ticker reuse), so the
    still-open membership of each ticker is kept as a stack of entries rather
    than a single value. Each entry closes into an interval when the later
    event that ends it is undone.
    """
    anomalies: list[Anomaly] = []
    del as_of  # reserved: the current table is always the "as of now" snapshot
    # Pending memberships that have not been given a start date yet, keyed by ticker.
    # Parallels a classic backward walk, but a ticker may name several companies over
    # time (ticker reuse), so each ticker keeps a list rather than a single name.
    pending: dict[str, list[_Entry]] = {}
    for row in current.to_dict('records'):
        ticker = str(row['ticker'])
        pending.setdefault(ticker, []).append(
            {
                'company_name': str(row['company_name']),
                'start': to_date(row.get('date_added')),
                'end': None,
            }
        )
    intervals: list[dict[str, object]] = []

    events = changes.copy()
    events['event_date'] = events['event_date'].map(to_date)
    for record in events.to_dict('records'):
        if record['event_date'] is None:
            anomalies.append(
                Anomaly(
                    kind='unparseable_date',
                    detail=f'event with added={record["added_ticker"]} removed={record["removed_ticker"]}',
                    ticker=str(record['added_ticker'] or record['removed_ticker']),
                    source='changes_table',
                )
            )
    events = events[events['event_date'].notna()]
    events = events.sort_values('event_date', ascending=False, kind='stable')

    for record in events.to_dict('records'):
        event_day: date = record['event_date']
        added = str(record['added_ticker'] or '')
        removed = str(record['removed_ticker'] or '')
        added_name = str(record['added_name'] or '')
        removed_name = str(record['removed_name'] or '')

        if added:
            entry = _pick_entry(pending.get(added, []), added_name, event_day)
            if entry is None:
                anomalies.append(
                    Anomaly(
                        kind='remove_missing',
                        detail='undo add: ticker was not in the member set after this date',
                        ticker=added,
                        company_name=added_name,
                        event_date=event_day.isoformat(),
                        source='changes_table',
                    )
                )
            else:
                if added_name and not _same_company(added_name, str(entry['company_name'])):
                    anomalies.append(
                        Anomaly(
                            kind='name_mismatch',
                            detail=f'add event names {added_name!r} but the open '
                            f'membership is {entry["company_name"]!r}',
                            ticker=added,
                            company_name=added_name,
                            event_date=event_day.isoformat(),
                            source='changes_table',
                        )
                    )
                # The current table's "Date added" and the event log legitimately differ
                # by a few days (announcement vs close). The event log is the authority
                # for start dates; a wide gap is worth recording.
                start = event_day
                if entry['start'] is not None and abs((entry['start'] - event_day).days) > 30:
                    anomalies.append(
                        Anomaly(
                            kind='start_conflict',
                            detail=f'add event dated {event_day} but the table says '
                            f'{entry["start"]}; using the event date',
                            ticker=added,
                            company_name=added_name,
                            event_date=event_day.isoformat(),
                            source='changes_table',
                        )
                    )
                intervals.append(
                    {
                        'ticker': added,
                        'company_name': str(entry['company_name']),
                        'effective_from': start,
                        'effective_to': entry['end'],
                    }
                )
                _remove_entry(pending, added, entry)

        if removed:
            already_open = [
                entry
                for entry in pending.get(removed, [])
                if _open_before(entry, event_day)
                and (not removed_name or entry['company_name'] == removed_name)
            ]
            if already_open:
                anomalies.append(
                    Anomaly(
                        kind='add_existing',
                        detail='undo remove: ticker already in the member set before this date',
                        ticker=removed,
                        company_name=removed_name,
                        event_date=event_day.isoformat(),
                        source='changes_table',
                    )
                )
            else:
                pending.setdefault(removed, []).append(
                    {'company_name': removed_name, 'start': None, 'end': event_day}
                )

    for ticker, entries in pending.items():
        for entry in entries:
            if entry['start'] is None:
                anomalies.append(
                    Anomaly(
                        kind='unknown_start',
                        detail='membership has an end but no recorded addition; '
                        'the interval is dropped from constituents.csv',
                        ticker=ticker,
                        company_name=str(entry['company_name']),
                        event_date=str(entry['end'] or ''),
                        source='changes_table',
                    )
                )
            intervals.append(
                {
                    'ticker': ticker,
                    'company_name': str(entry['company_name']),
                    'effective_from': entry['start'],
                    'effective_to': entry['end'],
                }
            )

    frame = pd.DataFrame(
        intervals, columns=['ticker', 'company_name', 'effective_from', 'effective_to']
    )
    if frame.empty:
        return empty_membership(), anomalies
    # Rows without a start date are written out as `unknown_start` anomalies above and
    # cannot be placed on a timeline, so they are excluded here rather than dropped quietly.
    frame = frame[frame['effective_from'].notna()]
    if frame.empty:
        return empty_membership(), anomalies
    frame['effective_from'] = pd.to_datetime(frame['effective_from'])
    frame['effective_to'] = pd.to_datetime(frame['effective_to'])
    frame['cik_hint'] = None
    frame = frame.sort_values(['ticker', 'effective_from']).reset_index(drop=True)
    return frame, anomalies


def load_source(
    config: Config, cache_root: Path, transport: object | None = None
) -> MembershipSource:
    """Fetch both Wikipedia tables and return reconstructed membership intervals."""
    agent = user_agent(config)
    settings = config.universe
    if not settings.current_table_url or not settings.changes_table_url:
        raise DataError('universe.current_table_url and universe.changes_table_url must be set')
    current_fetch: FetchResult = fetch_html(
        settings.current_table_url,
        cache_root,
        agent,
        settings.refresh,
        transport=transport,  # type: ignore[arg-type]
    )
    changes_fetch: FetchResult = fetch_html(
        settings.changes_table_url,
        cache_root,
        agent,
        settings.refresh,
        transport=transport,  # type: ignore[arg-type]
    )
    current = parse_current_table(current_fetch.cache_path.read_text(encoding='utf-8'))
    changes = parse_changes_table(changes_fetch.cache_path.read_text(encoding='utf-8'))
    frame, anomalies = reconstruct_membership(current, changes)
    return MembershipSource(
        frame=frame,
        anomalies=anomalies,
        provenance={
            'current_table_url': settings.current_table_url,
            'changes_table_url': settings.changes_table_url,
            'current_sha256': current_fetch.sha256,
            'changes_sha256': changes_fetch.sha256,
            'current_fetched_at': current_fetch.fetched_at,
            'changes_fetched_at': changes_fetch.fetched_at,
            'current_from_cache': current_fetch.from_cache,
            'changes_from_cache': changes_fetch.from_cache,
        },
    )
