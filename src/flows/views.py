"""What the page shows, computed from the database. Industry totals only: no fund is named."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.engine import Engine

from flows import calendar, collect, db, scheduler, totals
from flows.sources import LOCAL_OFFSET

OK_HOURS, LATE_HOURS = 18, 30     # the longest gap between slots is 17 hours (11:10 to 04:10)


def _stamp(ts) -> str | None:
    return None if ts is None else pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M")


def next_slot(now: pd.Timestamp) -> str:
    day = now.normalize()
    slots = [day + pd.Timedelta(hours=h, minutes=m) for h, m in scheduler.FILE_TIMES]
    later = [s for s in slots if s > now] or [slots[0] + pd.Timedelta(days=1)]
    return _stamp(later[0])


def status(eng: Engine, now: pd.Timestamp) -> dict:
    with eng.connect() as conn:
        last_ok = conn.execute(select(func.max(db.runs.c.finished_at)).where(and_(
            db.runs.c.job == "files", db.runs.c.status.in_(["ok", "partial"])))).scalar()
        runs = conn.execute(select(db.runs).order_by(db.runs.c.id.desc()).limit(12)
                            ).mappings().all()
        fetches = conn.execute(select(db.fetches).order_by(db.fetches.c.id.desc()).limit(16)
                               ).mappings().all()
        releases = conn.execute(select(db.releases).order_by(db.releases.c.id.desc()).limit(12)
                                ).mappings().all()
        latest = conn.execute(select(func.max(db.releases.c.id)).where(
            db.releases.c.dataset == "daily").group_by(db.releases.c.month)).scalars().all()
        days = conn.execute(
            select(db.release_days, db.releases.c.month, db.release_checks.c.rebuilt)
            .join(db.releases, db.releases.c.id == db.release_days.c.release_id)
            .outerjoin(db.release_checks, and_(
                db.release_checks.c.release_id == db.release_days.c.release_id,
                db.release_checks.c.dt == db.release_days.c.dt))
            .where(db.release_days.c.release_id.in_(latest))
            .order_by(db.release_days.c.dt.desc())).mappings().all()
    hours = None if last_ok is None else (now - pd.Timestamp(last_ok)).total_seconds() / 3600
    state = ("failing" if hours is None or hours > LATE_HOURS
             else "late" if hours > OK_HOURS else "ok")
    return {
        "as_of": _stamp(now),
        "collector": {"state": state, "last_success": _stamp(last_ok), "next": next_slot(now)},
        "days": [{"dt": d["dt"].isoformat(), "month": d["month"], "n": d["n"],
                  "n_new": d["n_new"], "n_changed": d["n_changed"], "rebuilt": d["rebuilt"],
                  "captc": d["captc"], "resg": d["resg"], "pl": d["pl"]} for d in days],
        "releases": [{"id": r["id"], "dataset": r["dataset"], "month": r["month"],
                      "written": _stamp(r["last_modified"]), "read": _stamp(r["fetched_at"]),
                      "rows": r["rows"], "bootstrap": bool(r["bootstrap"])} for r in releases],
        "fetches": [{"at": _stamp(f["fetched_at"]), "target": f["target"], "status": f["status"],
                     "rows": f["rows"], "new": f["new"], "changed": f["changed"]}
                    for f in fetches],
        "runs": [{"job": r["job"], "started": _stamp(r["started_at"]),
                  "finished": _stamp(r["finished_at"]), "status": r["status"],
                  "detail": r["detail"]} for r in runs],
    }


# ---- Totals pages. A day's lag is the number of business days between it and the morning file
# it was last read from: under 1% of fund-days are in at lag 1, 84-94% at lag 2, 98-99.5% by lag 5.
PARTIAL_LAG, ABOUT_COMPLETE_LAG = 2, 5
FLOWS = ["pl", "captc", "resg", "cotst"]


def file_day(eng: Engine) -> date | None:
    """The local day of the latest daily file read."""
    with eng.connect() as conn:
        written = conn.execute(select(func.max(db.releases.c.last_modified)).where(
            db.releases.c.dataset == "daily")).scalar()
    return None if written is None else (pd.Timestamp(written) - LOCAL_OFFSET).date()


def _totals(eng: Engine, segments: list[str], first: date | None = None) -> pd.DataFrame:
    q = select(db.daily_totals).where(db.daily_totals.c.segment.in_(segments))
    if first is not None:
        q = q.where(db.daily_totals.c.dt >= first)
    with eng.connect() as conn:
        rows = conn.execute(q.order_by(db.daily_totals.c.dt)).mappings().all()
    cols = ["dt", "segment", "n", *FLOWS, "top_share", "shown"]
    return pd.DataFrame(rows, columns=cols + ["updated_at"])[cols]


def _with_lag(frame: pd.DataFrame, latest: date | None) -> pd.DataFrame:
    lags = {d: calendar.lag(d, latest) if latest else 99 for d in frame["dt"].unique()}
    return frame.assign(lag=frame["dt"].map(lags))


def completeness(eng: Engine, latest: date | None, days: int = 15) -> list[dict]:
    """The latest business days: classes reported so far against the usual count (the median of
    the about-complete days among the previous 30)."""
    if latest is None:
        return []
    t = _with_lag(_totals(eng, ["all"], latest - timedelta(days=60)), latest)
    done = t[t["lag"] > ABOUT_COMPLETE_LAG].tail(30)
    usual = float(done["n"].median()) if len(done) else None
    out = []
    for r in t[t["lag"] >= 1].tail(days).itertuples():
        out.append({"dt": r.dt.isoformat(), "lag": int(r.lag), "n": int(r.n), "usual": usual,
                    "share": None if not usual else round(min(r.n / usual, 1.0), 4)})
    return out[::-1]


def _monthly_shown(eng: Engine, segments: list[str]) -> dict[tuple[str, str], bool]:
    """Whether each month's figure may be shown (flows.totals.monthly_totals)."""
    with eng.connect() as conn:
        rows = conn.execute(select(db.monthly_totals.c.month, db.monthly_totals.c.segment,
                                   db.monthly_totals.c.shown)
                            .where(db.monthly_totals.c.segment.in_(segments))).all()
    return {(m, s): bool(v) for m, s, v in rows}


