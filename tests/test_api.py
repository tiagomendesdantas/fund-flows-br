from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from flows import db

CNPJ = re.compile(r"\d{14}")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_SCHEDULER", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api.db")
    db.engine.cache_clear()
    eng = db.engine()
    stamp = db.utcnow()
    days = [date(2026, 9, 1) + timedelta(days=i) for i in range(30)]
    rows = []
    for d in days:
        if d.weekday() >= 5:
            continue
        for seg in ("all", "direct", "direct:Renda Fixa", "direct:Cambial"):
            rows.append({"dt": d, "segment": seg, "n": 5 if seg.endswith("Cambial") else 1000,
                         "pl": 1e12, "captc": 2e10, "resg": 1e10, "cotst": 1e6, "top_share": 0.1,
                         "shown": 0 if seg.endswith("Cambial") else 1, "updated_at": stamp})
    with eng.begin() as conn:
        conn.execute(db.daily_totals.insert(), rows)
        conn.execute(db.monthly_totals.insert(), [
            {"month": "2026-09", "segment": s, "n": 1000, "captc": 1.0, "resg": 0.5,
             "top_share": 0.1, "shown": 0 if s.endswith("Cambial") else 1, "updated_at": stamp}
            for s in ("all", "direct", "direct:Renda Fixa", "direct:Cambial")])
        conn.execute(db.releases.insert().values(
            dataset="daily", month="202609", etag="e", last_modified=db.utcnow(),
            fetched_at=stamp, sha256="x", rows=1, bootstrap=1))
    from flows.app import app
    with TestClient(app) as c:
        yield c


def test_every_page_and_api_answers_without_a_cnpj(client):
    for url in ("/", "/flows", "/reporting", "/status", "/method", "/api/overview",
                "/api/flows?segment=direct", "/api/flows?segment=direct:Cambial",
                "/api/reporting", "/api/status", "/data/daily-totals.csv", "/static/lags.json"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert not CNPJ.search(r.text), url


def test_the_headline_is_built_from_the_response(client):
    o = client.get("/api/overview").json()
    assert o["headline"].startswith("Net inflow of R$")
    assert "business days" in o["headline"] and o["headline"].endswith(".")


def test_headline_templates():
    from flows.views import headline
    base = {"this_month": {"month": "2026-10", "segments": [], "partial_days": 0},
            "last_month": {"month": "2026-09", "partial_days": 4, "segments": [
                {"segment": "direct", "net": -16.0e9, "days": 21}]},
            "assets": {"dt": "2026-09-23", "pl": 9.30e12}}
    assert headline(base) == ("Net outflow of R$16.0 bn in September, over 21 business days with 4 "
                              "still arriving; no day of October is mostly reported yet. "
                              "Net assets R$9.30 tn on 23 September.")
    base["this_month"]["segments"] = [{"segment": "direct", "net": 3.1e9, "days": 14}]
    base["this_month"]["partial_days"] = 3
    assert headline(base).startswith("Net inflow of R$3.1 bn in October so far, over 14 business "
                                     "days with 3 still arriving, after R$16.0 bn of outflow in "
                                     "September.")
    assert headline({"this_month": {"month": "2026-10", "segments": [], "partial_days": 0},
                     "last_month": {"month": "2026-09", "segments": [], "partial_days": 0},
                     "assets": None}) == "No day is mostly reported yet."


def test_hidden_segments_stay_hidden(client):
    flows = client.get("/api/flows?segment=direct:Cambial").json()
    assert flows["daily"] == [] and flows["months"] == [] and flows["hidden_days"] > 0
    csv = client.get("/data/daily-totals.csv").text
    assert "direct:Cambial" not in csv and "direct:Renda Fixa" in csv


def test_an_unknown_segment_is_refused(client):
    assert client.get("/api/flows?segment=fund:123").status_code == 400
