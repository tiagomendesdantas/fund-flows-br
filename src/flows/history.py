"""Local history for analysis: CVM's raw monthly files (scripts/download.py) parsed once into
Parquet under data/parquet/. Never used by the web service."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from flows import sources

DATA = Path(__file__).resolve().parents[2] / "data"
RAW, PARQUET = DATA / "raw", DATA / "parquet"


def _cached(name: str, raw: Path, parse) -> pd.DataFrame:
    path = PARQUET / f"{name}.parquet"
    if path.exists() and path.stat().st_mtime >= raw.stat().st_mtime:
        return pd.read_parquet(path)
    frame = parse(raw.read_bytes())
    PARQUET.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def daily(month: str) -> pd.DataFrame:
    """The daily report for one month as it stands in the downloaded file."""
    return _cached(f"daily_{month}", RAW / f"inf_diario_fi_{month}.zip", sources.parse_daily)


def deliveries(month: str) -> pd.DataFrame:
    return _cached(f"deliveries_{month}", RAW / f"fi_entrega_documento_{month}.zip",
                   sources.parse_deliveries)


def months(first: str, last: str) -> list[str]:
    return [m.strftime("%Y%m") for m in pd.period_range(first, last, freq="M")]


def daily_range(first: str, last: str, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.concat([daily(m)[columns] if columns else daily(m) for m in months(first, last)],
                     ignore_index=True)


def register() -> dict[str, pd.DataFrame]:
    """The fund register after CVM Resolution 175: funds, classes and subclasses (Latin-1)."""
    with zipfile.ZipFile(RAW / "registro_fundo_classe.zip") as z:
        return {name.removesuffix(".csv").removeprefix("registro_"): pd.read_csv(
            io.BytesIO(z.read(name)), sep=";", encoding="latin-1", dtype=str)
            for name in z.namelist() if name.endswith(".csv")}
