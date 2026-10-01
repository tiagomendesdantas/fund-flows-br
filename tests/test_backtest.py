from __future__ import annotations

from datetime import date, time

import numpy as np
import pandas as pd
import pytest

from flows import calendar, gaps, history, intervals, metrics, nowcast, vintages

UTC3 = pd.Timedelta(hours=3)


def at_local(stamp: str) -> pd.Timestamp:
    """A Brasília time as the naive-UTC instant the store uses."""
    return pd.Timestamp(stamp) + UTC3


def fund_days(rows: list[tuple]) -> pd.DataFrame:
    """rows: (cnpj, sub, dt, pl, captc, resg, kind)."""
    return pd.DataFrame([{"kind": k, "cnpj": c, "sub": s, "dt": pd.Timestamp(d).date(), "total": pl,
                          "quota": 1.0, "pl": pl, "captc": ca, "resg": re, "cotst": 1.0}
                         for c, s, d, pl, ca, re, k in rows])


def log(rows: list[tuple]) -> pd.DataFrame:
    """rows: (cnpj, sub, dt, first_at local, active)."""
    return pd.DataFrame([{"cnpj": c, "sub": s, "dt": pd.Timestamp(d).date(), "kind": "CLASSES - FIF",
                          "first_at": at_local(f), "last_at": at_local(f), "n_resub": 0, "active": a}
                         for c, s, d, f, a in rows])


@pytest.fixture
def store(monkeypatch):
    """Three business days, 28–30 Sept 2026, with every case the rule must handle."""
    daily = {"202609": fund_days([
        (1, "", "2026-09-28", 100.0, 5.0, 0.0, "CLASSES - FIF"),
        (1, "", "2026-09-29", 100.0, 1.0, 0.0, "CLASSES - FIF"),   # delivered 00:30, in
        (2, "", "2026-09-28", 50.0, 0.0, 2.0, "CLASSES - FIF"),
        (2, "", "2026-09-29", 50.0, 0.0, 1.0, "CLASSES - FIF"),    # delivered 00:53, out
        (3, "", "2026-09-28", 20.0, 0.0, 0.0, "CLASSES - FIF"),
        (3, "", "2026-09-29", 20.0, 0.0, 0.0, "CLASSES - FIF"),    # inactive, out
        (4, "", "2026-09-29", 10.0, 0.0, 0.0, "CLASSES FIIM"),     # never in the file
        (5, "S1", "2026-09-28", 30.0, 0.0, 0.0, "CLASSES - FIF"),
        (5, "S1", "2026-09-29", 30.0, 3.0, 0.0, "CLASSES - FIF"),  # resubmission only
        (6, "", "2026-09-28", 40.0, 0.0, 0.0, "CLASSES - FIF"),   # 28th delivered late: never known
    ])}
    logs = {"202609": log([
        (1, "", "2026-09-28", "2026-09-29 10:00", 1), (1, "", "2026-09-29", "2026-10-01 00:30", 1),
        (2, "", "2026-09-28", "2026-09-29 10:00", 1), (2, "", "2026-09-29", "2026-10-01 00:53", 1),
        (3, "", "2026-09-28", "2026-09-29 10:00", 1), (3, "", "2026-09-29", "2026-09-30 10:00", 0),
        (4, "", "2026-09-29", "2026-09-30 10:00", 1),
        (5, "S1", "2026-09-28", "2026-09-29 10:00", 1), (5, "S1", "2026-09-29", "2026-09-30 09:00", 1),
        (6, "", "2026-09-28", "2026-10-03 10:00", 1),
    ])}
    monkeypatch.setattr(history, "daily", lambda m: daily[m])
    monkeypatch.setattr(history, "deliveries", lambda m: logs[m])
    return vintages.Store("202609", "202609")


def test_the_file_of_a_morning_holds_what_was_delivered_before_its_cutoff(store):
    known = store.known_at(date(2026, 10, 1), date(2026, 9, 29), date(2026, 9, 29))
    assert sorted(known["cnpj"]) == [1, 5]          # 00:30 in; 00:53, inactive, FIIM out
    later = store.known_at(date(2026, 10, 1), date(2026, 9, 29), date(2026, 9, 29), time(3, 0))
    assert sorted(later["cnpj"]) == [1, 2, 5]
    assert store.unlogged == 0


def test_the_expected_set_and_last_known_values_come_from_the_vintage(store):
    v = vintages.vintage(store, date(2026, 9, 29), 2)
    assert sorted(v.present["cnpj"]) == [1, 5]
    missing = v.missing.set_index("cnpj")
    assert sorted(missing.index) == [2, 3]          # seen on the 28th, not in by the cutoff
    assert 6 not in missing.index                   # its 28th row was delivered after the cutoff
    assert missing.loc[2, "pl_last"] == 50.0 and missing.loc[2, "days_since_seen"] == 1
    assert v.expected_pl == 100.0 + 50.0 + 20.0 + 30.0


def test_shift_and_truth_window():
    assert calendar.shift(date(2026, 9, 4), 1) == date(2026, 9, 8)       # over the 7 Sept holiday
    assert calendar.shift(date(2026, 10, 3), 1) == date(2026, 10, 5)     # Saturday
    assert calendar.shift(date(2026, 9, 30), -1) == date(2026, 9, 29)
    assert vintages.cutoff(date(2026, 10, 1)) == pd.Timestamp("2026-10-01 03:52")


