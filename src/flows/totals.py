"""Industry totals by segment and day, from fund-day rows and the register.

    all                 every class in the daily report
    direct              every class that is not a fund of funds: money a fund of funds puts into
                        another fund is in that fund's flows, so this counts each flow once (the
                        headline); a class whose register entry does not say is counted here
    direct:<category>   direct classes of one CVM category (register.CATEGORIES, Unclassified)

A segment-day is hidden when fewer than MIN_FUNDS classes reported or one class holds more than
MAX_SHARE of its gross flow, so that no fund's own figures can be read off a total.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine

from flows import db, register
from flows.sources import KEY, VALUES

MIN_FUNDS, MAX_SHARE = 10, 0.5
MEASURES = ["pl", "captc", "resg", "cotst"]


def segments() -> list[str]:
    return ["all", "direct"] + [f"direct:{c}" for c in register.CATEGORIES
                                + [register.UNCLASSIFIED]]


def _segmented(frame: pd.DataFrame, classes: pd.DataFrame):
    """The frame with gross flow, and a row mask for each segment."""
    known = classes[["cnpj", "category", "fic"]].astype({"cnpj": "int64"})
    f = frame.merge(known, on="cnpj", how="left")
    f["category"] = f["category"].fillna(register.UNCLASSIFIED)
    f["gross"] = f["captc"].fillna(0) + f["resg"].fillna(0)
    direct = f["fic"].fillna(0) != 1
    masks = {"all": pd.Series(True, index=f.index), "direct": direct}
    for c in register.CATEGORIES + [register.UNCLASSIFIED]:
        masks[f"direct:{c}"] = direct & (f["category"] == c)
    return f, masks


def monthly_totals(frame: pd.DataFrame, classes: pd.DataFrame) -> pd.DataFrame:
    """One row per month and segment: classes reported, flows, and the largest class's share of
    the month's gross flow, which decides whether a month's figure may be shown."""
    f, masks = _segmented(frame, classes)
    f["month"] = pd.to_datetime(f["dt"]).dt.strftime("%Y-%m")
    parts = []
    for name, mask in masks.items():
        part = f[mask]
        per_fund = part.groupby(["month", "cnpj", "sub"])["gross"].sum()
        g = part.groupby("month")
        out = g[["captc", "resg"]].sum()
        out["n"] = per_fund.groupby(level="month").size()
        gross = per_fund.groupby(level="month").sum()
        out["top_share"] = (per_fund.groupby(level="month").max() / gross).where(gross > 0, 0.0)
        parts.append(out.reset_index().assign(segment=name))
    out = pd.concat(parts, ignore_index=True)
    out["shown"] = ((out["n"] >= MIN_FUNDS) & (out["top_share"] <= MAX_SHARE)).astype(int)
    return out[["month", "segment", "n", "captc", "resg", "top_share", "shown"]]


def daily_totals(frame: pd.DataFrame, classes: pd.DataFrame) -> pd.DataFrame:
    """One row per day and segment: classes reported, the four sums, the largest class's share
    of gross flow, and whether the row may be shown."""
    f, masks = _segmented(frame, classes)
    parts = []
    for name, mask in masks.items():
        g = f[mask].groupby("dt")
        part = g[MEASURES].sum()
        part["n"] = g.size()
        gross = g["gross"].sum()
        part["top_share"] = (g["gross"].max() / gross).where(gross > 0, 0.0)
        parts.append(part.reset_index().assign(segment=name))
    out = pd.concat(parts, ignore_index=True)
    out["shown"] = ((out["n"] >= MIN_FUNDS) & (out["top_share"] <= MAX_SHARE)).astype(int)
    return out[["dt", "segment", "n", *MEASURES, "top_share", "shown"]]


def _insert(conn, table, rows: pd.DataFrame) -> None:
    for start in range(0, len(rows), 20_000):
        part = rows.iloc[start:start + 20_000]
        conn.execute(table.insert(), part.astype(object).where(part.notna(), None).to_dict("records"))


def store(eng: Engine, frame: pd.DataFrame, classes: pd.DataFrame, first: date,
          last: date) -> None:
    """Replace the stored daily and monthly totals of the days from `first` to `last` (whole
    months) with those of `frame`, the fund-days of those days."""
    stamp = db.utcnow()
    months = [m.strftime("%Y-%m") for m in pd.period_range(first, last, freq="M")]
    with eng.begin() as conn:
        conn.execute(db.daily_totals.delete().where(db.daily_totals.c.dt.between(first, last)))
        conn.execute(db.monthly_totals.delete().where(db.monthly_totals.c.month.in_(months)))
        _insert(conn, db.daily_totals, daily_totals(frame, classes).assign(updated_at=stamp))
        _insert(conn, db.monthly_totals, monthly_totals(frame, classes).assign(updated_at=stamp))


def from_fund_days(eng: Engine, first: date, last: date) -> pd.DataFrame:
    """The latest values of every fund-day collected live between two days."""
    cols = KEY + VALUES
    with eng.connect() as conn:
        rows = conn.execute(select(*[db.fund_days.c[c] for c in cols])
                            .where(db.fund_days.c.dt.between(first, last))).all()
    return pd.DataFrame(rows, columns=cols).astype({"cnpj": "int64"})


def refresh_live(eng: Engine, first: date, last: date) -> str:
    frame = from_fund_days(eng, first, last)
    if frame.empty:
        return f"totals {first}..{last}: no fund-days"
    store(eng, frame, register.load(eng), first, last)
    return f"totals {first}..{last}: {frame['dt'].nunique()} days"
