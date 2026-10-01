"""Storage: every fund-day CVM publishes, as first seen and as it stands now, and every release.

CVM rewrites its monthly files every morning: late reports arrive and earlier reports are
resubmitted. Each version of a file we read is a release. A fund-day keeps its values from the
release it first appeared in and its latest values, and every change is logged, so the totals as
published on any morning can be rebuilt. Values in a bootstrap release (the first read of a month
that had been published before collection began) are not first-published values.

Postgres in production (DATABASE_URL); SQLite for tests and local work.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine

from flows.sources import VALUES

metadata = MetaData()


def _fund_key() -> list[Column]:
    return [Column("cnpj", BigInteger, primary_key=True), Column("sub", String, primary_key=True),
            Column("dt", Date, primary_key=True)]


releases = Table(
    "releases", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dataset", String, nullable=False),          # daily or deliveries
    Column("month", String, nullable=False),            # YYYYMM
    Column("etag", String), Column("last_modified", DateTime),   # naive UTC, as CVM states it
    Column("fetched_at", DateTime, nullable=False),
    Column("sha256", String, nullable=False),
    Column("rows", Integer, nullable=False),
    Column("bootstrap", Integer, nullable=False),       # 1: first read of an already published month
)

fund_days = Table(
    "fund_days", metadata, *_fund_key(),
    Column("kind", String),
    *[Column(c, Float) for c in VALUES],
    *[Column(f"first_{c}", Float) for c in VALUES],
    Column("first_release", Integer, nullable=False),
    Column("last_release", Integer, nullable=False),    # the release that set the current values
    Column("revisions", Integer, nullable=False),
)

fund_day_changes = Table(
    "fund_day_changes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cnpj", BigInteger, nullable=False), Column("sub", String, nullable=False),
    Column("dt", Date, nullable=False),
    Column("release_id", Integer, nullable=False),      # the release that replaced these values
    *[Column(f"old_{c}", Float) for c in VALUES],
)

# Totals of one release by competence day: how many fund-days, the sums as published that
# morning, and what the release added (new fund-days) and changed (resubmissions).
release_days = Table(
    "release_days", metadata,
    Column("release_id", Integer, primary_key=True), Column("dt", Date, primary_key=True),
    Column("n", Integer, nullable=False), Column("n_new", Integer, nullable=False),
    Column("n_changed", Integer, nullable=False),
    *[Column(c, Float) for c in ("pl", "captc", "resg", "cotst")],
    *[Column(f"d_{c}", Float) for c in ("pl", "captc", "resg")],
)

# The delivery log by file month: a fund-day can appear in two months' files.
deliveries = Table(
    "deliveries", metadata, *_fund_key(),
    Column("month", String, primary_key=True),
    Column("kind", String),
    Column("first_at", DateTime, nullable=False),       # first delivery of any kind, naive UTC
    Column("last_at", DateTime, nullable=False),
    Column("n_resub", Integer, nullable=False),
    Column("active", Integer, nullable=False),          # 1: a delivery is still active
)

# Does the delivery log explain the release? Fund-days first delivered before the release was
# written and still active, by competence day, against the fund-days the release holds.
release_checks = Table(
    "release_checks", metadata,
    Column("release_id", Integer, primary_key=True), Column("dt", Date, primary_key=True),
    Column("published", Integer, nullable=False), Column("rebuilt", Integer, nullable=False),
    Column("checked_at", DateTime, nullable=False),
)

fetches = Table(
    "fetches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String, nullable=False),
    Column("target", String, nullable=False),
    Column("fetched_at", DateTime, nullable=False),
    Column("status", String, nullable=False),           # ok, unchanged, missing, error
    Column("etag", String), Column("sha256", String),
    Column("rows", Integer), Column("new", Integer), Column("changed", Integer),
    Column("detail", Text),
)

runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job", String, nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Column("status", String, nullable=False),           # running, ok, partial, failed
    Column("detail", Text),
)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///data/local.db")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@lru_cache(maxsize=4)
def engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        os.makedirs(os.path.dirname(url[len("sqlite:///"):]) or ".", exist_ok=True)
    eng = create_engine(url, pool_pre_ping=True, future=True)
    metadata.create_all(eng)
    return eng


def start_run(eng: Engine, job: str) -> int:
    with eng.begin() as conn:
        return conn.execute(runs.insert().values(job=job, started_at=utcnow(), status="running")
                            ).inserted_primary_key[0]


def finish_run(eng: Engine, run_id: int, status: str, detail: str = "") -> None:
    with eng.begin() as conn:
        conn.execute(runs.update().where(runs.c.id == run_id)
                     .values(finished_at=utcnow(), status=status, detail=detail[:4000]))


def log_fetch(eng: Engine, **values) -> None:
    with eng.begin() as conn:
        conn.execute(fetches.insert().values(fetched_at=utcnow(), **values))


def last_release(eng: Engine, dataset: str, month: str):
    with eng.connect() as conn:
        return conn.execute(select(releases).where(and_(
            releases.c.dataset == dataset, releases.c.month == month))
            .order_by(releases.c.id.desc()).limit(1)).mappings().first()