@pytest.mark.skipif(not (history.PARQUET / "daily_202609.parquet").exists()
                    or not (history.PARQUET / "deliveries_202609.parquet").exists(),
                    reason="local caches absent")
def test_the_rule_reproduces_the_published_file_of_2026_10_01():
    s = vintages.Store("202609", "202609")
    counts = s.known_at(date(2026, 10, 1), date(2026, 9, 28), date(2026, 9, 30)
                        ).groupby("dt").size()
    assert counts.to_dict() == {pd.Timestamp("2026-09-28"): 25113, pd.Timestamp("2026-09-29"): 20932,
                                pd.Timestamp("2026-09-30"): 59}


def test_a_multi_day_hole_is_a_gap_and_small_or_final_absences_are_not():
    days = calendar.business_days(date(2026, 1, 2), date(2026, 1, 30))
    rows = []
    for d in days:
        for c in range(1, 21):
            if c == 1 and date(2026, 1, 13) <= d <= date(2026, 1, 16):
                continue                                   # the big fund is away four days
            if c == 2 and d == date(2026, 1, 20):
                continue                                   # a small fund misses one day
            if c == 3 and d >= date(2026, 1, 26):
                continue                                   # a fund that stops for good
            rows.append((c, "", d, 1000.0 if c == 1 else 10.0, 0.0, 0.0, "CLASSES - FIF"))
    found = gaps.detect(fund_days(rows)).set_index("dt")
    flagged = [d.isoformat() for d in found.index[found["gap"]]]
    assert flagged == ["2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16"]
    assert found.loc[date(2026, 1, 20), "n_gone"] == 1 and not found.loc[date(2026, 1, 20), "gap"]
    assert found.loc[date(2026, 1, 28), "n_gone"] == 0


def classes_for(cnpjs: list[int], category: str = "Renda Fixa") -> pd.DataFrame:
    return pd.DataFrame({"cnpj": cnpjs, "category": category, "fic": 0, "exclusive": 0})


def test_every_method_equals_the_truth_when_nothing_is_missing(store):
    v = vintages.vintage(store, date(2026, 9, 29), 2)
    v.missing = v.missing.iloc[0:0]
    classes = classes_for([1, 2, 3, 5])
    truth = nowcast.truth_sums(v.present, classes, v.d).set_index("segment")
    for m in ("reported", "scale_up", "trailing"):
        e = nowcast.estimate(v, m, classes).set_index("segment")
        assert e.loc["direct", "net"] == pytest.approx(truth.loc["direct", "net"])
        assert e.loc["direct", "missing_pl"] == 0


def test_scale_up_divides_by_the_share_present_and_a_ceased_fund_targets_zero(store):
    v = vintages.vintage(store, date(2026, 9, 29), 2)
    classes = classes_for([1, 2, 3, 5])
    e = nowcast.estimate(v, "scale_up", classes).set_index("segment")
    reported = 1.0 + 3.0                                   # funds 1 and 5 subscriptions
    share = (100.0 + 30.0) / (100.0 + 30.0 + 50.0 + 20.0)  # present PL over expected PL
    assert e.loc["direct", "captc"] == pytest.approx(reported / share)
    f = nowcast.features(v, classes)
    t = nowcast.targets(f, store.truth(v.d)).set_index("cnpj")
    assert t.loc[3, "y_captc"] == 0 and t.loc[3, "y_resg"] == 0     # inactive: not in the truth


def test_skill_interval_covers_zero_for_identical_errors_and_is_deterministic():
    dates = pd.date_range("2025-01-06", periods=60, freq="B")
    e = pd.Series(np.abs(np.random.default_rng(1).normal(size=60)))
    point, lo, hi = metrics.skill_ci(e, e, dates, n_boot=200)
    assert point == 0 and lo <= 0 <= hi
    again = metrics.skill_ci(e, e * 0.5, dates, n_boot=200)
    assert again == metrics.skill_ci(e, e * 0.5, dates, n_boot=200) and again[0] == pytest.approx(0.5)


def test_same_cells_drops_cells_a_method_lacks():
    est = pd.DataFrame({"segment": ["direct"] * 3, "d": [1, 1, 2], "k": [2, 2, 2],
                        "method": ["a", "b", "a"]})
    assert metrics.same_cells(est)["d"].tolist() == [1, 1]


def test_intervals_cover_the_fitted_residuals_at_the_stated_rates():
    rng = np.random.default_rng(2)
    n = 400
    scored = pd.DataFrame({"d": pd.date_range("2025-01-06", periods=n, freq="B"),
                           "missing_pl": 1e9, "captc": 0.0, "resg": 0.0, "net": 0.0})
    for m in intervals.MEASURES:
        scored[f"err_{m}"] = rng.normal(size=n) * 1e7
    table = intervals.calibrate(scored)
    truth = scored.assign(**{f"true_{m}": -scored[f"err_{m}"] for m in intervals.MEASURES})
    out = intervals.apply(scored, table)
    cov = metrics.coverage(truth["true_net"].to_numpy(), out["net_q10"].to_numpy(),
                           out["net_q90"].to_numpy())
    assert 0.76 <= cov <= 0.84
