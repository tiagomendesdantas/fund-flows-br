"""CVM open data (ODbL): the daily fund report and the log of its deliveries.

Both are monthly zips holding one CSV. CVM rewrites the current and the previous month Monday to
Saturday (around 03:52 UTC on the days checked) with late reports and resubmissions, and older
months weekly. A file is downloaded only when its ETag has changed (conditional GET).
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
import pandas as pd

BASE = "https://dados.cvm.gov.br/dados/FI"
USER_AGENT = "fund-flows-br (portfolio project)"
# Brasília has had no daylight saving time since 2019: local time is UTC-3.
LOCAL_OFFSET = pd.Timedelta(hours=3)

DAILY_COLUMNS = {"TP_FUNDO_CLASSE": "kind", "CNPJ_FUNDO_CLASSE": "cnpj", "ID_SUBCLASSE": "sub",
                 "DT_COMPTC": "dt", "VL_TOTAL": "total", "VL_QUOTA": "quota",
                 "VL_PATRIM_LIQ": "pl", "CAPTC_DIA": "captc", "RESG_DIA": "resg",
                 "NR_COTST": "cotst"}
VALUES = ["total", "quota", "pl", "captc", "resg", "cotst"]
KEY = ["cnpj", "sub", "dt"]

DELIVERY_COLUMNS = {"Tipo_Fundo_Classe": "kind", "CNPJ_Fundo_Classe": "cnpj",
                    "ID_Subclasse": "sub", "Tipo_Documento": "doc",
                    "Data_Fim_Competencia": "dt", "Data_Hora_Entrega": "at",
                    "Tipo_Apresentacao": "presentation", "Ativo": "active"}
DAILY_REPORT = "DIÁRIO FUNDOS"


def daily_url(month: str) -> str:
    return f"{BASE}/DOC/INF_DIARIO/DADOS/inf_diario_fi_{month}.zip"


def deliveries_url(month: str) -> str:
    return f"{BASE}/DOC/ENTREGA/DADOS/fi_entrega_documento_{month}.zip"


@dataclass
class Download:
    url: str
    status: int                      # 200, 304 (unchanged since the ETag given), 404, ...
    content: bytes
    etag: str | None
    last_modified: datetime | None   # naive UTC: when CVM wrote the file

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def get(url: str, etag: str | None = None, timeout: float = 300.0) -> Download:
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        r = client.get(url)
    modified = r.headers.get("last-modified")
    when = (parsedate_to_datetime(modified).astimezone(UTC).replace(tzinfo=None)
            if modified else None)
    return Download(url, r.status_code, r.content if r.status_code == 200 else b"",
                    r.headers.get("etag"), when)


def _member(content: bytes, prefer: str = "") -> io.BytesIO:
    """The zip's CSV; where there are several, the one whose name contains `prefer`."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) > 1:
            names = [n for n in names if prefer and prefer in n.lower()]
        if len(names) != 1:
            raise ValueError(f"zip holds {z.namelist()}")
        return io.BytesIO(z.read(names[0]))


def _cnpj(s: pd.Series) -> pd.Series:
    return s.str.replace(r"\D", "", regex=True).astype("int64")


def parse_daily(content: bytes) -> pd.DataFrame:
    """One row per fund class (or subclass) and day: key cnpj (digits), sub ('' for a class
    without subclasses), dt; the six reported values; kind as reported."""
    raw = pd.read_csv(_member(content), sep=";", encoding="latin-1",
                      dtype={c: str for c in ("TP_FUNDO_CLASSE", "CNPJ_FUNDO_CLASSE",
                                              "ID_SUBCLASSE", "DT_COMPTC")})
    missing = set(DAILY_COLUMNS) - set(raw.columns)
    if missing:
        raise KeyError(f"daily report without {sorted(missing)}")
    frame = raw.rename(columns=DAILY_COLUMNS)[list(DAILY_COLUMNS.values())]
    frame["cnpj"] = _cnpj(frame["cnpj"])
    frame["sub"] = frame["sub"].fillna("").str.strip()
    frame["dt"] = pd.to_datetime(frame["dt"], format="%Y-%m-%d").dt.date
    for col in VALUES:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float64")
    return frame.drop_duplicates(KEY, keep="last").reset_index(drop=True)


def parse_deliveries(content: bytes, chunksize: int = 250_000) -> pd.DataFrame:
    """Deliveries of the daily report, one row per fund-day: the first delivery of any kind and
    the last (naive UTC), how many were resubmissions, and whether one is still active. A
    fund-day is in the published file when it has an active delivery: on 2026-10-01, 15 fund-days
    whose every delivery was inactive were absent, and 27 subclass fund-days had resubmissions
    but no first presentation. The zip keeps the daily report's deliveries in their own CSV
    (`..._diario_...`, 158 MB for September 2026), read in chunks."""
    parts = []
    reader = pd.read_csv(_member(content, prefer="_diario_"), sep=";", encoding="latin-1",
                         dtype=str, chunksize=chunksize)
    for raw in reader:
        missing = set(DELIVERY_COLUMNS) - set(raw.columns)
        if missing:
            raise KeyError(f"delivery log without {sorted(missing)}")
        frame = raw.rename(columns=DELIVERY_COLUMNS)[list(DELIVERY_COLUMNS.values())]
        frame = frame[frame["doc"] == DAILY_REPORT].copy()
        frame["cnpj"] = _cnpj(frame["cnpj"])
        frame["sub"] = frame["sub"].fillna("").str.strip()
        frame["dt"] = pd.to_datetime(frame["dt"], format="%Y-%m-%d").dt.date
        frame["at"] = (pd.to_datetime(frame["at"].str[:19], format="%Y-%m-%d %H:%M:%S")
                       + LOCAL_OFFSET)
        frame["resub"] = (frame["presentation"] != "Apresentação").astype(int)
        frame["active"] = (frame["active"] == "S").astype(int)
        parts.append(frame.groupby(KEY, as_index=False).agg(
            kind=("kind", "last"), first_at=("at", "min"), last_at=("at", "max"),
            n_resub=("resub", "sum"), active=("active", "max")))
    if not parts:
        return pd.DataFrame(columns=KEY + ["kind", "first_at", "last_at", "n_resub", "active"])
    both = pd.concat(parts, ignore_index=True)
    return both.groupby(KEY, as_index=False).agg(
        kind=("kind", "last"), first_at=("first_at", "min"), last_at=("last_at", "max"),
        n_resub=("n_resub", "sum"), active=("active", "max"))