def _month_rows(t: pd.DataFrame, shown: bool) -> dict:
    """Flows summed over the days given; net assets and quota holders on the latest
    about-complete day (the latest day when none is)."""
    if t.empty:
        return {}
    done = t[t["lag"] > ABOUT_COMPLETE_LAG]
    end = (done if len(done) else t)["dt"].max()
    last = t[t["dt"] == end]
    return {"captc": float(t["captc"].sum()), "resg": float(t["resg"].sum()),
            "net": float((t["captc"] - t["resg"]).sum()),
            "days": int(t["dt"].map(calendar.is_business_day).sum()),
            "pl_end": float(last["pl"].sum()), "cotst_end": float(last["cotst"].sum()),
            "end": end.isoformat(), "shown": shown, "through": t["dt"].max().isoformat()}


def overview(eng: Engine, now: pd.Timestamp) -> dict:
    latest = file_day(eng)
    month_start = pd.Timestamp(collect.local_today(now)).replace(day=1).date()
    prev_start = (pd.Timestamp(month_start) - pd.DateOffset(months=1)).date()
    segs = totals.segments()
    t = _with_lag(_totals(eng, segs, prev_start - timedelta(days=45)), latest)
    usable = t[t["lag"] >= PARTIAL_LAG]
    direct = usable[usable["segment"] == "direct"]
    done = direct[direct["lag"] > ABOUT_COMPLETE_LAG]
    recent = direct[(direct["dt"] >= (latest or month_start) - timedelta(days=45))
                    & (direct["shown"] == 1) & direct["dt"].map(calendar.is_business_day)]

    shown = _monthly_shown(eng, segs)

    def by_segment(part: pd.DataFrame, month: str) -> list[dict]:
        rows = []
        for seg in segs:
            row = _month_rows(part[part["segment"] == seg], shown.get((month, seg), False))
            if row:
                rows.append({"segment": seg, **row})
        return rows

    this_month = usable[usable["dt"] >= month_start]
    last_month = usable[(usable["dt"] >= prev_start) & (usable["dt"] < month_start)]
    return {
        "as_of": _stamp(now), "file_day": latest.isoformat() if latest else None,
        "collector": status(eng, now)["collector"],
        "assets": None if done.empty else {
            "dt": done["dt"].max().isoformat(),
            "pl": float(done[done["dt"] == done["dt"].max()]["pl"].iloc[0]),
            "cotst": float(done[done["dt"] == done["dt"].max()]["cotst"].iloc[0])},
        "this_month": {"month": month_start.strftime("%Y-%m"), "segments": by_segment(this_month, month_start.strftime("%Y-%m")),
                       "partial_days": int((this_month["segment"].eq("direct")
                                            & this_month["lag"].le(ABOUT_COMPLETE_LAG)).sum())},
        "last_month": {"month": prev_start.strftime("%Y-%m"), "segments": by_segment(last_month, prev_start.strftime("%Y-%m")),
                       "partial_days": int((last_month["segment"].eq("direct")
                                            & last_month["lag"].le(ABOUT_COMPLETE_LAG)).sum())},
        "daily": [{"dt": r.dt.isoformat(), "lag": int(r.lag), "captc": r.captc, "resg": r.resg,
                   "net": r.captc - r.resg, "n": int(r.n)} for r in recent.itertuples()],
        "completeness": completeness(eng, latest, days=6),
    }


