"""Fetch with rate limiting, retry and backoff.

Every production scraper eventually hits the same three walls: a 429 that
arrives before you think you are rate limited, a 503 that clears after two
seconds, and a connection that hangs forever. Doing retry logic inline at every
call site is how you end up with three different half-correct implementations.
"""
from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FetchStats:
    attempts: int = 0
    ok: int = 0
    retries: int = 0
    failures: int = 0
    total_sleep: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.ok + self.failures
        return self.ok / total if total else 1.0


class Fetcher:
    def __init__(self, min_interval: float = 0.4, max_retries: int = 3,
                 timeout: float = 15.0, jitter: float = 0.25):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.jitter = jitter
        self.stats = FetchStats()
        self._last_call = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
            self.stats.total_sleep += wait
        self._last_call = time.monotonic()

    def get(self, url: str) -> str:
        last_err = ""
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self.stats.attempts += 1
            try:
                text = self._read(url)
                self.stats.ok += 1
                return text
            except urllib.error.HTTPError as exc:
                last_err = f"HTTP {exc.code} {url}"
                self.stats.errors.append(last_err)
                # 4xx other than 429 will not get better by retrying
                if exc.code != 429 and 400 <= exc.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_err = f"{type(exc).__name__}: {exc} ({url})"
                self.stats.errors.append(last_err)

            if attempt < self.max_retries:
                self.stats.retries += 1
                backoff = (2 ** attempt) + random.uniform(0, self.jitter)
                time.sleep(backoff)
                self.stats.total_sleep += backoff

        self.stats.failures += 1
        raise FetchError(last_err)

    def _read(self, url: str) -> str:
        if url.startswith("file://"):
            path = Path(url[len("file://"):])
            if not path.exists():
                raise OSError(f"fixture not found: {path}")
            return path.read_text(encoding="utf-8")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PricePipeline/0.4; +contact@example.com)",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")


class FetchError(RuntimeError):
    pass
