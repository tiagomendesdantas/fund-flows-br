"""Brazilian business days: weekdays that are not national holidays, Carnival Monday and Tuesday
or Corpus Christi (the calendar of the sibling grid-forecast-br). Checked against the days CVM's
daily report actually has rows for (DATA.md)."""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
from dateutil.easter import easter


@lru_cache(maxsize=32)
def holidays(year: int) -> frozenset[date]:
    e = easter(year)
    fixed = [date(year, 1, 1), date(year, 4, 21), date(year, 5, 1), date(year, 9, 7),
             date(year, 10, 12), date(year, 11, 2), date(year, 11, 15), date(year, 12, 25)]
    if year >= 2024:
        fixed.append(date(year, 11, 20))  # Consciência Negra, national since 2024
    moving = [e - timedelta(days=48), e - timedelta(days=47), e - timedelta(days=2),
              e + timedelta(days=60)]
    return frozenset(fixed + moving)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def business_days(first: date, last: date) -> list[date]:
    """Business days from `first` to `last`, both included."""
    return [d.date() for d in pd.date_range(first, last) if is_business_day(d.date())]


@lru_cache(maxsize=1)
def _index() -> np.ndarray:
    return np.array(business_days(date(2000, 1, 1), date(2035, 12, 31)), dtype="datetime64[D]")


def _count_upto(d: date) -> int:
    """Business days on or before `d` since 2000."""
    return int(np.searchsorted(_index(), np.datetime64(d, "D"), side="right"))


def lag(competence: date, when: date) -> int:
    """Business days after the competence day, up to and including `when` (local dates): a report
    for Monday read on Tuesday is at lag 1."""
    if when <= competence:
        return 0
    return _count_upto(when) - _count_upto(competence)


def shift(d: date, k: int) -> date:
    """The k-th business day after `d` (k < 0: before). A non-business `d` counts from the last
    business day before it, so shift(Saturday, 1) is Monday."""
    idx = _count_upto(d) - 1 + k
    return _index()[idx].astype("datetime64[D]").astype(object)
