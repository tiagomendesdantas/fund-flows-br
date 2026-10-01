"""Find source gaps in CVM's daily report since 2021 (flows.gaps) and write data/gaps.json and
web/gaps.json (the days, for the Method page).

    uv run python scripts/gaps.py --from 202101 --to 202609
"""

from __future__ import annotations

import argparse
import json

import pandas as pd

from flows import gaps, history


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="first", default="202101")
    parser.add_argument("--to", dest="last", default="202609")
    args = parser.parse_args()
    months = history.months(args.first, args.last)
    # One year at a time with a month of margin on each side, so windows cross year ends.
    frames = []
    years = sorted({m[:4] for m in months})
    for year in years:
        span = [m for m in months if m[:4] == year]
        lo = (pd.Period(span[0], "M") - 1).strftime("%Y%m")
        hi = (pd.Period(span[-1], "M") + 1).strftime("%Y%m")
        use = [m for m in history.months(lo, hi) if m in months]
        daily = history.daily_range(use[0], use[-1], ["cnpj", "sub", "dt", "pl"])
        found = gaps.detect(daily)
        found = found[pd.to_datetime(found["dt"]).dt.year == int(year)]
        frames.append(found)
        print(year, "gap days:", int(found["gap"].sum()), flush=True)
    all_days = pd.concat(frames, ignore_index=True)
    all_days["dt"] = all_days["dt"].astype(str)
    all_days.to_json(history.DATA / "gaps.json", orient="records", indent=1)
    gap_days = all_days[all_days["gap"]]
    summary = [{"dt": r.dt, "n_gone": int(r.n_gone), "pl_share": round(float(r.pl_share), 4)}
               for r in gap_days.itertuples()]
    (history.DATA.parent / "web" / "gaps.json").write_text(json.dumps(
        {"window": gaps.WINDOW, "share": gaps.SHARE, "from": args.first, "to": args.last,
         "days": summary}, indent=1))
    print(gap_days[["dt", "n_gone", "pl_share"]].to_string(index=False))


if __name__ == "__main__":
    main()
