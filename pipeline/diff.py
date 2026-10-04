"""Day-over-day price diff and report rendering.

The report deliberately leads with the *change*, not the price. A list of
current prices is something the client can get by opening the page themselves.
What they are paying for is knowing what moved while they were not looking.
"""
from __future__ import annotations

from dataclasses import dataclass

from .store import PriceStore


@dataclass
class Change:
    sku: str
    site: str
    title: str
    prev_price: float | None
    curr_price: float
    currency: str
    layer: str

    @property
    def delta(self) -> float | None:
        if self.prev_price is None:
            return None
        return round(self.curr_price - self.prev_price, 2)

    @property
    def pct(self) -> float | None:
        if not self.prev_price:
            return None
        return round((self.curr_price - self.prev_price) / self.prev_price * 100, 2)

    @property
    def direction(self) -> str:
        if self.prev_price is None:
            return "new"
        if self.curr_price > self.prev_price:
            return "up"
        if self.curr_price < self.prev_price:
            return "down"
        return "flat"


def build_changes(store: PriceStore, snapshots: list[dict], before: str) -> list[Change]:
    """snapshots: [{sku, site, title, price, currency, layer}] captured at `before`."""
    out: list[Change] = []
    for s in snapshots:
        prev = store.last(s["sku"], s["site"], before=before)
        out.append(Change(
            sku=s["sku"], site=s["site"], title=s["title"],
            prev_price=prev[0] if prev else None,
            curr_price=s["price"], currency=s["currency"], layer=s["layer"],
        ))
    out.sort(key=lambda c: (c.direction != "down", c.pct or 0))
    return out


def render_markdown(changes: list[Change], captured_at: str) -> str:
    moved = [c for c in changes if c.direction in ("up", "down")]
    lines = [
        f"# Price report — {captured_at}",
        "",
        f"{len(changes)} tracked, **{len(moved)} moved** since the previous capture.",
        "",
        "| SKU | Site | Price | Change | Layer |",
        "|---|---|---|---|---|",
    ]
    for c in changes:
        if c.direction == "new":
            change = "first capture"
        elif c.direction == "flat":
            change = "unchanged"
        else:
            arrow = "▲" if c.direction == "up" else "▼"
            change = f"{arrow} {c.pct:+.2f}% ({c.delta:+.2f})"
        cur = f"{c.curr_price:.2f} {c.currency}"
        lines.append(f"| {c.sku} | {c.site} | {cur} | {change} | {c.layer} |")

    alerts = [c for c in changes if c.direction == "up" and (c.pct or 0) >= 5]
    if alerts:
        lines += ["", "## Alerts (increase ≥ 5%)", ""]
        for c in alerts:
            lines.append(
                f"- **{c.sku}** on {c.site}: {c.prev_price:.2f} → {c.curr_price:.2f} "
                f"{c.currency} ({c.pct:+.2f}%)"
            )

    degraded = [c for c in changes if c.layer != "json-ld"]
    if degraded:
        lines += ["", "## Extraction health", ""]
        for c in degraded:
            lines.append(
                f"- {c.sku} on {c.site} resolved via `{c.layer}` instead of "
                "JSON-LD; worth checking whether the structured data was dropped."
            )
    return "\n".join(lines) + "\n"
