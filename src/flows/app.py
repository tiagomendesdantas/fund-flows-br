"""FastAPI app: the pages, their JSON, and the daily totals as an ODbL download. The collector and
the scheduler run in this process (flows.scheduler)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from flows import db, scheduler, totals, views

WEB = Path(__file__).resolve().parents[2] / "web"
PAGES = ("/", "/flows", "/reporting", "/status", "/method")


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = scheduler.start() if os.getenv("RUN_SCHEDULER", "1") == "1" else None
    yield
    if stop is not None:
        stop.set()


app = FastAPI(title="fund-flows-br", docs_url="/docs", redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")


def now() -> pd.Timestamp:
    return pd.Timestamp(db.utcnow())


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    with db.engine().connect() as conn:
        last = conn.execute(select(db.runs.c.job, func.max(db.runs.c.finished_at))
                            .where(db.runs.c.status.in_(["ok", "partial"]))
                            .group_by(db.runs.c.job)).all()
    return {"ok": True, "last_success": {job: str(ts) for job, ts in last}}


@app.get("/api/status")
def status() -> dict:
    return views.status(db.engine(), now())


@app.get("/api/overview")
def overview() -> dict:
    return views.overview(db.engine(), now())


@app.get("/api/flows")
def flows(segment: str = "direct") -> dict:
    if segment not in totals.segments():
        raise HTTPException(400, f"segment must be one of {totals.segments()}")
    return views.flows(db.engine(), segment)


@app.get("/api/reporting")
def reporting() -> dict:
    return views.reporting(db.engine(), now())


@app.get("/data/daily-totals.csv")
def totals_csv() -> Response:
    """Daily totals by group under the ODbL, as the source data (CVM, dados.cvm.gov.br)."""
    return Response(views.totals_csv(db.engine()), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="daily-totals.csv"',
                             "Cache-Control": "max-age=3600"})


def _shell() -> HTMLResponse:
    return HTMLResponse((WEB / "index.html").read_text(), headers={"Cache-Control": "no-cache"})


for _path in PAGES:
    app.add_api_route(_path, _shell, methods=["GET"], include_in_schema=False)
