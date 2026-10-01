"""Data checks on CVM's daily report, its delivery log and the fund register, run before any
total or model is built. Results go to data/checks.json and, in words, to DATA.md.

    uv run python scripts/checks.py --from 202401 --to 202609
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import pandas as pd

from flows import calendar, history

FLOWS = ["pl", "captc", "resg", "cotst"]


def business_index() -> tuple[np.ndarray, callable]:
    days = np.array(calendar.business_days(date(2019, 1, 1), date(2027, 12, 31)),
                    dtype="datetime64[D]")

    def count_upto(d) -> np.ndarray:            # business days on or before d
        return np.searchsorted(days, np.asarray(d, dtype="datetime64[D]"), side="right")

    return days, count_upto


def subclasses(df: pd.DataFrame) -> dict:
    """Is a class row with subclasses the sum of its subclass rows, or are they exclusive?"""
    subs = df[df["sub"] != ""]
    keys = subs.groupby(["cnpj", "dt"])[FLOWS].sum()
    blank = df[df["sub"] == ""].set_index(["cnpj", "dt"])[FLOWS]
    both = keys.join(blank, how="inner", rsuffix="_class")
    rel = (both["pl_class"] - both["pl"]).abs() / both["pl_class"].abs().clip(lower=1)
    return {"class_days_with_subclasses": len(keys), "with_a_class_row_too": len(both),
            "class_row_equals_sum": int((rel < 1e-4).sum()),
            "subclass_rows": len(subs), "rows": len(df)}


def calendar_check(df: pd.DataFrame) -> dict:
    per_day = df.groupby("dt").size()
    typical = per_day.median()
    low = sorted(d for d, n in per_day.items() if n < 0.05 * typical)
    off = sorted(d for d in per_day.index if not calendar.is_business_day(d))
    return {"days": len(per_day), "duplicates": int(df.duplicated(["cnpj", "sub", "dt"]).sum()),
            "low_days": [str(d) for d in low], "non_business_days_with_rows": [str(d) for d in off],
            "low_but_business": [str(d) for d in low if calendar.is_business_day(d)],
            "normal_but_holiday": [str(d) for d in off if d not in low]}


def identity(df: pd.DataFrame, prev_day: dict) -> dict:
    """PL today against PL yesterday grown by the quota's return, plus subscriptions minus
    redemptions, on consecutive business days of the same fund."""
    df = df.sort_values(["cnpj", "sub", "dt"])
    g = df.groupby(["cnpj", "sub"])
    prev = pd.DataFrame({"dt": g["dt"].shift(), "pl": g["pl"].shift(), "quota": g["quota"].shift()})
    expected_prev = df["dt"].map(prev_day)
    ok = (prev["dt"] == expected_prev) & (prev["pl"] > 0) & (prev["quota"] > 0) & (df["quota"] > 0)
    resid = (df["pl"] - prev["pl"] * df["quota"] / prev["quota"]
             - (df["captc"].fillna(0) - df["resg"].fillna(0)))
    rel = (resid / prev["pl"]).abs()[ok]
    flow = (df["captc"].fillna(0) + df["resg"].fillna(0))[ok]
    return {"pairs": int(ok.sum()), "within_0_1pct": int((rel < 0.001).sum()),
            "within_1pct": int((rel < 0.01).sum()),
            "negative_flow_rows": int(((df["captc"] < 0) | (df["resg"] < 0)).sum()),
            "gross_flow_above_10x_pl": int((flow > 10 * prev["pl"][ok]).sum()),
            "missing_flow_rows": int((df["captc"].isna() | df["resg"].isna()).sum())}


def migrations(span: pd.DataFrame, next_day: dict, end: date) -> dict:
    """Funds that stop on one day while another starts on the next business day with the same
    net assets (within 0.5%): CNPJ changes, which would look like a fund going missing."""
    stops = span[span["last"] < end - timedelta(days=10)]
    starts = span.groupby("first")
    pairs, pl = 0, 0.0
    for d, part in stops.groupby("last"):
        if next_day.get(d) not in starts.groups:
            continue
        new_pl = starts.get_group(next_day[d])["first_pl"].dropna().to_numpy()
        for v in part["last_pl"].dropna():
            if v > 0 and new_pl.size and (np.abs(new_pl - v) / v < 0.005).any():
                pairs += 1
                pl += v
    return {"stopped_funds": len(stops), "matched_by_next_day_start": pairs,
            "matched_pl_brl": pl}


def lags(month: str, daily: pd.DataFrame, count_upto) -> dict:
    """Business-day lag at which each fund-day first appeared in a morning file, from the
    delivery log: a delivery on local day t is in the file of the next business day, so a report
    delivered on the competence day itself is at lag 1 and one delivered the next day at lag 2."""
    log = history.deliveries(month)
    local = (log["first_at"] - pd.Timedelta(hours=3)).dt.normalize()
    next_bd = count_upto(local.values.astype("datetime64[D]")) + 1   # index of next business day
    k = next_bd - count_upto(pd.to_datetime(log["dt"]).values.astype("datetime64[D]"))
    log = log.assign(k=np.clip(k, 0, 10))
    day_pl = daily.set_index(["cnpj", "sub", "dt"])[["pl", "captc", "resg"]]
    joined = log.set_index(["cnpj", "sub", "dt"]).join(day_pl, how="inner")
    gross = joined["captc"].fillna(0) + joined["resg"].fillna(0)
    out = {"competence_from": str(log["dt"].min()), "competence_to": str(log["dt"].max()),
           "fund_days": len(log), "joined": len(joined)}
    for name, w in (("count", pd.Series(1.0, index=joined.index)), ("pl", joined["pl"]),
                    ("gross_flow", gross)):
        share = w.groupby(joined["k"]).sum() / w.sum()
        out[f"share_by_k_{name}"] = {int(i): round(float(v), 5) for i, v in share.items()}
    late = joined["k"] >= 3          # missing from the first file where the day is mostly in
    net = (joined["captc"].fillna(0) - joined["resg"].fillna(0)).abs() / joined["pl"].clip(lower=1)
    out["median_abs_net_over_pl_on_time"] = float(net[~late].median())
    out["median_abs_net_over_pl_late"] = float(net[late].median())
    out["mean_abs_net_over_pl_on_time"] = float(net[~late].clip(upper=1).mean())
    out["mean_abs_net_over_pl_late"] = float(net[late].clip(upper=1).mean())
    return out


def register_check(daily: pd.DataFrame) -> dict:
    reg = history.register()
    classes = reg["classe"].assign(cnpj=lambda r: r["CNPJ_Classe"].str.replace(r"\D", "", regex=True))
    funds = reg["fundo"].assign(cnpj=lambda r: r["CNPJ_Fundo"].str.replace(r"\D", "", regex=True))
    present = sorted(daily["dt"].unique())
    last = present[-1]
    day = daily[daily["dt"] == present[-4]]                   # the fourth-latest day: about complete
    cls = classes.drop_duplicates("cnpj").set_index("cnpj")
    key = day["cnpj"].astype(str).str.zfill(14)
    in_class = key.isin(cls.index)
    in_fund = key.isin(set(funds["cnpj"]))
    pl = day["pl"].fillna(0)
    joined = cls.reindex(key)
    out = {"day": str(day["dt"].iloc[0]), "latest_day": str(last), "fund_days": len(day),
           "pl_brl": float(pl.sum()),
           "pl_share_matched_class": float(pl[in_class.values].sum() / pl.sum()),
           "pl_share_matched_fund_only": float(pl[(~in_class & in_fund).values].sum() / pl.sum())}
    for col in ("Classificacao", "Classe_Cotas", "Exclusivo", "Publico_Alvo",
                "Classificacao_Anbima"):
        values = joined[col].fillna("(unmatched or blank)").values
        share = pl.groupby(values).sum() / pl.sum()
        out[f"pl_share_by_{col}"] = {k: round(float(v), 4) for k, v in
                                     share.sort_values(ascending=False).head(12).items()}
    return out


def export_lags(out: dict) -> dict:
    """Share of fund-days, net assets and gross flow in by each lag, across the months with a
    delivery log: the table on the Reporting page (web/lags.json)."""
    months = [m for m, v in out["months"].items() if "lags" in v]
    table = []
    for k in range(1, 7):
        row = {"lag": k}
        for name in ("count", "pl", "gross_flow"):
            vals = [sum(v for key, v in out["months"][m]["lags"][f"share_by_k_{name}"].items()
                        if int(key) <= k) for m in months]
            row[name] = {"mean": round(sum(vals) / len(vals), 4), "min": round(min(vals), 4),
                         "max": round(max(vals), 4)}
        table.append(row)
    lags = {"from": months[0], "to": months[-1], "by_lag": table}
    (history.DATA.parent / "web" / "lags.json").write_text(json.dumps(lags, indent=1))
    return lags


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="first", default="202401")
    parser.add_argument("--to", dest="last", default="202609")
    args = parser.parse_args()
    days, count_upto = business_index()
    prev_day = {pd.Timestamp(d).date(): pd.Timestamp(p).date() for p, d in pairwise(days)}
    out: dict = {"months": {}}
    spans = []
    for month in history.months(args.first, args.last):
        df = history.daily(month)
        res = {"subclasses": subclasses(df), "calendar": calendar_check(df),
               "identity": identity(df, prev_day)}
        if month >= "202501":
            res["lags"] = lags(month, df, count_upto)
        out["months"][month] = res
        spans.append(df.groupby(["cnpj", "sub"]).agg(first=("dt", "min"), last=("dt", "max")))
        print(month, json.dumps({k: v for k, v in res["subclasses"].items()}), flush=True)
    span = pd.concat(spans).groupby(level=[0, 1]).agg(first=("first", "min"), last=("last", "max"))
    full = history.daily_range(args.first, args.last, ["cnpj", "sub", "dt", "pl"])
    pl_at = full.set_index(["cnpj", "sub", "dt"])["pl"]
    span["first_pl"] = pl_at.reindex(list(zip(span.index.get_level_values(0),
                                              span.index.get_level_values(1), span["first"],
                                              strict=True))).values
    span["last_pl"] = pl_at.reindex(list(zip(span.index.get_level_values(0),
                                             span.index.get_level_values(1), span["last"],
                                             strict=True))).values
    next_day = {p: d for d, p in prev_day.items()}
    out["migrations"] = migrations(span.reset_index(), next_day, full["dt"].max())
    out["register"] = register_check(history.daily(args.last))
    path = history.DATA / "checks.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    export_lags(out)
    print("written", path)


if __name__ == "__main__":
    main()
