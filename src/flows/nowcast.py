"""Estimates of a day's final totals from what was known on a morning (flows.vintages).

    reported       the sum of what has arrived: what a reader of the file sees
    scale_up       reported × expected net assets / present net assets, within each category
    trailing       reported + each missing fund's own trailing 20-day mean subscriptions and
                   redemptions, scaled by its last net assets
    trailing_beta  trailing, plus a per-category response to the day's reported net flow
    model          reported + a LightGBM prediction per missing fund (features below)

Every estimate is by segment (flows.totals.segments) with the net assets still missing, which
scales the intervals. Rules in docs/EVAL_PLAN.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from flows import intervals, register, totals
from flows.vintages import FUND, Vintage

METHODS = ["reported", "scale_up", "trailing", "trailing_beta", "model"]
LEGS = ["captc", "resg"]
MAX_FACTOR = 3.0          # scale-up is capped: a category with almost nothing in is not scaled up
FEATURES = ["pl_last_log", "captc_rate", "resg_rate", "zero_share", "n_trail", "days_since_seen",
            "k", "month_end", "bd_to_month_end", "exclusive", "fic", "category_code",
            "cat_net_rate", "cat_captc_rate", "cat_resg_rate", "cat_share_reported"]
CATEGORY_CODES = {c: i for i, c in enumerate(register.CATEGORIES + [register.UNCLASSIFIED])}


def _tag(frame: pd.DataFrame, classes: pd.DataFrame) -> pd.DataFrame:
    known = classes[["cnpj", "category", "fic", "exclusive"]].astype({"cnpj": "int64"})
    out = frame.merge(known, on="cnpj", how="left")
    out["category"] = out["category"].fillna(register.UNCLASSIFIED)
    out["fic"] = out["fic"].fillna(0).astype(int)
    out["exclusive"] = out["exclusive"].fillna(0).astype(int)
    return out


def _masks(f: pd.DataFrame) -> dict[str, pd.Series]:
    direct = f["fic"] != 1
    masks = {"all": pd.Series(True, index=f.index), "direct": direct}
    for c in register.CATEGORIES + [register.UNCLASSIFIED]:
        masks[f"direct:{c}"] = direct & (f["category"] == c)
    return masks


def _bd_to_month_end(d) -> int:
    from flows import calendar
    t = pd.Timestamp(d)
    last = t + pd.offsets.MonthEnd(0)
    while not calendar.is_business_day(last.date()):
        last -= pd.Timedelta(days=1)
    return calendar.lag(t.date(), last.date())


def groups(v: Vintage, classes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Present rows and missing rows tagged with category, fund-of-funds and exclusive flags, and
    per (category, fic) group: present sums, missing net assets and the scale-up factor."""
    present = _tag(v.present, classes)
    missing = _tag(v.missing, classes)
    g = present.groupby(["category", "fic"]).agg(
        captc=("captc", lambda s: float(s.fillna(0).sum())),
        resg=("resg", lambda s: float(s.fillna(0).sum())),
        pl=("pl", lambda s: float(s.fillna(0).sum())), n=("cnpj", "size"))
    miss = missing.groupby(["category", "fic"])["pl_last"].sum().rename("missing_pl")
    g = g.join(miss, how="outer").fillna({"captc": 0.0, "resg": 0.0, "pl": 0.0, "n": 0,
                                           "missing_pl": 0.0})
    g["factor"] = np.where(g["pl"] > 0, np.minimum((g["pl"] + g["missing_pl"]) / g["pl"].where(
        g["pl"] > 0, 1), MAX_FACTOR), 1.0)
    return present, missing, g.reset_index()


