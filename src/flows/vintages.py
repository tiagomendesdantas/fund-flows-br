"""What was known on a given morning, rebuilt from the delivery log.

A fund-day is in the file CVM writes on morning m when its first delivery came before the file was
written and a delivery is still active (DATA.md: this reproduces the published file exactly).
`Store` holds fund-day rows with their first delivery time for a span of months; `vintage` gives,
for a competence day d seen from morning m, the fund-days present, the funds expected but missing
with what was last known about them, and the trailing statistics the estimates use. Everything
"known" is taken from rows delivered before the cutoff, never from the final file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from flows import calendar, history
from flows.sources import KEY, LOCAL_OFFSET

CUTOFF = time(0, 52)            # Brasília; CVM wrote its file at 00:52 local on the days checked
NOT_IN_FILE = {"CLASSES FIIM"}   # delivered as daily reports, absent from the published file
LOOKBACK = 10                    # business days: a fund is expected if seen in the last 10
TRAIL = 20                       # business days of history behind the trailing statistics
TRUTH_LAG = 15                   # business days: the truth is the membership at d + 15
FUND = ["cnpj", "sub"]


def cutoff(m: date, at: time = CUTOFF) -> pd.Timestamp:
    """The naive-UTC instant before which a delivery is in the file written on morning m."""
    return pd.Timestamp(datetime.combine(m, at)) + LOCAL_OFFSET


class Store:
    """Fund-day rows (final values) with the first delivery time and active flag of each, for the
    months from `first` to `last` (YYYYMM), non-FIIM."""

    def __init__(self, first: str, last: str):
        months = history.months(first, last)
        daily = pd.concat([history.daily(m) for m in months], ignore_index=True)
        log = pd.concat([history.deliveries(m) for m in months], ignore_index=True)
        log = log.groupby(KEY, as_index=False).agg(first_at=("first_at", "min"),
                                                   active=("active", "max"))
        rows = daily[~daily["kind"].isin(NOT_IN_FILE)].merge(log, on=KEY, how="left")
        rows["dt"] = pd.to_datetime(rows["dt"])
        self.unlogged = int(rows["first_at"].isna().sum())
        self.rows = rows.sort_values(["dt", "cnpj", "sub"]).reset_index(drop=True)
        self.days = sorted(d.date() for d in rows["dt"].unique())

    def known_at(self, m: date, first: date, last: date, at: time = CUTOFF) -> pd.DataFrame:
        """Rows of competence days `first`..`last` that were in the file of morning m."""
        r = self.rows
        mask = ((r["first_at"] < cutoff(m, at)) & (r["active"] == 1)
                & (r["dt"] >= pd.Timestamp(first)) & (r["dt"] <= pd.Timestamp(last)))
        return r[mask]

    def truth(self, d: date, at: time = CUTOFF) -> pd.DataFrame:
        """The fund-days of d in the file written TRUTH_LAG business days after d."""
        return self.known_at(calendar.shift(d, TRUTH_LAG), d, d, at)

    def final(self, d: date) -> pd.DataFrame:
        return self.rows[self.rows["dt"] == pd.Timestamp(d)]


@dataclass
class Vintage:
    d: date
    m: date
    k: int
    present: pd.DataFrame     # fund-days of d in the file of m: KEY, values, kind
    missing: pd.DataFrame     # expected funds not present: cnpj, sub, pl_last, last_dt,
    #                           days_since_seen, trailing captc_rate, resg_rate, zero_share, n_trail
    expected_pl: float        # sum of pl_last over expected funds (present + missing)


def _successors(missing: pd.DataFrame, past: pd.DataFrame, d: date) -> pd.Series:
    """Missing funds that stopped and were followed, the next business day, by a fund not seen
    before with net assets within 0.5%: a CNPJ change, not a late report."""
    gone = pd.Series(False, index=missing.index)
    stopped = missing[missing["last_dt"] < pd.Timestamp(calendar.shift(d, -1))]
    for last_dt, part in stopped.groupby("last_dt"):
        nxt = pd.Timestamp(calendar.shift(last_dt.date(), 1))
        at_last = set(map(tuple, past[past["dt"] == last_dt][FUND].to_numpy()))
        new = past[(past["dt"] == nxt)]
        new = new[[tuple(x) not in at_last for x in new[FUND].to_numpy()]]
        pls = np.sort(new["pl"].dropna().to_numpy())
        if not pls.size:
            continue
        for idx, pl in part["pl_last"].items():
            if pl > 0:
                i = np.searchsorted(pls, pl * 0.995)
                if i < pls.size and pls[i] <= pl * 1.005:
                    gone[idx] = True
    return gone


def vintage(store: Store, d: date, k: int, at: time = CUTOFF) -> Vintage:
    m = calendar.shift(d, k)
    start = calendar.shift(d, -max(LOOKBACK, TRAIL))
    known = store.known_at(m, start, d, at)
    present = known[known["dt"] == pd.Timestamp(d)]
    past = known[known["dt"] < pd.Timestamp(d)]

    seen = past[past["dt"] >= pd.Timestamp(calendar.shift(d, -LOOKBACK))]
    last = (seen.sort_values("dt").groupby(FUND, as_index=False)
            .agg(last_dt=("dt", "last"), pl_last=("pl", "last")))
    present_keys = set(map(tuple, present[FUND].to_numpy()))
    is_present = pd.Series([tuple(x) in present_keys for x in last[FUND].to_numpy()],
                           index=last.index)
    missing = last[~is_present].copy()
    if len(missing):
        missing = missing[~_successors(missing, past, d)]
        missing["days_since_seen"] = [calendar.lag(t.date(), d) for t in missing["last_dt"]]
    else:
        missing["days_since_seen"] = pd.Series(dtype=int)

    trail = past[past["dt"] >= pd.Timestamp(calendar.shift(d, -TRAIL))].copy()
    trail = trail[trail["pl"] > 0]
    trail["captc_rate"] = trail["captc"].fillna(0) / trail["pl"]
    trail["resg_rate"] = trail["resg"].fillna(0) / trail["pl"]
    trail["zero"] = ((trail["captc"].fillna(0) + trail["resg"].fillna(0)) == 0).astype(float)
    stats = trail.groupby(FUND).agg(captc_rate=("captc_rate", "mean"),
                                    resg_rate=("resg_rate", "mean"),
                                    zero_share=("zero", "mean"), n_trail=("dt", "size"))
    missing = missing.merge(stats, on=FUND, how="left")
    missing["n_trail"] = missing["n_trail"].fillna(0).astype(int)
    expected_pl = float(last["pl_last"].fillna(0).sum())
    return Vintage(d, m, k, present.reset_index(drop=True), missing.reset_index(drop=True),
                   expected_pl)
