"""FastAPI app: the status page and its JSON. The collector and the scheduler run in this process
(flows.scheduler)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from flows import db, scheduler, views

WEB = Path(__file__).resolve().parents[2] / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = scheduler.start() if os.getenv("RUN_SCHEDULER", "1") == "1" else None
    yield
    if stop is not None:
        stop.set()


app = FastAPI(title="fund-flows-br", docs_url="/docs", redoc_url=None, lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    with db.engine().connect() as conn:
        last = conn.execute(select(db.runs.c.job, func.max(db.runs.c.finished_at))
                            .where(db.runs.c.status.in_(["ok", "partial"]))
                            .group_by(db.runs.c.job)).all()
    return {"ok": True, "last_success": {job: str(ts) for job, ts in last}}


@app.get("/api/status")
def status() -> dict:
    return views.status(db.engine(), pd.Timestamp(db.utcnow()))


@app.get("/")
def page() -> FileResponse:
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
