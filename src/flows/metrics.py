"""Scoring the estimates: every method on the same cells, errors in reais and in basis points of
net assets, and the pre-registered skill test with a weekly block bootstrap (docs/EVAL_PLAN.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MEASURES = ["captc", "resg", "net"]
CELL = ["segment", "d", "k"]
SEED, B = 20261001, 2000


def same_cells(estimates: pd.DataFrame) -> pd.DataFrame:
    """Keep only the cells (segment, d, k) that every method has, so methods are compared on
    identical days."""
    counts = estimates.groupby(CELL)["method"].nunique()
    full = counts[counts == estimates["method"].nunique()].index
    return estimates.set_index(CELL).loc[full].reset_index()


def score(estimates: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Join estimates (method, segment, d, k, captc, resg, net, missing_pl) with truth (segment,
    d, captc, resg, net, pl); one row per cell and method with the signed errors."""
    scored = estimates.merge(truth.rename(columns={m: f"true_{m}" for m in MEASURES + ["pl"]}),
                             on=["segment", "d"], how="inner")
    for m in MEASURES:
        scored[f"err_{m}"] = scored[m] - scored[f"true_{m}"]
        scored[f"bps_{m}"] = 1e4 * scored[f"err_{m}"] / scored["true_pl"]
    return scored


def summary(scored: pd.DataFrame) -> pd.DataFrame:
    """MAE in R$ and basis points, and bias, by method, segment, k and measure."""
    rows = []
    for (method, segment, k), part in scored.groupby(["method", "segment", "k"]):
        for m in MEASURES:
            rows.append({"method": method, "segment": segment, "k": int(k), "measure": m,
                         "n": len(part), "mae_brl": float(part[f"err_{m}"].abs().mean()),
                         "mae_bps": float(part[f"bps_{m}"].abs().mean()),
                         "bias_brl": float(part[f"err_{m}"].mean())})
    return pd.DataFrame(rows)


def skill_ci(e_base: pd.Series, e_model: pd.Series, dates: pd.Series, n_boot: int = B,
             seed: int = SEED) -> tuple[float, float, float]:
    """Skill = 1 − Σ|e_model| / Σ|e_base| over paired days, with a block bootstrap by ISO week:
    the point value and the 2.5th and 97.5th percentiles."""
    e_b, e_m = np.abs(np.asarray(e_base, float)), np.abs(np.asarray(e_model, float))
    weeks = pd.to_datetime(pd.Series(dates)).dt.strftime("%G-%V").to_numpy()
    blocks = [np.flatnonzero(weeks == w) for w in np.unique(weeks)]
    point = 1 - e_m.sum() / e_b.sum()
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(blocks), len(blocks))
        idx = np.concatenate([blocks[j] for j in pick])
        draws[i] = 1 - e_m[idx].sum() / e_b[idx].sum()
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    diff = y - q
    return float(np.mean(np.maximum(tau * diff, (tau - 1) * diff)))


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    return float(np.mean((y >= lo) & (y <= hi)))
