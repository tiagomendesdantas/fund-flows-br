"""The backtest of the estimates under docs/EVAL_PLAN.md.

    uv run python scripts/backtest.py --dev            # 2025, the development year
    uv run python scripts/backtest.py --test --once    # 2026-01..08, scored once (Phase 4)

Every method is estimated for every scored (day, lag) from the vintage of that morning; the model
is scored out of fold (purged weekly blocks); the pre-registered decision is printed and written,
never applied by hand. Outputs go to data/backtest/<phase>/ and web/backtest_<phase>.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time as clock
from datetime import date

import numpy as np
import pandas as pd

from flows import calendar, history, intervals, metrics, nowcast, register, totals, vintages

OUT = history.DATA / "backtest"
LAGS = (2, 3, 4, 5)
POWERS = (1.3, 1.5, 1.7)
ROUNDS = 400
FOLDS = 5
SKIP_FIRST = 10          # business days of a year without enough history


def classes() -> pd.DataFrame:
    return register.combine(
        register.parse_register((history.RAW / "registro_fundo_classe.zip").read_bytes()),
        register.parse_legacy((history.RAW / "cad_fi.csv").read_bytes()))


def gap_days() -> set[date]:
    path = history.DATA / "gaps.json"
    if not path.exists():
        return set()
    return {pd.Timestamp(r["dt"]).date() for r in json.loads(path.read_text()) if r["gap"]}


def scored_days(store: vintages.Store, first: date, last: date) -> tuple[list[date], list[date]]:
    """Business days with rows in the window, minus the first SKIP_FIRST and the gap days (which
    are returned separately)."""
    days = [d for d in store.days if first <= d <= last and calendar.is_business_day(d)]
    days = days[SKIP_FIRST:]
    gaps = gap_days()
    return [d for d in days if d not in gaps], [d for d in days if d in gaps]


def build(store, days, cls, log) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Estimates of the simple methods, the truth, the hidden flags and the model rows."""
    estimates, truths, shown, rows = [], [], [], []
    t0 = clock.time()
    for i, d in enumerate(days):
        truth_rows = store.truth(d)
        truths.append(nowcast.truth_sums(truth_rows, cls, d))
        flags = totals.daily_totals(truth_rows.assign(dt=d), cls)[["segment", "shown"]]
        shown.append(flags.assign(d=pd.Timestamp(d)))
        for k in LAGS:
            v = vintages.vintage(store, d, k)
            for m in ("reported", "scale_up", "trailing"):
                estimates.append(nowcast.estimate(v, m, cls))
            f = nowcast.features(v, cls)
            if len(f):
                rows.append(nowcast.targets(f, truth_rows))
        if (i + 1) % 20 == 0:
            log(f"  {i + 1}/{len(days)} days, {clock.time() - t0:.0f}s")
    return (pd.concat(estimates, ignore_index=True), pd.concat(truths, ignore_index=True),
            pd.concat(shown, ignore_index=True), pd.concat(rows, ignore_index=True))


