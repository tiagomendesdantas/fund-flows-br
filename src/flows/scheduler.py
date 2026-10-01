"""In-process scheduler for the web service: one background thread, one job at a time.

    files   at 04:10, 05:10, 07:10 and 11:10 UTC: CVM rewrote the files at about 03:52 (daily
            report) and 04:46 (delivery log) on the days checked; the later slots catch late or
            repeated rewrites. A slot with nothing new costs two conditional requests per file.

On Postgres a session advisory lock keeps two replicas from running the same job; each slot runs
at most once (the `runs` table is the record). A job that fails is recorded and retried at the
next slot; the thread never dies on an exception.
"""

from __future__ import annotations

import logging
import threading
import time

import pandas as pd
from sqlalchemy import text

from flows import collect, db

log = logging.getLogger("flows.scheduler")
FILE_TIMES = ((4, 10), (5, 10), (7, 10), (11, 10))
LOCK_ID = 20261001
JOBS = {"files": collect.collect_files}


def due(now: pd.Timestamp, last: dict[str, pd.Timestamp]) -> list[str]:
    slot = now.floor("min")
    if (slot.hour, slot.minute) in FILE_TIMES and last.get("files") != slot:
        return ["files"]
    return []


def _with_lock(eng, fn) -> bool:
    if eng.dialect.name != "postgresql":
        fn()
        return True
    with eng.connect() as conn:
        got = conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": LOCK_ID}).scalar()
        if not got:
            return False
        try:
            fn()
        finally:
            conn.execute(text("select pg_advisory_unlock(:k)"), {"k": LOCK_ID})
            conn.commit()
    return True


def loop(stop: threading.Event) -> None:
    eng = db.engine()
    last: dict[str, pd.Timestamp] = {}
    # Catch up once at start: a restart should not wait for the next slot.
    _with_lock(eng, lambda: collect.run(eng, "files", JOBS["files"]))
    while not stop.is_set():
        now = pd.Timestamp(db.utcnow())
        for job in due(now, last):
            last[job] = now.floor("min")
            try:
                _with_lock(eng, lambda job=job: collect.run(eng, job, JOBS[job]))
            except Exception:  # the loop must survive anything
                log.exception("scheduler: %s failed", job)
        stop.wait(20)


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=loop, args=(stop,), daemon=True, name="scheduler").start()
    return stop


if __name__ == "__main__":  # run the scheduler alone, e.g. locally
    logging.basicConfig(level=logging.INFO)
    event = start()
    while True:
        time.sleep(3600)
