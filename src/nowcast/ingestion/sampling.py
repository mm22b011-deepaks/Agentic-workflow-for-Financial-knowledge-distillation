"""Point-in-time sampling of the universe and de-duplication of filing exhibits.

Two separate biases used to decide what got downloaded: the CIK list was taken in
sorted order and cut at the document cap, so the sample was "the lowest CIKs, latest
filings first"; and every EX-99 exhibit of a filing became its own document, so one
company could occupy several slots with the same release. Both are fixed here, in code,
by seeded selection and an explicit exhibit priority.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, TypeVar

import pandas as pd

from nowcast.config import Config, resolve_data_path
from nowcast.errors import DataError
from nowcast.ingestion.constituents import active_on, load_constituents

# Exhibits that carry the earnings release itself, best first. The primary EX-99.1 is
# the release; an unsuffixed EX-99 is a catch-all used by some filers; an EX-99.2 is
# usually a supplement. A filing contributes one document under the default rule.
EXHIBIT_PRIORITY = ('EX-99.1', 'EX-99', 'EX-99.2')


class DisclosureLike(Protocol):
    """The attributes filing selection reads; satisfied by `edgar.Disclosure`.

    Declared read-only: a protocol with mutable attributes is invariant, and a plain
    dataclass does not satisfy it.
    """

    @property
    def accession(self) -> str: ...

    @property
    def filing_date(self) -> date: ...

    @property
    def exhibit_type(self) -> str: ...

    @property
    def document(self) -> str: ...


T = TypeVar('T', bound=DisclosureLike)


@dataclass(frozen=True)
class Sample:
    """The companies a run will consider, and why anything was left out.

    `seed` and `seasons` travel with the sample so a manifest says how it was drawn,
    not only how many companies came out. Without them a capped run cannot be
    reproduced: the same config today and tomorrow would walk a different set if the
    seed that produced the order were not recorded.
    """

    ciks: tuple[str, ...]
    companies: int
    skipped: dict[str, int] = field(default_factory=dict)
    seed: int = 0
    seasons: tuple[str, ...] = ()
    # (cik, season) pairs this run intends to fetch. A company sampled for one quarter
    # must not be expected to have reported the others, and only these pairs may become
    # the denominator of a share.
    pairs: tuple[tuple[str, str], ...] = ()

    def season_targets(self) -> dict[str, list[str]]:
        """Return the target seasons per company, as ingest wants them."""
        result: dict[str, list[str]] = {}
        for cik, season in self.pairs:
            result.setdefault(cik, []).append(season)
        return result

    def as_dict(self) -> dict[str, object]:
        """Return the sample as JSON-serialisable data."""
        return {
            'companies': self.companies,
            'ciks': len(self.ciks),
            'seed': self.seed,
            'seasons': list(self.seasons),
            'pairs': len(self.pairs),
            'skipped': dict(sorted(self.skipped.items())),
        }


def season_frame(config: Config) -> list[tuple[str, pd.Timestamp]]:
    """Return each calendar quarter in the window with the date members are checked on.

    Seasons are calendar quarters (the same convention `aggregate.season_of` uses), and
    membership is tested at the season's first day, so a company that joined mid-season
    is not sampled for a season it was only partly a member of.
    """
    if not config.data.start_date or not config.data.end_date:
        raise DataError('data.start_date and data.end_date must both be set to sample by season')
    periods = pd.period_range(config.data.start_date, config.data.end_date, freq='Q')
    return [
        (f'{period.year}Q{period.quarter}', period.start_time.normalize()) for period in periods
    ]


def season_sample(config: Config, frame: pd.DataFrame, limit: int | None = None) -> Sample:
    """Return the companies to walk, in a seeded order that is not the alphabet.

    The walk order matters as much as the membership: the ingest stops when the document
    cap is reached, so walking `sorted(ciks)` downloads the alphabetically first
    companies and says nothing about the index. Here the order is a seeded permutation,
    drawn per season, so a capped run is a spread sample.

    With `universe.subset_n` set, only that many companies are drawn per season; with it
    at 0 every member active in the window is kept. Every member appears once — a
    company active in four seasons must not be visited four times.
    """
    if frame.empty:
        return Sample(ciks=(), companies=0, skipped={'no_constituents': 1})
    seasons = season_frame(config)
    if not seasons:
        raise DataError('the configured window contains no quarters to sample')
    n = int(config.universe.subset_n)
    rng = random.Random(int(config.universe.subset_seed))
    chosen: list[str] = []
    pairs: list[tuple[str, str]] = []
    skipped: dict[str, int] = {}
    for name, as_of in seasons:
        members = active_on(frame, as_of)
        ciks = sorted({str(value).zfill(10) for value in members['cik']})
        if not ciks:
            skipped[f'no_members:{name}'] = 1
            continue
        if n <= 0 or n >= len(ciks):
            picked = ciks
        else:
            picked = rng.sample(ciks, n)
            skipped['left_out_by_seed'] = skipped.get('left_out_by_seed', 0) + len(ciks) - n
        # Shuffle inside the season too: companies sampled for every season would
        # otherwise always be visited in the same order and the early seasons' earliest
        # members would fill the cap again.
        rng.shuffle(picked)
        chosen.extend(picked)
        pairs.extend((cik, name) for cik in picked)
    ordered = list(dict.fromkeys(chosen))
    if limit is not None and len(ordered) > limit:
        skipped['left_out_by_cap'] = len(ordered) - limit
        ordered = ordered[:limit]
    kept = set(ordered)
    pairs = [(cik, season) for cik, season in pairs if cik in kept]
    return Sample(
        ciks=tuple(ordered),
        companies=len(ordered),
        skipped=skipped,
        pairs=tuple(pairs),
        seed=int(config.universe.subset_seed),
        seasons=tuple(name for name, _ in seasons),
    )


def sample_from_config(config: Config, limit: int | None = None) -> Sample:
    """Load the configured constituents and return the sample for the window."""
    path = resolve_data_path(config, config.data.constituents_csv)
    frame = load_constituents(path)
    return season_sample(config, frame, limit=limit)


def exhibit_priority(
    exhibit_type: str, priority: tuple[str, ...] = EXHIBIT_PRIORITY
) -> tuple[int, str]:
    """Return the sort key for one exhibit: position in the priority list, then name.

    Types outside the list sort last but are still ordered deterministically, so a
    filing whose only exhibit is unusual is not silently dropped.
    """
    label = str(exhibit_type).strip().upper()
    try:
        rank = priority.index(label)
    except ValueError:
        rank = len(priority)
    return rank, label


def season_of_filing(value: date) -> tuple[int, int]:
    """Return the calendar (year, quarter) a filing date falls in."""
    return value.year, (value.month - 1) // 3 + 1


def select_filings(
    items: Sequence[T],
    priority: tuple[str, ...] = EXHIBIT_PRIORITY,
    wanted_seasons: Sequence[str] | None = None,
) -> tuple[list[T], dict[str, int]]:
    """Return one exhibit per filing and one filing per season, newest season first.

    A filing publishes the release and often a supplement, and a company files every
    quarter; taking the newest N documents per company therefore spends the whole cap
    on one or two quarters. Selection runs in two steps, each recorded as a skip:

    1. Within one accession, keep the highest-priority exhibit.
    2. Across accessions, keep one per (year, quarter), newest first, so a cap applied
       afterwards truncates seasons rather than exhibits of the same release.

    With `wanted_seasons`, only those seasons are kept, newest first: a company can
    file more quarters than the sample asked for, and taking them anyway changes what
    the run measured. The caller applies its per-company cap after this, so the cap
    counts seasons.
    """
    if not items:
        return [], {}
    skips: dict[str, int] = {}
    best_by_accession: dict[str, T] = {}
    for item in items:
        existing = best_by_accession.get(item.accession)
        if existing is None:
            best_by_accession[item.accession] = item
            continue
        skips['duplicate_exhibit'] = skips.get('duplicate_exhibit', 0) + 1
        if exhibit_priority(item.exhibit_type, priority) < exhibit_priority(
            existing.exhibit_type, priority
        ):
            best_by_accession[item.accession] = item
    ordered = sorted(best_by_accession.values(), key=lambda item: item.filing_date, reverse=True)
    wanted = set(wanted_seasons) if wanted_seasons else None
    seen: set[tuple[int, int]] = set()
    kept: list[T] = []
    for item in ordered:
        season = season_of_filing(item.filing_date)
        season_name = f'{season[0]}Q{season[1]}'
        if wanted is not None and season_name not in wanted:
            skips['season_not_sampled'] = skips.get('season_not_sampled', 0) + 1
            continue
        if season in seen:
            skips['duplicate_season'] = skips.get('duplicate_season', 0) + 1
            continue
        seen.add(season)
        kept.append(item)
    return kept, skips