def features(v: Vintage, classes: pd.DataFrame) -> pd.DataFrame:
    """One row per missing fund with the model's inputs; empty when nothing is missing."""
    _, missing, g = groups(v, classes)
    if missing.empty:
        return pd.DataFrame(columns=FUND + FEATURES + ["pl_last", "category", "d", "k"])
    cat = g.groupby("category").agg(captc=("captc", "sum"), resg=("resg", "sum"), pl=("pl", "sum"),
                                    missing_pl=("missing_pl", "sum"))
    cat["cat_captc_rate"] = cat["captc"] / cat["pl"].where(cat["pl"] > 0, np.nan)
    cat["cat_resg_rate"] = cat["resg"] / cat["pl"].where(cat["pl"] > 0, np.nan)
    cat["cat_net_rate"] = cat["cat_captc_rate"] - cat["cat_resg_rate"]
    cat["cat_share_reported"] = cat["pl"] / (cat["pl"] + cat["missing_pl"]).where(
        (cat["pl"] + cat["missing_pl"]) > 0, np.nan)
    f = missing.merge(cat[["cat_captc_rate", "cat_resg_rate", "cat_net_rate",
                           "cat_share_reported"]], left_on="category", right_index=True,
                      how="left")
    f["pl_last_log"] = np.log1p(f["pl_last"].fillna(0).clip(lower=0))
    f["k"] = v.k
    f["month_end"] = int(intervals.month_end(v.d))
    f["bd_to_month_end"] = _bd_to_month_end(v.d)
    f["category_code"] = f["category"].map(CATEGORY_CODES).fillna(len(CATEGORY_CODES)).astype(int)
    f["d"] = pd.Timestamp(v.d)
    return f


def _missing_flows(method: str, v: Vintage, missing: pd.DataFrame, g: pd.DataFrame,
                   predictions: pd.DataFrame | None, betas: dict | None) -> pd.DataFrame:
    """Each missing fund's estimated subscriptions and redemptions under `method`."""
    out = missing[FUND + ["category", "fic", "pl_last"]].copy()
    pl = out["pl_last"].fillna(0).clip(lower=0)
    if method in ("reported", "scale_up"):
        out["captc"], out["resg"] = 0.0, 0.0
        return out
    if method == "model":
        if predictions is None:
            raise ValueError("model estimates need predictions")
        p = out.merge(predictions, on=FUND, how="left")
        out["captc"] = (p["captc_rate_hat"].fillna(0) * pl).to_numpy()
        out["resg"] = (p["resg_rate_hat"].fillna(0) * pl).to_numpy()
        return out
    # trailing: a fund without history takes its category's mean rate among missing funds
    rates = missing[["category", "captc_rate", "resg_rate"]]
    cat_mean = rates.groupby("category")[["captc_rate", "resg_rate"]].mean()
    captc_rate = missing["captc_rate"].fillna(missing["category"].map(cat_mean["captc_rate"])).fillna(0)
    resg_rate = missing["resg_rate"].fillna(missing["category"].map(cat_mean["resg_rate"])).fillna(0)
    out["captc"] = (captc_rate * pl).to_numpy()
    out["resg"] = (resg_rate * pl).to_numpy()
    if method == "trailing_beta" and betas:
        cat = g.groupby("category").agg(captc=("captc", "sum"), resg=("resg", "sum"), pl=("pl", "sum"))
        shock = ((cat["captc"] - cat["resg"]) / cat["pl"].where(cat["pl"] > 0, np.nan)).fillna(0)
        beta = missing["category"].map(betas).fillna(0)
        extra = beta * missing["category"].map(shock).fillna(0) * pl
        out["captc"] = out["captc"] + extra.clip(lower=0).to_numpy()
        out["resg"] = out["resg"] + (-extra).clip(lower=0).to_numpy()
    return out


