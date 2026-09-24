"""Price extraction with a layered strategy.

Order matters. JSON-LD is machine-readable, stable across redesigns and
maintained by the site owner because search engines read it. CSS selectors are
what breaks every time marketing ships a redesign. Scraping CSS first is a
decision you re-pay for monthly.

So: JSON-LD -> microdata -> semantic regex. The first layer that yields a
price wins, and the layer used is recorded so a shift shows up in the reports
before it shows up as a wrong number.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

_PRICE_RE = re.compile(r"[\d][\d,.\s]*")


@dataclass
class Product:
    sku: str
    title: str
    price: float
    currency: str
    source_layer: str


class _MicrodataParser(HTMLParser):
    """Collects [itemprop=price] content and the enclosing title."""

    def __init__(self) -> None:
        super().__init__()
        self.price: str | None = None
        self.currency: str | None = None
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("itemprop") == "price" and a.get("content"):
            self.price = a["content"]
        if a.get("itemprop") == "priceCurrency" and a.get("content"):
            self.currency = a["content"]
        if tag == "h1":
            self._in_title = True

    def handle_data(self, data):
        if self._in_title and data.strip():
            self.title = data.strip()
            self._in_title = False

    def handle_endtag(self, tag):
        if tag == "h1":
            self._in_title = False


def _parse_price(raw: str) -> float | None:
    cleaned = raw.replace(",", "").strip()
    m = _PRICE_RE.search(cleaned)
    if not m:
        return None
    try:
        return float(m.group(0).replace(" ", ""))
    except ValueError:
        return None


def _from_jsonld(html: str, sku: str) -> Product | None:
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.S | re.I,
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict) or node.get("@type") != "Product":
                continue
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = _parse_price(str(offers.get("price", "")))
            if price is None:
                continue
            return Product(
                sku=sku,
                title=str(node.get("name", "")).strip(),
                price=price,
                currency=str(offers.get("priceCurrency", "USD")),
                source_layer="json-ld",
            )
    return None


def _from_microdata(html: str, sku: str) -> Product | None:
    p = _MicrodataParser()
    p.feed(html)
    if not p.price:
        return None
    price = _parse_price(p.price)
    if price is None:
        return None
    return Product(sku, p.title or sku, price, p.currency or "USD", "microdata")


def _from_regex(html: str, sku: str) -> Product | None:
    m = re.search(r'data-price=["\']([\d.,]+)["\']', html)
    if not m:
        m = re.search(r'"price"\s*:\s*"?([\d.,]+)"?', html)
    if not m:
        return None
    price = _parse_price(m.group(1))
    if price is None:
        return None
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    return Product(sku, (title.group(1).strip() if title else sku), price, "USD", "regex")


def extract(html: str, sku: str) -> Product | None:
    for layer in (_from_jsonld, _from_microdata, _from_regex):
        product = layer(html, sku)
        if product:
            return product
    return None
