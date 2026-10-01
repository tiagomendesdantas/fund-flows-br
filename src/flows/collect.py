"""Collection: every new version of the current and the previous month's daily report and
delivery log, written as a release, and a check that the delivery log explains each release.

    files   the daily report (M-1, M), the delivery log (M-1, M), then the check
"""

from __future__ import annotations

import traceback
from datetime import date

import pandas as pd
from sqlalchemy import and_, bindparam, func, select
from sqlalchemy.engine import Connection, Engine

from flows import db, register, sources, totals
from flows.sources import KEY, LOCAL_OFFSET, VALUES

CHUNK = 20_000
# Delivered as daily reports but absent from the daily report file (checked 2026-10-01).
NOT_IN_DAILY_FILE = {"CLASSES FIIM"}


def local_today(now: pd.Timestamp) -> date:
    return (now - LOCAL_OFFSET).date()


def months(now: pd.Timestamp) -> list[str]:
    """The previous and the current local month, the two CVM rewrites every morning."""
    first = pd.Timestamp(local_today(now)).replace(day=1)
    return [f"{first - pd.DateOffset(months=1):%Y%m}", f"{first:%Y%m}"]


def _download(eng: Engine, dataset: str, month: str, url: str):
    """The file if CVM published a new version since the last release, else a note."""
    target = f"{dataset}:{month}"
    last = db.last_release(eng, dataset, month)
    got = sources.get(url, etag=last["etag"] if last else None)
    if got.status == 304 or (got.status == 200 and last and last["sha256"] == got.sha256):
        db.log_fetch(eng, source="cvm", target=target, status="unchanged", etag=got.etag)
        return None, last, f"{target}: unchanged"
    if got.status == 404:
        db.log_fetch(eng, source="cvm", target=target, status="missing")
        return None, last, f"{target}: not published yet"
    if got.status != 200:
        db.log_fetch(eng, source="cvm", target=target, status="error", detail=f"HTTP {got.status}")
        return None, last, f"{target}: HTTP {got.status}"
    return got, last, ""


def _latest_release(eng: Engine, dataset: str) -> int | None:
    with eng.connect() as conn:
        return conn.execute(select(func.max(db.releases.c.id))
                            .where(db.releases.c.dataset == dataset)).scalar()


def _new_release(conn: Connection, dataset: str, month: str, got, rows: int, bootstrap: bool) -> int:
    return conn.execute(db.releases.insert().values(
        dataset=dataset, month=month, etag=got.etag, last_modified=got.last_modified,
        fetched_at=db.utcnow(), sha256=got.sha256, rows=rows, bootstrap=int(bootstrap))
    ).inserted_primary_key[0]


def _existing(conn: Connection, table, cols: list[str], lo: date, hi: date) -> pd.DataFrame:
    rows = conn.execute(select(*[table.c[c] for c in KEY + cols])
                        .where(table.c.dt.between(lo, hi))).all()
    frame = pd.DataFrame(rows, columns=KEY + cols)
    return frame.astype({"cnpj": "int64", "sub": str})


def _records(frame: pd.DataFrame) -> list[dict]:
    return frame.astype(object).where(frame.notna(), None).to_dict("records")


def _insert(conn: Connection, table, frame: pd.DataFrame) -> None:
    for start in range(0, len(frame), CHUNK):
        conn.execute(table.insert(), _records(frame.iloc[start:start + CHUNK]))


def _differs(new: pd.DataFrame, old: pd.DataFrame) -> pd.Series:
    """Rows whose values changed; two missing values are equal."""
    old = old.set_axis(new.columns, axis=1)
    return ~(new.eq(old) | (new.isna() & old.isna())).all(axis=1)


def _update(conn: Connection, table, frame: pd.DataFrame, cols: list[str], **extra) -> None:
    """Set `cols` from `frame` on the rows with its primary keys (and any `extra` values)."""
    keys = [c.name for c in table.primary_key.columns]
    statement = table.update().where(and_(*[table.c[k] == bindparam(f"k_{k}") for k in keys])
                                     ).values(**{v: bindparam(f"v_{v}") for v in cols}, **extra)
    params = frame[keys + cols].rename(columns={**{k: f"k_{k}" for k in keys},
                                                **{v: f"v_{v}" for v in cols}})
    for start in range(0, len(params), CHUNK):
        conn.execute(statement, _records(params.iloc[start:start + CHUNK]))


def _bootstrap(eng: Engine, month: str, now: pd.Timestamp) -> bool:
    """A month first read after it began to be published before collection started: its values
    are not first-published ones."""
    with eng.connect() as conn:
        began = conn.execute(select(func.min(db.releases.c.fetched_at))
                             .where(db.releases.c.dataset == "daily")).scalar()
    began = pd.Timestamp(began) if began is not None else now
    return pd.Timestamp(f"{month}01") < pd.Timestamp(local_today(began))


