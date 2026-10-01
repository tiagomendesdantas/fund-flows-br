from __future__ import annotations

import io
import zipfile
from datetime import date, datetime

import pandas as pd
import pytest
from sqlalchemy import select

from flows import collect, db, scheduler, sources

HEADER = ("TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;ID_SUBCLASSE;DT_COMPTC;VL_TOTAL;VL_QUOTA;"
          "VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST")
LOG_HEADER = ("Tipo_Fundo_Classe;CNPJ_Fundo_Classe;ID_Subclasse;Tipo_Documento;"
              "Data_Inicio_Competencia;Data_Fim_Competencia;ID_Documento;Data_Hora_Entrega;"
              "Tipo_Apresentacao;Ativo;Sistema_Origem")


def at(stamp: str) -> datetime:
    """A naive UTC time, as the database stores them."""
    return pd.Timestamp(stamp).to_pydatetime()


def zipped(lines: list[str], encoding: str = "ascii") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("file.csv", ("\r\n".join(lines) + "\r\n").encode(encoding))
    return buf.getvalue()


def daily(*rows: str) -> bytes:
    return zipped([HEADER, *rows])


def log(*rows: str) -> bytes:
    return zipped([LOG_HEADER, *rows], "latin-1")


A1 = "CLASSES - FIF;00.000.000/0001-91;;2026-09-29;100.0;1.5;100.0;10.0;0.0;5"
B1 = "CLASSES - FIF;11.111.111/0001-11;SUB1;2026-09-29;200.0;2.0;200.0;0.0;20.0;7"
A2 = "CLASSES - FIF;00.000.000/0001-91;;2026-09-30;110.0;1.6;110.0;0.0;0.0;5"


def test_parse_daily_reads_keys_and_values():
    frame = sources.parse_daily(daily(A1, B1))
    assert list(frame["cnpj"]) == [191, 11111111000111]
    assert list(frame["sub"]) == ["", "SUB1"]
    assert frame.loc[1, "resg"] == 20.0 and frame.loc[0, "dt"] == date(2026, 9, 29)


def test_parse_daily_reads_the_layout_before_resolution_175():
    frame = sources.parse_daily(zipped([
        "TP_FUNDO;CNPJ_FUNDO;DT_COMPTC;VL_TOTAL;VL_QUOTA;VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST",
        "FI;00.000.000/0001-91;2021-06-30;100.0;1.5;100.0;10.0;0.0;5"]))
    assert frame.loc[0, "cnpj"] == 191 and frame.loc[0, "sub"] == "" and frame.loc[0, "kind"] == "FI"


def test_parse_daily_refuses_a_changed_layout():
    with pytest.raises(KeyError):
        sources.parse_daily(zipped(["A;B", "1;2"]))


def test_parse_deliveries_keeps_daily_reports_in_utc():
    content = log(
        "CLASSES - FIF;00000000000191;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;1;2026-09-29 19:00:00.000;Apresentação;S;X",
        "CLASSES - FIF;00000000000191;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;2;2026-09-30 10:00:00.000;Reapresentação;S;X",
        "CLASSES - FIF;00000000000191;;FATO RELEV;2026-09-29;2026-09-29;3;2026-09-29 08:00:00.000;Apresentação;S;X")
    out = sources.parse_deliveries(content)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["first_at"] == pd.Timestamp("2026-09-29 22:00")      # 19:00 Brasília
    assert row["last_at"] == pd.Timestamp("2026-09-30 13:00") and row["n_resub"] == 1
    assert row["active"] == 1


def test_a_fund_day_counts_from_its_first_delivery_of_any_kind():
    out = sources.parse_deliveries(log(
        "CLASSES - FIF;00000000000191;S1;DIÁRIO FUNDOS;2026-09-29;2026-09-29;1;2026-09-30 10:00:00.000;Reapresentação;S;X",
        "CLASSES - FIF;11111111000111;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;2;2026-09-29 19:00:00.000;Apresentação;N;X"))
    by = out.set_index("cnpj")
    assert by.loc[191, "first_at"] == pd.Timestamp("2026-09-30 13:00")
    assert by.loc[11111111000111, "active"] == 0           # withdrawn: not in the file


class Files:
    """Stands in for CVM: serves the content set for each URL, honouring ETags."""

    def __init__(self):
        self.content: dict[str, tuple[bytes, str, datetime]] = {}

    def set(self, url: str, content: bytes, etag: str, written: datetime) -> None:
        self.content[url] = (content, etag, written)

    def get(self, url: str, etag: str | None = None) -> sources.Download:
        if url not in self.content:
            return sources.Download(url, 404, b"", None, None)
        content, tag, written = self.content[url]
        if etag == tag:
            return sources.Download(url, 304, b"", tag, written)
        return sources.Download(url, 200, content, tag, written)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    db.engine.cache_clear()
    eng = db.engine(f"sqlite:///{tmp_path}/t.db")
    files = Files()
    monkeypatch.setattr(sources, "get", files.get)
    return eng, files


NOW = pd.Timestamp("2026-10-01 04:10")