def estimate(v: Vintage, method: str, classes: pd.DataFrame, predictions: pd.DataFrame | None = None,
             betas: dict | None = None) -> pd.DataFrame:
    """One row per segment: the estimated captc, resg and net, what was reported, and the net
    assets still missing."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    present, missing, g = groups(v, classes)
    flows = _missing_flows(method, v, missing, g, predictions, betas)
    rows = []
    pm, mm = _masks(present), _masks(flows)
    for name in totals.segments():
        p, m = present[pm[name]], flows[mm[name]]
        rep_c, rep_r = float(p["captc"].fillna(0).sum()), float(p["resg"].fillna(0).sum())
        if method == "scale_up":
            keys = p.groupby(["category", "fic"])[["captc", "resg"]].sum().join(
                g.set_index(["category", "fic"])["factor"], how="left")
            est_c = float((keys["captc"].fillna(0) * keys["factor"].fillna(1)).sum())
            est_r = float((keys["resg"].fillna(0) * keys["factor"].fillna(1)).sum())
        else:
            est_c, est_r = rep_c + float(m["captc"].sum()), rep_r + float(m["resg"].sum())
        rows.append({"segment": name, "method": method, "d": pd.Timestamp(v.d), "k": v.k,
                     "captc": est_c, "resg": est_r, "net": est_c - est_r,
                     "reported_captc": rep_c, "reported_resg": rep_r,
                     "present_pl": float(p["pl"].fillna(0).sum()),
                     "missing_pl": float(m["pl_last"].fillna(0).sum()),
                     "n_present": len(p), "n_missing": len(m)})
    return pd.DataFrame(rows)


def truth_sums(truth_rows: pd.DataFrame, classes: pd.DataFrame, d) -> pd.DataFrame:
    """Segment sums of the truth rows (flows.vintages.Store.truth)."""
    t = _tag(truth_rows, classes)
    masks = _masks(t)
    return pd.DataFrame([{
        "segment": name, "d": pd.Timestamp(d), "captc": float(t[m]["captc"].fillna(0).sum()),
        "resg": float(t[m]["resg"].fillna(0).sum()),
        "net": float((t[m]["captc"].fillna(0) - t[m]["resg"].fillna(0)).sum()),
        "pl": float(t[m]["pl"].fillna(0).sum()), "n": int(m.sum())}
        for name, m in masks.items()])


def targets(f: pd.DataFrame, truth_rows: pd.DataFrame) -> pd.DataFrame:
    """The missing funds' true flows as rates of their last net assets (0 when a fund never
    arrived by the truth cutoff)."""
    t = truth_rows[FUND + ["captc", "resg"]].rename(columns={"captc": "true_captc",
                                                              "resg": "true_resg"})
    out = f.merge(t, on=FUND, how="left")
    pl = out["pl_last"].fillna(0).clip(lower=1.0)
    out["y_captc"] = out["true_captc"].fillna(0) / pl
    out["y_resg"] = out["true_resg"].fillna(0) / pl
    return out


def fit(rows: pd.DataFrame, leg: str, power: float = 1.5, rounds: int = 400, seed: int = 20261001):
    """A LightGBM Tweedie model of one leg's rate, weighted by last net assets so that errors
    count in reais; the target winsorised at its 99.9th percentile."""
    import lightgbm as lgb

    y = rows[f"y_{leg}"].to_numpy(dtype=float)
    cap = np.quantile(y, 0.999)
    y = np.minimum(y, cap)
    w = rows["pl_last"].fillna(0).clip(lower=1.0).to_numpy(dtype=float)
    data = lgb.Dataset(rows[FEATURES], label=y, weight=w, categorical_feature=["category_code"],
                       free_raw_data=False)
    params = {"objective": "tweedie", "tweedie_variance_power": power, "learning_rate": 0.05,
              "num_leaves": 63, "min_data_in_leaf": 200, "feature_fraction": 0.9,
              "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1,
              "seed": seed, "num_threads": 4}
    return lgb.train(params, data, num_boost_round=rounds)


def predict(models: dict, f: pd.DataFrame) -> pd.DataFrame:
    """Predicted rates per missing fund from the two legs' models."""
    out = f[FUND].copy()
    for leg in LEGS:
        out[f"{leg}_rate_hat"] = models[leg].predict(f[FEATURES]) if len(f) else []
    return out