def folds(rows: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    """Purged weekly-block folds: contiguous blocks of ISO weeks, training rows one week away
    from the held-out block on each side."""
    weeks = pd.to_datetime(rows["d"]).dt.strftime("%G-%V")
    order = sorted(weeks.unique())
    chunk = int(np.ceil(len(order) / FOLDS))
    out = []
    for i in range(FOLDS):
        held = order[i * chunk:(i + 1) * chunk]
        if not held:
            continue
        lo, hi = order.index(held[0]), order.index(held[-1])
        purge = set(order[max(0, lo - 1):min(len(order), hi + 2)])
        test = weeks.isin(held).to_numpy()
        train = ~weeks.isin(purge).to_numpy()
        out.append((np.flatnonzero(train), np.flatnonzero(test)))
    return out


def betas_from(rows: pd.DataFrame) -> dict:
    """Per category: the slope of (true net rate − trailing net rate) on the category's reported
    net rate, weighted by net assets."""
    r = rows.dropna(subset=["cat_net_rate"]).copy()
    r["y"] = (r["y_captc"] - r["y_resg"]) - (r["captc_rate"].fillna(0) - r["resg_rate"].fillna(0))
    r["w"] = r["pl_last"].fillna(0).clip(lower=1.0)
    out = {}
    for c, part in r.groupby("category"):
        x, y, w = part["cat_net_rate"].to_numpy(), part["y"].to_numpy(), part["w"].to_numpy()
        den = float((w * x * x).sum())
        out[c] = float((w * x * y).sum() / den) if den > 0 else 0.0
    return out


def model_estimates(store, rows, cls, log) -> tuple[dict, pd.DataFrame, dict]:
    """Out-of-fold estimates for the model at each Tweedie power and for trailing_beta."""
    parts = {f"model@{p}": [] for p in POWERS} | {"trailing_beta": []}
    importance = {}
    for n, (train, test) in enumerate(folds(rows)):
        tr, te = rows.iloc[train], rows.iloc[test]
        log(f"  fold {n + 1}: {len(tr)} train rows, {len(te)} held out")
        betas = betas_from(tr)
        preds = {}
        for p in POWERS:
            models = {leg: nowcast.fit(tr, leg, power=p, rounds=ROUNDS) for leg in nowcast.LEGS}
            preds[p] = nowcast.predict(models, te).assign(d=te["d"].to_numpy(), k=te["k"].to_numpy())
            importance[p] = {leg: dict(zip(nowcast.FEATURES, models[leg].feature_importance("gain").tolist(), strict=True))
                             for leg in nowcast.LEGS}
        for (d, k), _ in te.groupby(["d", "k"]):
            v = vintages.vintage(store, pd.Timestamp(d).date(), k)
            parts["trailing_beta"].append(nowcast.estimate(v, "trailing_beta", cls, betas=betas))
            for p in POWERS:
                pk = preds[p][(preds[p]["d"] == d) & (preds[p]["k"] == k)]
                e = nowcast.estimate(v, "model", cls, predictions=pk)
                parts[f"model@{p}"].append(e.assign(method=f"model@{p}"))
    return ({k: pd.concat(v, ignore_index=True) for k, v in parts.items() if v},
            pd.DataFrame(), importance)


def decide(scored: pd.DataFrame, log) -> dict:
    """The pre-registered rule on lag-2 direct net flow."""
    cell = scored[(scored["segment"] == "direct") & (scored["k"] == 2)]
    base = cell[cell["method"] == "scale_up"].set_index("d")["err_net"]
    out = {"primary": "lag-2 direct net MAE", "n_days": len(base), "methods": {}}
    for m in sorted(cell["method"].unique()):
        e = cell[cell["method"] == m].set_index("d")["err_net"].reindex(base.index)
        point, lo, hi = metrics.skill_ci(base, e, base.index.to_series())
        out["methods"][m] = {"mae_brl": float(e.abs().mean()), "skill": point, "ci": [lo, hi]}
    models = {m: r for m, r in out["methods"].items() if m.startswith("model@")}
    best_model = max(models, key=lambda m: models[m]["skill"]) if models else None
    passes = best_model is not None and models[best_model]["skill"] >= 0.10 and models[best_model]["ci"][0] > 0
    if passes:
        default = best_model
    else:
        simple = {m: r for m, r in out["methods"].items() if m in ("scale_up", "trailing", "trailing_beta")}
        default = min(simple, key=lambda m: simple[m]["mae_brl"])
    out |= {"best_model": best_model, "model_passes": bool(passes), "default": default}
    log(f"decision: default = {default} (model passes: {passes})")
    return out


def run(phase: str, first: date, last: date, store_months: tuple[str, str]) -> None:
    out_dir = OUT / phase
    out_dir.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        print(msg, flush=True)
        with open(out_dir / "log.txt", "a") as f:
            f.write(msg + "\n")

    log(f"== {phase}: {first}..{last}, store {store_months}")
    cls = classes()
    store = vintages.Store(*store_months)
    days, gaps = scored_days(store, first, last)
    log(f"{len(days)} days scored, {len(gaps)} gap days set aside, {store.unlogged} unlogged rows")
    est, truth, shown, rows = build(store, days, cls, log)
    log(f"{len(rows)} model rows")
    extra, _, importance = model_estimates(store, rows, cls, log)
    est = pd.concat([est, *extra.values()], ignore_index=True)
    est = metrics.same_cells(est)
    scored = metrics.score(est, truth)
    scored = scored.merge(shown, on=["segment", "d"], how="left")
    scored = scored[scored["shown"] == 1]
    decision = decide(scored, log)
    summary = metrics.summary(scored)
    # Unexpected arrivals: truth minus what any expected-set method can reach.
    reach = rows.groupby(["d", "k"]).apply(lambda r: float((r["true_captc"].fillna(0) - r["true_resg"].fillna(0)).sum()), include_groups=False)
    rep = est[(est["method"] == "reported") & (est["segment"] == "all")].set_index(["d", "k"])
    tru = truth[truth["segment"] == "all"].set_index("d")["net"]
    unexpected = (tru.reindex(rep.index.get_level_values(0)).to_numpy() - rep["net"].to_numpy()
                  - reach.reindex(rep.index).fillna(0).to_numpy())
    unexpected_by_k = pd.Series(unexpected, index=rep.index).groupby(level="k").agg(["mean", "std"])
    table = intervals.calibrate(scored[scored["method"] == decision["default"]])
    with_iv = intervals.apply(scored[scored["method"] == decision["default"]], table)
    cov = {m: {"80": metrics.coverage(with_iv[f"true_{m}"].to_numpy(), with_iv[f"{m}_q10"].to_numpy(), with_iv[f"{m}_q90"].to_numpy()),
               "95": metrics.coverage(with_iv[f"true_{m}"].to_numpy(), with_iv[f"{m}_q025"].to_numpy(), with_iv[f"{m}_q975"].to_numpy())}
           for m in intervals.MEASURES}
    est.to_parquet(out_dir / "estimates.parquet", index=False)
    scored.to_parquet(out_dir / "scores.parquet", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)
    sha = hashlib.sha256((out_dir / "estimates.parquet").read_bytes()).hexdigest()[:16]
    result = {"phase": phase, "window": [str(first), str(last)], "days": len(days),
              "gap_days": [str(g) for g in gaps], "lags": list(LAGS), "cells": len(scored),
              "decision": decision, "summary": summary.to_dict("records"),
              "unexpected_net_by_k": {str(k): {"mean": float(r["mean"]), "std": float(r["std"])} for k, r in unexpected_by_k.iterrows()},
              "intervals": table, "coverage_in_sample": cov, "importance": importance,
              "estimates_sha256": sha, "run_at": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M")}
    (out_dir / "result.json").write_text(json.dumps(result, indent=1, default=str))
    (history.DATA.parent / "web" / f"backtest_{phase}.json").write_text(json.dumps(result, indent=1, default=str))
    if phase == "dev":
        intervals.save(table)
    log(f"estimates sha256 {sha}; written to {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.dev:
        run("dev", date(2025, 1, 1), date(2025, 12, 31), ("202501", "202601"))
    elif args.test:
        if (OUT / "test" / "result.json").exists():
            sys.exit("the test has been scored; it is scored once (docs/EVAL_PLAN.md)")
        plan = (history.DATA.parent / "docs" / "EVAL_PLAN.md").read_text()
        if "## Development results" not in plan or not args.once:
            sys.exit("the test runs only with --once and after the development results are in EVAL_PLAN.md")
        run("test", date(2026, 1, 1), date(2026, 8, 31), ("202512", "202609"))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
