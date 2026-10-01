"""What the page shows, computed from the database. Industry totals only: no fund is named."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.engine import Engine

from flows import db, scheduler

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
