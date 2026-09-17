"""Fetch a page with a minimum interval between requests."""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path


class Fetcher:
    def __init__(self, min_interval: float = 0.4, timeout: float = 15.0):
        self.min_interval = min_interval
        self.timeout = timeout
        self._last_call = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def get(self, url: str) -> str:
        self._throttle()
        return self._read(url)

    def _read(self, url: str) -> str:
        if url.startswith("file://"):
            path = Path(url[len("file://"):])
            if not path.exists():
                raise OSError(f"fixture not found: {path}")
            return path.read_text(encoding="utf-8")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PricePipeline/0.3)",
        })
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