def flows(eng: Engine, segment: str) -> dict:
    latest = file_day(eng)
    t = _with_lag(_totals(eng, [segment]), latest)
    t = t[t["lag"] >= PARTIAL_LAG]
    t["month"] = pd.to_datetime(t["dt"]).dt.strftime("%Y-%m")
    shown = _monthly_shown(eng, [segment])
    months = [{"month": month, **_month_rows(part, True),
               "partial": bool((part["lag"] <= ABOUT_COMPLETE_LAG).any())}
              for month, part in t.groupby("month") if shown.get((month, segment), False)]
    business = t["dt"].map(calendar.is_business_day)
    hidden = int(((t["shown"] == 0) & business).sum())
    t = t[(t["shown"] == 1) & business]     # holidays carry a handful of rows
    return {"segment": segment, "file_day": latest.isoformat() if latest else None,
            "hidden_days": hidden,
            "daily": [[r.dt.isoformat(), r.captc, r.resg, r.pl, r.cotst, int(r.lag)]
                      for r in t.itertuples()],
            "columns": ["dt", "captc", "resg", "pl", "cotst", "lag"], "months": months}


def reporting(eng: Engine, now: pd.Timestamp) -> dict:
    latest = file_day(eng)
    with eng.connect() as conn:
        rel = conn.execute(select(db.releases).where(db.releases.c.dataset == "daily")
                           .order_by(db.releases.c.id.desc()).limit(12)).mappings().all()
        days = conn.execute(select(db.release_days.c.release_id,
                                   func.sum(db.release_days.c.n_new),
                                   func.sum(db.release_days.c.n_changed),
                                   func.sum(db.release_days.c.d_captc),
                                   func.sum(db.release_days.c.d_resg))
                            .where(db.release_days.c.release_id.in_([r["id"] for r in rel]))
                            .group_by(db.release_days.c.release_id)).all()
    sums = {r[0]: r[1:] for r in days}
    return {"file_day": latest.isoformat() if latest else None,
            "completeness": completeness(eng, latest),
            "releases": [{"month": r["month"], "written": _stamp(r["last_modified"]),
                          "bootstrap": bool(r["bootstrap"]),
                          "new": int(sums.get(r["id"], (0,) * 4)[0] or 0),
                          "changed": int(sums.get(r["id"], (0,) * 4)[1] or 0),
                          "d_captc": float(sums.get(r["id"], (0,) * 4)[2] or 0),
                          "d_resg": float(sums.get(r["id"], (0,) * 4)[3] or 0)} for r in rel]}


def totals_csv(eng: Engine) -> str:
    """Every shown daily total, for the ODbL download."""
    t = _totals(eng, totals.segments())
    t = t[t["shown"] == 1].drop(columns=["shown", "top_share"])
    return t.to_csv(index=False, float_format="%.2f")
