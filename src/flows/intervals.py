"""Intervals for the estimates: empirical quantiles of the development-period residuals, scaled
by the net assets still missing, by measure and month-end flag, pooled across lags and
categories; fitted once and frozen in models/intervals.json."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

QUANTILES = {"q025": 0.025, "q10": 0.10, "q90": 0.90, "q975": 0.975}
MEASURES = ["captc", "resg", "net"]
PATH = Path(__file__).resolve().parents[2] / "models" / "intervals.json"


def month_end(d) -> bool:
    """The last business day of the month and the two before it."""
    from flows import calendar
    t = pd.Timestamp(d)
    last = t + pd.offsets.MonthEnd(0)
    while not calendar.is_business_day(last.date()):
        last -= pd.Timedelta(days=1)
    return calendar.lag(t.date(), last.date()) <= 2


def calibrate(scored: pd.DataFrame) -> dict:
    """From scored rows of one method (err_<m>, missing_pl, d): quantiles of (truth − estimate) /
    missing_pl per measure and month-end flag. Cells with no missing net assets are skipped."""
    table: dict = {}
    rows = scored[scored["missing_pl"] > 0].copy()
    rows["me"] = [month_end(d) for d in rows["d"]]
    for m in MEASURES:
        for me, part in rows.groupby("me"):
            r = (-part[f"err_{m}"] / part["missing_pl"]).to_numpy()
            table[f"{m}|{'month_end' if me else 'normal'}"] = {
                name: float(np.quantile(r, q)) for name, q in QUANTILES.items()} | {"n": len(r)}
    return table


def apply(estimates: pd.DataFrame, table: dict) -> pd.DataFrame:
    """Add <measure>_<q> columns: estimate + quantile × missing_pl."""
    out = estimates.copy()
    me = np.array([month_end(d) for d in out["d"]])
    for m in MEASURES:
        for name in QUANTILES:
            q_me = table[f"{m}|month_end"][name]
            q_no = table[f"{m}|normal"][name]
            out[f"{m}_{name}"] = out[m] + np.where(me, q_me, q_no) * out["missing_pl"]
    return out


def save(table: dict, path: Path = PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=1))


def load(path: Path = PATH) -> dict:
    return json.loads(path.read_text())
