from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd

from flows import register, totals

DAY = date(2026, 9, 25)


def funds(rows: list[tuple]) -> pd.DataFrame:
    """rows: (cnpj, pl, captc, resg)."""
    return pd.DataFrame([{"cnpj": c, "sub": "", "dt": DAY, "pl": pl, "captc": ca, "resg": re,
                          "cotst": 1.0, "total": pl, "quota": 1.0} for c, pl, ca, re in rows])


def classes(rows: list[tuple]) -> pd.DataFrame:
    """rows: (cnpj, category, fic)."""
    return pd.DataFrame([{"cnpj": c, "category": cat, "fic": fic} for c, cat, fic in rows],
                        columns=["cnpj", "category", "fic"])


def test_funds_of_funds_are_left_out_of_direct_totals():
    frame = funds([(1, 100.0, 10.0, 0.0), (2, 50.0, 10.0, 0.0)] +
                  [(10 + i, 10.0, 1.0, 1.0) for i in range(10)])
    reg = classes([(1, "Renda Fixa", 1), (2, "Renda Fixa", 0)] +
                  [(10 + i, "Renda Fixa", 0) for i in range(10)])
    out = totals.daily_totals(frame, reg).set_index("segment")
    assert out.loc["all", "captc"] == 30.0 and out.loc["direct", "captc"] == 20.0
    assert out.loc["direct:Renda Fixa", "n"] == 11


def test_a_class_missing_from_the_register_is_unclassified_and_direct():
    out = totals.daily_totals(funds([(1, 100.0, 5.0, 0.0)]), classes([])).set_index("segment")
    assert out.loc["direct:Unclassified", "captc"] == 5.0 and out.loc["direct", "n"] == 1


def test_a_segment_dominated_by_one_fund_or_with_few_funds_is_hidden():
    many = [(10 + i, 10.0, 1.0, 1.0) for i in range(12)]
    frame = funds([(1, 100.0, 500.0, 0.0)] + many)
    reg = classes([(1, "Ações", 0)] + [(10 + i, "Ações", 0) for i in range(12)]
                  + [(99, "Cambial", 0)])
    out = totals.daily_totals(pd.concat([frame, funds([(99, 5.0, 1.0, 0.0)])]),
                              reg).set_index("segment")
    assert out.loc["direct:Ações", "top_share"] > 0.5 and out.loc["direct:Ações", "shown"] == 0
    assert out.loc["direct:Cambial", "shown"] == 0            # one fund
    assert out.loc["all", "shown"] == 0                       # one fund is >50% of all flow too


def zipped_register(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("registro_classe.csv", "\n".join(lines).encode("latin-1"))
    return buf.getvalue()


def test_the_current_register_wins_and_legacy_classes_map_to_instruction_555():
    current = register.parse_register(zipped_register([
        "CNPJ_Classe;Data_Registro;Classificacao;Classe_Cotas;Exclusivo",
        "00.000.000/0001-91;2024-01-01;Ações;S;N"]))
    legacy = register.parse_legacy((
        "CNPJ_FUNDO;DT_REG;CLASSE;FUNDO_COTAS;FUNDO_EXCLUSIVO\n"
        "00.000.000/0001-91;2010-01-01;Renda Fixa;N;N\n"
        "11.111.111/0001-11;2010-01-01;Referenciado;N;S\n"
        "22.222.222/0001-22;2010-01-01;FIDC;N;N\n").encode("latin-1"))
    both = register.combine(current, legacy).set_index("cnpj")
    assert both.loc[191, "category"] == "Ações" and both.loc[191, "fic"] == 1
    assert both.loc[11111111000111, "category"] == "Renda Fixa"
    assert both.loc[22222222000122, "category"] == register.UNCLASSIFIED
