"""Download CVM's raw files for local analysis into data/raw/ (never committed).

    uv run python scripts/download.py --daily-from 202401 --deliveries-from 202501

A file already on disk is downloaded again only if CVM's ETag changed (kept beside it).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from flows import sources

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
REGISTER_URL = f"{sources.BASE}/CAD/DADOS/registro_fundo_classe.zip"


def fetch(url: str) -> str:
    path = RAW / url.rsplit("/", 1)[1]
    tag = path.with_suffix(".etag")
    got = sources.get(url, etag=tag.read_text() if path.exists() and tag.exists() else None)
    if got.status == 304:
        return f"{path.name}: unchanged"
    if got.status != 200:
        return f"{path.name}: HTTP {got.status}"
    path.write_bytes(got.content)
    tag.write_text(got.etag or "")
    return f"{path.name}: {len(got.content) / 1e6:.1f} MB"


def months(first: str, last: str) -> list[str]:
    return [m.strftime("%Y%m") for m in pd.period_range(pd.Period(first, "M"), pd.Period(last, "M"))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-from", default="202401")
    parser.add_argument("--deliveries-from", default="202501")
    parser.add_argument("--to", default=f"{pd.Timestamp.now():%Y%m}")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    for month in months(args.daily_from, args.to):
        print(fetch(sources.daily_url(month)), flush=True)
    for month in months(args.deliveries_from, args.to):
        print(fetch(sources.deliveries_url(month)), flush=True)
    print(fetch(REGISTER_URL), flush=True)


if __name__ == "__main__":
    main()