def ingest_daily(eng: Engine, month: str, now: pd.Timestamp) -> str:
    got, last, note = _download(eng, "daily", month, sources.daily_url(month))
    if got is None:
        return note
    frame = sources.parse_daily(got.content)
    bootstrap = last is None and _bootstrap(eng, month, now)
    old_cols = [f"old_{c}" for c in VALUES]
    with eng.begin() as conn:
        rid = _new_release(conn, "daily", month, got, len(frame), bootstrap)
        existing = _existing(conn, db.fund_days, VALUES, frame["dt"].min(), frame["dt"].max())
        existing = existing.rename(columns=dict(zip(VALUES, old_cols, strict=True)))
        merged = frame.merge(existing, on=KEY, how="left", indicator=True)
        new = merged[merged["_merge"] == "left_only"]
        both = merged[merged["_merge"] == "both"].reset_index(drop=True)
        changed = both[_differs(both[VALUES], both[old_cols])]

        rows = new[KEY + ["kind"] + VALUES].copy()
        for c in VALUES:
            rows[f"first_{c}"] = rows[c]
        rows = rows.assign(first_release=rid, last_release=rid, revisions=0)
        _insert(conn, db.fund_days, rows)
        _insert(conn, db.fund_day_changes, changed[KEY + old_cols].assign(release_id=rid))
        if len(changed):
            _update(conn, db.fund_days, changed, VALUES + ["kind"], last_release=rid,
                    revisions=db.fund_days.c.revisions + 1)

        days = frame.groupby("dt").agg(n=("cnpj", "size"), pl=("pl", "sum"),
                                       captc=("captc", "sum"), resg=("resg", "sum"),
                                       cotst=("cotst", "sum"))
        days["n_new"] = new.groupby("dt").size()
        days["n_changed"] = changed.groupby("dt").size()
        for c in ("pl", "captc", "resg"):
            days[f"d_{c}"] = (changed[c].fillna(0) - changed[f"old_{c}"].fillna(0)
                              ).groupby(changed["dt"]).sum()
        days = days.fillna({"n_new": 0, "n_changed": 0, "d_pl": 0, "d_captc": 0, "d_resg": 0})
        days = days.astype({"n_new": int, "n_changed": int}).reset_index()
        _insert(conn, db.release_days, days.assign(release_id=rid))
    db.log_fetch(eng, source="cvm", target=f"daily:{month}", status="ok", etag=got.etag,
                 sha256=got.sha256, rows=len(frame), new=len(new), changed=len(changed))
    latest = frame["dt"].max()
    return (f"daily:{month}: {len(frame)} rows, {len(new)} new, {len(changed)} revised"
            f"{' (bootstrap)' if bootstrap else ''}; latest day {latest} has "
            f"{int((frame['dt'] == latest).sum())}")


def ingest_deliveries(eng: Engine, month: str) -> str:
    """The delivery log in one month's file, kept by file month and brought in line with the
    newest version of that file."""
    got, _, note = _download(eng, "deliveries", month, sources.deliveries_url(month))
    if got is None:
        return note
    frame = sources.parse_deliveries(got.content).assign(month=month)
    cols = ["kind", "first_at", "last_at", "n_resub", "active"]
    with eng.begin() as conn:
        _new_release(conn, "deliveries", month, got, len(frame), False)
        rows = conn.execute(select(*[db.deliveries.c[c] for c in KEY + cols])
                            .where(db.deliveries.c.month == month)).all()
        existing = pd.DataFrame(rows, columns=KEY + cols).astype({"cnpj": "int64", "sub": str})
        existing = existing.rename(columns={c: f"old_{c}" for c in cols})
        merged = frame.merge(existing, on=KEY, how="outer", indicator=True)
        new = merged[merged["_merge"] == "left_only"]
        gone = merged[merged["_merge"] == "right_only"]
        both = merged[merged["_merge"] == "both"]
        changed = both[_differs(both[cols], both[[f"old_{c}" for c in cols]])]
        _insert(conn, db.deliveries, new[KEY + ["month"] + cols])
        if len(changed):
            _update(conn, db.deliveries, changed, cols)
        for start in range(0, len(gone), CHUNK):
            part = gone.iloc[start:start + CHUNK]
            conn.execute(db.deliveries.delete().where(and_(
                db.deliveries.c.month == month,
                db.deliveries.c.cnpj == bindparam("k_cnpj"),
                db.deliveries.c.sub == bindparam("k_sub"), db.deliveries.c.dt == bindparam("k_dt"))),
                [{"k_cnpj": int(r.cnpj), "k_sub": r.sub, "k_dt": r.dt} for r in part.itertuples()])
    db.log_fetch(eng, source="cvm", target=f"deliveries:{month}", status="ok", etag=got.etag,
                 sha256=got.sha256, rows=len(frame), new=len(new), changed=len(changed))
    return (f"deliveries:{month}: {len(frame)} fund-days, {len(new)} new, {len(changed)} changed"
            f"{f', {len(gone)} gone' if len(gone) else ''}")


