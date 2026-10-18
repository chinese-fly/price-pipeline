"""Tests for fetch, extract, store and diff.

All offline: fixtures live in data/fixtures and the fetcher understands
file:// URLs, which is also how the demo runs.
"""
import tempfile
import unittest
from pathlib import Path

from pipeline.diff import Change, build_changes
from pipeline.extract import extract
from pipeline.fetch import FetchError, Fetcher
from pipeline.store import PriceStore

ROOT = Path(__file__).parent.parent
FIX = ROOT / "data" / "fixtures"


class TestExtract(unittest.TestCase):
    def test_jsonld_layer(self):
        p = extract((FIX / "atlas-day1.html").read_text(), "ATLAS-14")
        self.assertIsNotNone(p)
        self.assertEqual(p.price, 1299.00)
        self.assertEqual(p.currency, "USD")
        self.assertEqual(p.source_layer, "json-ld")

    def test_microdata_fallback(self):
        p = extract((FIX / "zenith-day1.html").read_text(), "ZENITH-9")
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.price, 89.90)
        self.assertEqual(p.source_layer, "microdata")

    def test_regex_fallback(self):
        p = extract((FIX / "legacy-day1.html").read_text(), "LEGACY-3")
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.price, 349.00)
        self.assertEqual(p.source_layer, "regex")

    def test_no_price_returns_none(self):
        self.assertIsNone(extract("<html><body>nothing here</body></html>", "X"))

    def test_thousands_separator(self):
        html = '<script type="application/ld+json">{"@type":"Product","name":"X","offers":{"price":"1,299.50","priceCurrency":"USD"}}</script>'
        p = extract(html, "X")
        self.assertAlmostEqual(p.price, 1299.50)


class TestFetcher(unittest.TestCase):
    def test_reads_file_url(self):
        f = Fetcher(min_interval=0)
        html = f.get("file://" + str((FIX / "atlas-day1.html").resolve()))
        self.assertIn("Atlas", html)
        self.assertEqual(f.stats.success_rate, 1.0)

    def test_raises_after_retries(self):
        f = Fetcher(min_interval=0, max_retries=1)
        with self.assertRaises(FetchError):
            f.get("file:///nonexistent/page.html")
        self.assertEqual(f.stats.failures, 1)
        self.assertGreaterEqual(f.stats.attempts, 2)


class TestStoreAndDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.store = PriceStore(self.tmp.name)

    def tearDown(self):
        self.store.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_history_roundtrip(self):
        self.store.record("A", "s1", 10.0, "USD", "json-ld", "2026-01-01T00:00:00+00:00")
        self.store.record("A", "s1", 12.0, "USD", "json-ld", "2026-01-02T00:00:00+00:00")
        self.assertEqual(self.store.last("A", "s1")[0], 12.0)
        self.assertEqual(self.store.last("A", "s1", before="2026-01-02T00:00:00+00:00")[0], 10.0)

    def test_change_math(self):
        c = Change("A", "s1", "t", prev_price=100.0, curr_price=112.5,
                   currency="USD", layer="json-ld")
        self.assertEqual(c.direction, "up")
        self.assertAlmostEqual(c.pct, 12.5)
        self.assertAlmostEqual(c.delta, 12.5)

    def test_first_capture_has_no_delta(self):
        c = Change("A", "s1", "t", prev_price=None, curr_price=5.0,
                   currency="USD", layer="regex")
        self.assertEqual(c.direction, "new")
        self.assertIsNone(c.pct)

    def test_build_changes_reads_previous_snapshot(self):
        self.store.record("A", "s1", 100.0, "USD", "json-ld", "2026-01-01T00:00:00+00:00")
        snap = [{"sku": "A", "site": "s1", "title": "t", "price": 90.0,
                 "currency": "USD", "layer": "json-ld"}]
        changes = build_changes(self.store, snap, before="2026-01-02T00:00:00+00:00")
        self.assertEqual(changes[0].direction, "down")
        self.assertAlmostEqual(changes[0].pct, -10.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