def test_first_values_are_kept_and_changes_logged(setup):
    eng, files = setup
    url = sources.daily_url("202609")
    files.set(url, daily(A1, B1), "e1", at("2026-10-01 03:52"))
    note = collect.ingest_daily(eng, "202609", NOW)
    assert "2 new" in note and "bootstrap" in note
    assert collect.ingest_daily(eng, "202609", NOW).endswith("unchanged")

    resubmitted = A1.replace(";10.0;0.0;5", ";12.0;0.0;5")
    files.set(url, daily(resubmitted, B1, A2), "e2", at("2026-10-02 03:52"))
    note = collect.ingest_daily(eng, "202609", NOW + pd.Timedelta(days=1))
    assert "1 new, 1 revised" in note and "bootstrap" not in note
    with eng.connect() as conn:
        a = conn.execute(select(db.fund_days).where(db.fund_days.c.cnpj == 191,
                                                    db.fund_days.c.dt == date(2026, 9, 29))
                         ).mappings().one()
        changes = conn.execute(select(db.fund_day_changes)).mappings().all()
        days = {(r["release_id"], r["dt"]): r for r in
                conn.execute(select(db.release_days)).mappings()}
    assert (a["captc"], a["first_captc"], a["revisions"]) == (12.0, 10.0, 1)
    assert a["first_release"] == 1 and a["last_release"] == 2
    assert len(changes) == 1 and changes[0]["old_captc"] == 10.0
    second = days[(2, date(2026, 9, 29))]
    assert (second["n"], second["n_new"], second["n_changed"], second["d_captc"]) == (2, 0, 1, 2.0)
    assert days[(2, date(2026, 9, 30))]["n_new"] == 1


def test_a_month_started_after_collection_began_is_not_bootstrap(setup):
    eng, files = setup
    files.set(sources.daily_url("202609"), daily(A1), "e1", at("2026-10-01 03:52"))
    collect.ingest_daily(eng, "202609", NOW)
    files.set(sources.daily_url("202610"),
              daily(A1.replace("2026-09-29", "2026-10-01")), "f1", at("2026-10-02 03:52"))
    assert "bootstrap" not in collect.ingest_daily(eng, "202610", NOW + pd.Timedelta(days=1))


def test_the_check_rebuilds_the_release_from_the_delivery_log(setup):
    eng, files = setup
    files.set(sources.daily_url("202609"), daily(A1, B1), "e1", at("2026-10-01 03:52"))
    files.set(sources.deliveries_url("202609"), log(
        "CLASSES - FIF;00000000000191;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;1;2026-09-29 19:00:00.000;Apresentação;S;X",
        "CLASSES - FIF;11111111000111;SUB1;DIÁRIO FUNDOS;2026-09-29;2026-09-29;2;2026-10-01 00:30:00.000;Apresentação;S;X",
        "CLASSES FIIM;22222222000122;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;3;2026-09-29 19:00:00.000;Apresentação;S;X",
        "CLASSES - FIF;33333333000133;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;4;2026-10-01 01:00:00.000;Apresentação;S;X",
        "CLASSES - FIF;44444444000144;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;5;2026-09-29 19:00:00.000;Apresentação;N;X"),
        "d1", at("2026-10-01 04:46"))
    notes = collect.collect_files(eng, NOW)
    assert "check daily:202609: 1 days, all equal" in notes
    assert collect.check_releases(eng) == []            # each release is checked once


def test_the_check_waits_for_a_delivery_log_written_after_the_release(setup):
    eng, files = setup
    files.set(sources.daily_url("202609"), daily(A1), "e1", at("2026-10-01 03:52"))
    files.set(sources.deliveries_url("202609"), log(
        "CLASSES - FIF;00000000000191;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;1;2026-09-29 19:00:00.000;Apresentação;S;X"),
        "d0", at("2026-09-30 04:46"))
    notes = collect.collect_files(eng, NOW)
    assert not any(n.startswith("check") for n in notes)


def test_deliveries_follow_the_newest_file(setup):
    eng, files = setup
    url = sources.deliveries_url("202609")
    first = "CLASSES - FIF;00000000000191;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;1;2026-09-29 19:00:00.000;Apresentação;S;X"
    other = "CLASSES - FIF;11111111000111;;DIÁRIO FUNDOS;2026-09-29;2026-09-29;2;2026-09-29 20:00:00.000;Apresentação;S;X"
    files.set(url, log(first, other), "d1", at("2026-10-01 04:46"))
    collect.ingest_deliveries(eng, "202609")
    resub = first.replace(";1;2026-09-29 19:00:00.000;Apresentação", ";5;2026-09-30 09:00:00.000;Reapresentação")
    files.set(url, log(first, resub), "d2", at("2026-10-02 04:46"))
    note = collect.ingest_deliveries(eng, "202609")
    assert "1 changed" in note and "1 gone" in note
    with eng.connect() as conn:
        rows = conn.execute(select(db.deliveries)).mappings().all()
    assert len(rows) == 1 and rows[0]["n_resub"] == 1


def test_months_are_local_and_the_slots_run_once():
    assert collect.months(pd.Timestamp("2026-10-01 02:00")) == ["202608", "202609"]  # still 30 Sep
    assert collect.months(pd.Timestamp("2026-10-01 04:10")) == ["202609", "202610"]
    slot = pd.Timestamp("2026-10-01 04:10:30")
    assert scheduler.due(slot, {}) == ["files"]
    assert scheduler.due(slot, {"files": slot.floor("min")}) == []
    assert scheduler.due(pd.Timestamp("2026-10-01 06:00"), {}) == []