def check_releases(eng: Engine) -> list[str]:
    """For each month's latest daily release not yet checked, once the delivery log has been
    rewritten after it: fund-days first delivered before the release was written and still
    active, by day, against the fund-days it holds."""
    notes = []
    with eng.connect() as conn:
        latest = conn.execute(select(db.releases).where(db.releases.c.id.in_(
            select(func.max(db.releases.c.id)).where(db.releases.c.dataset == "daily")
            .group_by(db.releases.c.month)))).mappings().all()
        log_written = conn.execute(select(func.min(db.releases.c.last_modified)).where(
            db.releases.c.id.in_(select(func.max(db.releases.c.id))
                                 .where(db.releases.c.dataset == "deliveries")
                                 .group_by(db.releases.c.month)))).scalar()
        done = {r for (r,) in conn.execute(select(db.release_checks.c.release_id).distinct())}
    for rel in latest:
        if rel["id"] in done or rel["last_modified"] is None or log_written is None \
                or log_written < rel["last_modified"]:
            continue
        with eng.begin() as conn:
            published = dict(conn.execute(select(db.release_days.c.dt, db.release_days.c.n)
                                          .where(db.release_days.c.release_id == rel["id"])).all())
            lo, hi = min(published), max(published)
            rows = conn.execute(select(db.deliveries.c.cnpj, db.deliveries.c.sub,
                                       db.deliveries.c.dt, db.deliveries.c.kind,
                                       db.deliveries.c.first_at, db.deliveries.c.active)
                                .where(db.deliveries.c.dt.between(lo, hi))).all()
            log = pd.DataFrame(rows, columns=KEY + ["kind", "first_at", "active"])
            log = log[~log["kind"].isin(NOT_IN_DAILY_FILE)]
            fund = log.groupby(KEY).agg(first_at=("first_at", "min"), active=("active", "max"))
            cutoff = pd.Timestamp(rel["last_modified"])
            present = fund[(fund["first_at"] < cutoff) & (fund["active"] == 1)]
            rebuilt = present.reset_index().groupby("dt").size()
            checked = db.utcnow()
            conn.execute(db.release_checks.insert(), [
                {"release_id": rel["id"], "dt": d, "published": n,
                 "rebuilt": int(rebuilt.get(d, 0)), "checked_at": checked}
                for d, n in published.items()])
        off = [d for d, n in published.items() if int(rebuilt.get(d, 0)) != n]
        notes.append(f"check daily:{rel['month']}: {len(published)} days, "
                     + ("all equal" if not off else f"{len(off)} differ (first {min(off)})"))
    return notes


def collect_files(eng: Engine, now: pd.Timestamp | None = None) -> list[str]:
    now = now or pd.Timestamp(db.utcnow())
    notes = register.refresh(eng) if register.load(eng).empty else []
    before = _latest_release(eng, "daily")
    notes += [ingest_daily(eng, m, now) for m in months(now)]
    notes += [ingest_deliveries(eng, m) for m in months(now)]
    first = pd.Timestamp(f"{months(now)[0]}01").date()
    with eng.connect() as conn:
        have = conn.execute(select(func.count()).select_from(db.daily_totals)
                            .where(db.daily_totals.c.dt >= first)).scalar()
    if _latest_release(eng, "daily") != before or not have:     # a new version, or none yet
        notes.append(totals.refresh_live(eng, first, local_today(now)))
    return notes + check_releases(eng)


HISTORY_FROM = "202101"


def collect_history(eng: Engine, now: pd.Timestamp | None = None) -> list[str]:
    """Totals for every month before the two collected live, from CVM's monthly files: read
    once, then again only when CVM rewrites a file (months M-2 to M-11 weekly)."""
    now = now or pd.Timestamp(db.utcnow())
    if register.load(eng).empty:
        register.refresh(eng)
    classes = register.load(eng)
    last = pd.Period(months(now)[0], "M") - 1
    read, notes = 0, []
    for period in pd.period_range(pd.Period(HISTORY_FROM, "M"), last, freq="M"):
        month = period.strftime("%Y%m")
        got, _, note = _download(eng, "history", month, sources.daily_url(month))
        if got is None:
            if not note.endswith("unchanged"):
                notes.append(note)
            continue
        frame = sources.parse_daily(got.content)
        with eng.begin() as conn:
            _new_release(conn, "history", month, got, len(frame), True)
        totals.store(eng, frame, classes, period.start_time.date(), period.end_time.date())
        db.log_fetch(eng, source="cvm", target=f"history:{month}", status="ok", etag=got.etag,
                     sha256=got.sha256, rows=len(frame))
        read += 1
    return [f"history: {read} months read"] + notes


def collect_register(eng: Engine, now: pd.Timestamp | None = None) -> list[str]:
    return register.refresh(eng)


def run(eng: Engine, job: str, fn, *args) -> str:
    """Run a job with a row in `runs`; failures are recorded, not raised."""
    run_id = db.start_run(eng, job)
    try:
        notes = fn(eng, *args)
        errors = [n for n in notes if "HTTP" in n or "Error" in n or "differ" in n]
        db.finish_run(eng, run_id, "partial" if errors else "ok", "\n".join(notes))
        return "partial" if errors else "ok"
    except Exception:  # noqa: BLE001 - any failure is recorded in `runs` and retried next slot
        db.finish_run(eng, run_id, "failed", traceback.format_exc())
        return "failed"
