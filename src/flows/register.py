"""The fund register: each class's CVM category, and whether it is a fund of funds.

Two sources. The register after CVM Resolution 175 (`registro_classe.csv`) covers 99.999% of the
daily report's net assets in 2026 but only 91% in 2021, since it leaves out funds closed before it
began; the legacy register (`cad_fi.csv`) fills most of the rest (97.3% in 2021). The new register
wins where both have a fund. Classes of the legacy register's older rules map to the four classes
of CVM Instruction 555, which absorbed them: Referenciado, Curto Prazo and Dívida Externa into
Renda Fixa.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
from sqlalchemy.engine import Engine

from flows import db, sources

REGISTER_URL = f"{sources.BASE}/CAD/DADOS/registro_fundo_classe.zip"
LEGACY_URL = f"{sources.BASE}/CAD/DADOS/cad_fi.csv"
CATEGORIES = ["Renda Fixa", "Ações", "Multimercado", "Cambial", "FMP-FGTS"]
UNCLASSIFIED = "Unclassified"
LEGACY_CATEGORY = {"Renda Fixa": "Renda Fixa", "Referenciado": "Renda Fixa",
                   "Curto Prazo": "Renda Fixa", "Dívida Externa": "Renda Fixa",
                   "Ações": "Ações", "Multimercado": "Multimercado", "Cambial": "Cambial",
                   "FMP-FGTS": "FMP-FGTS"}


def _digits(s: pd.Series) -> pd.Series:
    return s.str.replace(r"\D", "", regex=True)


def _flag(s: pd.Series) -> pd.Series:
    return s.map({"S": 1, "N": 0})


def parse_register(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = pd.read_csv(io.BytesIO(z.read("registro_classe.csv")), sep=";", encoding="latin-1",
                          dtype=str)
    raw = raw[_digits(raw["CNPJ_Classe"].fillna("")).str.len() > 0]
    raw = raw.sort_values("Data_Registro").drop_duplicates("CNPJ_Classe", keep="last")
    return pd.DataFrame({
        "cnpj": _digits(raw["CNPJ_Classe"]).astype("int64"),
        "category": raw["Classificacao"].where(raw["Classificacao"].isin(CATEGORIES),
                                               UNCLASSIFIED),
        "fic": _flag(raw["Classe_Cotas"]), "exclusive": _flag(raw["Exclusivo"]),
        "source": "registro_classe"})


def parse_legacy(content: bytes) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(content), sep=";", encoding="latin-1", dtype=str)
    raw = raw[_digits(raw["CNPJ_FUNDO"].fillna("")).str.len() > 0]
    raw = raw.sort_values("DT_REG").drop_duplicates("CNPJ_FUNDO", keep="last")
    return pd.DataFrame({
        "cnpj": _digits(raw["CNPJ_FUNDO"]).astype("int64"),
        "category": raw["CLASSE"].map(LEGACY_CATEGORY).fillna(UNCLASSIFIED),
        "fic": _flag(raw["FUNDO_COTAS"]), "exclusive": _flag(raw["FUNDO_EXCLUSIVO"]),
        "source": "cad_fi"})


def combine(current: pd.DataFrame, legacy: pd.DataFrame) -> pd.DataFrame:
    """One row per CNPJ: the current register's, else the legacy one's."""
    both = pd.concat([current, legacy[~legacy["cnpj"].isin(current["cnpj"])]], ignore_index=True)
    return both.reset_index(drop=True)


def refresh(eng: Engine) -> list[str]:
    """Download both registers and replace the `classes` table (about 80,000 rows)."""
    current, legacy = sources.get(REGISTER_URL), sources.get(LEGACY_URL)
    for got in (current, legacy):
        if got.status != 200:
            db.log_fetch(eng, source="cvm", target=got.url.rsplit("/", 1)[1], status="error",
                         detail=f"HTTP {got.status}")
            return [f"register: HTTP {got.status}"]
    classes = combine(parse_register(current.content), parse_legacy(legacy.content))
    classes["updated_at"] = db.utcnow()
    with eng.begin() as conn:
        conn.execute(db.classes.delete())
        for start in range(0, len(classes), 20_000):
            part = classes.iloc[start:start + 20_000]
            conn.execute(db.classes.insert(),
                         part.astype(object).where(part.notna(), None).to_dict("records"))
    db.log_fetch(eng, source="cvm", target="register", status="ok", rows=len(classes))
    return [f"register: {len(classes)} classes"]


def load(eng: Engine) -> pd.DataFrame:
    with eng.connect() as conn:
        rows = conn.execute(db.classes.select()).mappings().all()
    return pd.DataFrame(rows, columns=["cnpj", "category", "fic", "exclusive", "source",
                                       "updated_at"])
