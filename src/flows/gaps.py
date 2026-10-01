"""Source gaps: business days on which funds present on both sides are absent from CVM's final
file. 13–16 January 2026 is one (49 classes, R$1.67 trillion). A strict "absent today, present
yesterday and tomorrow" rule misses a hole several days wide, so presence is looked for within a
window of business days on each side."""

from __future__ import annotations

import numpy as np
import pandas as pd

from flows import calendar

WINDOW, SHARE = 5, 0.01


def detect(daily: pd.DataFrame, window: int = WINDOW, share: float = SHARE) -> pd.DataFrame:
    """One row per business day with rows: funds absent that day but present within `window`
    business days before and after, and the share of the day's net assets they held (at their
    last appearance before the day). `gap` marks days where that share exceeds `share`."""
    f = daily[["cnpj", "sub", "dt", "pl"]].copy()
    f["dt"] = pd.to_datetime(f["dt"])
    f = f[[calendar.is_business_day(t.date()) for t in f["dt"]]]
    days = np.array(sorted(f["dt"].unique()))
    day_index = {t: i for i, t in enumerate(days)}
    key = f["cnpj"].astype(str) + "|" + f["sub"].astype(str)
    codes, uniques = pd.factorize(key)
    n_keys, n_days = len(uniques), len(days)
    present = np.zeros((n_keys, n_days), dtype=bool)
    pl = np.full((n_keys, n_days), np.nan, dtype="float32")
    cols = f["dt"].map(day_index).to_numpy()
    present[codes, cols] = True
    pl[codes, cols] = f["pl"].fillna(0).to_numpy(dtype="float32")

    # Forward-filled net assets: what each fund last reported on or before each day.
    last_pl = pl.copy()
    for j in range(1, n_days):
        hole = np.isnan(last_pl[:, j])
        last_pl[hole, j] = last_pl[hole, j - 1]

    out = []
    for j in range(n_days):
        before = present[:, max(0, j - window):j].any(axis=1) if j > 0 else np.zeros(n_keys, bool)
        after = present[:, j + 1:j + 1 + window].any(axis=1) if j + 1 < n_days else np.zeros(n_keys, bool)
        gone = before & after & ~present[:, j]
        total = float(np.nansum(pl[present[:, j], j]))
        missing_pl = float(np.nansum(last_pl[gone, j]))
        s = missing_pl / total if total > 0 else 0.0
        out.append({"dt": pd.Timestamp(days[j]).date(), "n_present": int(present[:, j].sum()),
                    "n_gone": int(gone.sum()), "missing_pl": missing_pl, "pl_share": s,
                    "gap": s > share})
    return pd.DataFrame(out)
