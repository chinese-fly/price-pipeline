# price-pipeline

English | [简体中文](README.zh-CN.md)

Scheduled price collection with layered extraction, retry/backoff, SQLite history, and a day-over-day report that leads with what moved.

```bash
python run.py --day day1 --at 2026-11-01T09:00:00+00:00
python run.py --day day2 --at 2026-11-02T09:00:00+00:00
cat reports/report-day2.md
python -m unittest      # 11 tests, ~1s
```

No third-party dependencies. Python 3.10+.

---

## The problem this solves

The client sells against a dozen competitor storefronts and had one person checking them by hand every morning, copying prices into a spreadsheet. Two failure modes made that expensive:

1. **Manually-read prices are late.** A competitor drops a price at 08:00 and the client finds out at 10:00, after the morning's orders have gone out at the old price.
2. **Nobody notices when the extraction breaks.** A redesign silently returns yesterday's number as if it were today's, and the report looks fine. This is the expensive one — bad data that looks healthy.

The second problem is why the extraction layers and the health section exist.

---

## Extraction is layered, and it records which layer won

Order: **JSON-LD → microdata → regex**.

JSON-LD is machine-readable, maintained by the site owner because Google reads it, and survives redesigns. CSS selectors break every time marketing ships a new layout. Scraping CSS-first is a decision you re-pay for monthly.

Every captured price records the layer that produced it, and the report surfaces anything that did not come from JSON-LD:

```
## Extraction health

- LEGACY-3 on legacy resolved via `regex` instead of JSON-LD; worth checking
  whether the structured data was dropped.
- ZENITH-9 on zenith resolved via `microdata` instead of JSON-LD; worth checking
  whether the structured data was dropped.
```

That section is the difference between "the number is wrong" and "the number is wrong and we can see why". On a 12-site pipeline, a silent layer shift is how you end up reporting a stale price for three weeks.

---

## Actual output

```
$ python run.py --day day1 --at 2026-11-01T09:00:00+00:00
  ATLAS-14     atlas      1299.00 USD  [json-ld]
  ZENITH-9     zenith       89.90 USD  [microdata]
  LEGACY-3     legacy      349.00 USD  [regex]

fetched 3/3  retries=0  success=100.0%  sleep=0.4s

$ python run.py --day day2 --at 2026-11-02T09:00:00+00:00
  ATLAS-14     atlas      1099.00 USD  [json-ld]
  ZENITH-9     zenith       94.90 USD  [microdata]
  LEGACY-3     legacy      349.00 USD  [regex]

fetched 3/3  retries=0  success=100.0%  sleep=0.4s
```

```markdown
# Price report — 2026-11-02T09:00:00+00:00

3 tracked, **2 moved** since the previous capture.

| SKU | Site | Price | Change | Layer |
|---|---|---|---|---|
| ATLAS-14 | atlas | 1099.00 USD | ▼ -15.40% (-200.00) | json-ld |
| LEGACY-3 | legacy | 349.00 USD | unchanged | regex |
| ZENITH-9 | zenith | 94.90 USD | ▲ +5.56% (+5.00) | microdata |

## Alerts (increase ≥ 5%)

- **ZENITH-9** on zenith: 89.90 → 94.90 USD (+5.56%)
```

Note the ordering. Rows sort so decreases come first — a competitor cutting price is the thing the client needs to see in the first line, not the third.

---

## Fetch behaviour

`pipeline/fetch.py` handles the three things that actually happen in production:

- **Throttling** — a minimum interval between requests, enforced per fetcher instance, so adding a target does not turn into a burst.
- **Backoff** — exponential with jitter (`2^attempt + rand(0, 0.25)`), because a hundred clients retrying in lockstep is indistinguishable from an attack.
- **Non-retryable errors** — a 404 or 403 is not going to become a 200 on the second try. Only 429 and 5xx retry.

`FetchStats` reports attempts, retries, success rate and total sleep, and `run.py` prints it every pass. If success rate drifts from 100%, that is the earliest signal something upstream changed.

---

## Layout

```
pipeline/
  fetch.py     throttled fetch, jittered backoff, per-run stats
  extract.py   JSON-LD → microdata → regex, records winning layer
  store.py     SQLite history, indexed on (sku, captured_at)
  diff.py      change calculation + markdown report
run.py         one capture pass
targets.json   watched SKUs; http(s) or repo-relative fixtures
data/fixtures  local HTML so the demo runs with no network
tests/         11 tests, offline
```

The fixtures are three synthetic product pages, one per extraction layer, in two price states — that is what makes `day1` → `day2` reproducible on a fresh clone.

---

## What it does not do

Being explicit about this, because a scraper that overclaims is worse than a small one:

1. **No proxy rotation, no anti-bot handling.** If a target actively blocks automated access, this pipeline will report failures — it will not pretend otherwise. Adding rotating residential proxies is a real change to the fetch layer, not a config flag.
2. **No JS rendering.** Playwright would be needed for client-side-rendered prices. Adding it multiplies memory per target and changes the failure mode from "parse error" to "timeout", so it is a deliberate omission rather than an oversight.
3. **Single-process.** For 12 sites this is right. At 500 it needs a queue and a worker pool.
4. **Currency conversion is not handled.** Prices are stored with their native currency and reported as such. Mixing currencies in one aggregate number is how you get a report nobody trusts.

## Using it against real sites

Replace `source` in `targets.json` with a real URL:

```json
{"sku": "ATLAS-14", "site": "atlas", "source": "https://atlas.example/products/atlas-14"}
```

Nothing else changes — the fetch layer already handles `http(s)://`, and the extractor does not care where the HTML came from. Point it only at pages you own or are permitted to monitor.
