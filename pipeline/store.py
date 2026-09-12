"""SQLite price history.

Deliberately not a time-series database. At a few hundred SKUs and one capture
per day the whole history fits in a few MB, and SQLite means the client can open
the file and look at it themselves — which they will ask for.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    sku         TEXT NOT NULL,
    site        TEXT NOT NULL,
    price       REAL NOT NULL,
    currency    TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    layer       TEXT NOT NULL,
    PRIMARY KEY (sku, site, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_sku_time ON prices (sku, captured_at);
"""


class PriceStore:
    def __init__(self, path: str | Path = "prices.db"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def record(self, sku: str, site: str, price: float, currency: str,
               layer: str, captured_at: str | None = None) -> None:
        ts = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?)",
            (sku, site, price, currency, ts, layer),
        )
        self.conn.commit()

    def last(self, sku: str, site: str, before: str | None = None) -> tuple[float, str] | None:
        q = "SELECT price, captured_at FROM prices WHERE sku=? AND site=?"
        args: list = [sku, site]
        if before:
            q += " AND captured_at < ?"
            args.append(before)
        q += " ORDER BY captured_at DESC LIMIT 1"
        row = self.conn.execute(q, args).fetchone()
        return (row[0], row[1]) if row else None

    def history(self, sku: str, site: str, limit: int = 30) -> list[tuple[float, str]]:
        rows = self.conn.execute(
            "SELECT price, captured_at FROM prices WHERE sku=? AND site=? "
            "ORDER BY captured_at DESC LIMIT ?",
            (sku, site, limit),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def close(self) -> None:
        self.conn.close()
