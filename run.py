#!/usr/bin/env python3
"""One capture pass.

    python run.py --day day1 --at 2026-11-01T09:00:00+00:00
    python run.py --day day2 --at 2026-11-02T09:00:00+00:00

Day 2 reads the history written by day 1 and reports what moved. The fixture
files under data/fixtures are local HTML so the whole thing runs offline; swap
`source` in targets.json for real URLs and the rest is unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.diff import build_changes, render_markdown
from pipeline.extract import extract
from pipeline.fetch import FetchError, Fetcher
from pipeline.store import PriceStore

ROOT = Path(__file__).parent


def load_targets(path: Path) -> list[dict]:
    return json.loads(path.read_text())["targets"]


def resolve(source: str) -> str:
    if "://" in source:
        return source
    return "file://" + str((ROOT / source).resolve())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="targets.json")
    ap.add_argument("--db", default="prices.db")
    ap.add_argument("--day", default="day1")
    ap.add_argument("--at", default=None, help="capture timestamp (ISO 8601)")
    ap.add_argument("--out", default=None, help="markdown report path")
    args = ap.parse_args()

    fetcher = Fetcher(min_interval=0.2)
    store = PriceStore(args.db)
    snapshots: list[dict] = []
    skipped: list[str] = []

    for t in load_targets(ROOT / args.targets):
        url = resolve(t["source"].format(day=args.day))
        try:
            html = fetcher.get(url)
        except FetchError as exc:
            skipped.append(f"{t['sku']}@{t['site']}: {exc}")
            continue
        product = extract(html, t["sku"])
        if not product:
            skipped.append(f"{t['sku']}@{t['site']}: no price found in page")
            continue
        store.record(product.sku, t["site"], product.price, product.currency,
                     product.source_layer, captured_at=args.at)
        snapshots.append({
            "sku": product.sku, "site": t["site"], "title": product.title,
            "price": product.price, "currency": product.currency,
            "layer": product.source_layer,
        })
        print(f"  {product.sku:12s} {t['site']:8s} {product.price:>9.2f} "
              f"{product.currency}  [{product.source_layer}]")

    captured_at = args.at or "now"
    changes = build_changes(store, snapshots, before=captured_at)
    report = render_markdown(changes, captured_at)

    out = ROOT / (args.out or f"reports/report-{args.day}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    st = fetcher.stats
    print(f"\nfetched {st.ok}/{st.ok + st.failures}  retries={st.retries}  "
          f"success={st.success_rate:.1%}  sleep={st.total_sleep:.1f}s")
    if skipped:
        print("skipped:")
        for s in skipped:
            print("  -", s)
    print(f"report -> {out.relative_to(ROOT)}")
    store.close()


if __name__ == "__main__":
    main()
