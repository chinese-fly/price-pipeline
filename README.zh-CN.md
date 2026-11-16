# price-pipeline

[English](README.md) | 简体中文

定时价格采集：分层提取、失败重试与退避、SQLite 历史记录，以及一份把「什么变了」放在最前面的逐日对比报告。

```bash
python run.py --day day1 --at 2026-11-01T09:00:00+00:00
python run.py --day day2 --at 2026-11-02T09:00:00+00:00
cat reports/report-day2.md
python -m unittest      # 11 tests, ~1s
```

零第三方依赖。Python 3.10+。

---

## 这个项目解决什么问题

客户在跟十几个竞品店铺拼价格，原来靠一个人每天早上手动看一遍，把价格抄进表格。有两种失效方式让这件事变得很贵：

1. **人工读取的价格是滞后的。** 竞品早上 8 点降价，客户 10 点才知道 —— 而这一天的订单已经按旧价格发出去了。
2. **提取坏掉的时候没人发现。** 改版之后，脚本默默把昨天的数字当成今天的返回，报告看起来一切正常。这一种才是贵的 —— 看起来健康、实际有问题的数据。

第二个问题，正是分层提取和健康度章节存在的理由。

---

## 提取是分层的，并且会记录哪一层命中

顺序：**JSON-LD → microdata → 正则**。

JSON-LD 是机器可读的，由站点所有者维护（因为 Google 要读它），而且能扛住改版。CSS 选择器则每逢营销团队上线新布局就挂一次。优先抓 CSS 的选择，是一笔每个月都要重新付一次的账。

每个抓到的价格都会记录它来自哪一层，报告会把所有非 JSON-LD 来源的项单独列出来：

```
## Extraction health

- LEGACY-3 on legacy resolved via `regex` instead of JSON-LD; worth checking
  whether the structured data was dropped.
- ZENITH-9 on zenith resolved via `microdata` instead of JSON-LD; worth checking
  whether the structured data was dropped.
```

这一节，就是「数字错了」和「数字错了，而且我们知道为什么」之间的区别。在一个 12 站点的管线上，图层静默降级，正是你连续三周报告过期价格的方式。

---

## 实际输出

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

注意排序。降价的排在最前面 —— 竞品砍价是客户必须在第一行看到的事，不是第三行。

---

## 抓取行为

`pipeline/fetch.py` 处理生产环境里真正会发生的三件事：

- **节流（Throttling）** —— 请求之间的最小间隔，按 fetcher 实例强制执行，这样加一个目标不会变成一次突发。
- **退避（Backoff）** —— 指数退避 + 抖动（`2^attempt + rand(0, 0.25)`），因为上百个客户端整齐划一地重试，跟一次攻击没什么区别。
- **不可重试的错误** —— 404 或 403 不会在第二次尝试时变成 200。只有 429 和 5xx 才重试。

`FetchStats` 会报告尝试次数、重试次数、成功率和总睡眠时长，`run.py` 每轮都打印一次。如果成功率从 100% 开始漂移，那就是上游有东西变了的最早信号。

---

## 目录结构

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

fixture 是三个合成商品页，每个对应一种提取层，各有两种价格状态 —— 这就是为什么全新 clone 下来，`day1` → `day2` 也能复现。

---

## 它不做什么

明确写出来，因为一个吹过头的爬虫比一个小而准的爬虫更糟：

1. **没有代理轮换，没有反爬处理。** 如果目标站主动封锁自动化访问，这条管线会如实报告失败 —— 它不会装作没事。加轮换住宅代理是对抓取层的实质改造，不是一个配置开关。
2. **没有 JS 渲染。** 客户端渲染的价格需要 Playwright。加上它会让每个目标的内存开销成倍增加，并把失败模式从「解析错误」变成「超时」，所以这是刻意的取舍，不是疏漏。
3. **单进程。** 12 个站点，这样是对的。500 个站点就需要队列和 worker 池。
4. **不处理货币换算。** 价格按原币种存储、按原币种报告。把不同币种混进一个汇总数字，就是做出一个没人会信的报表的方式。

## 用在真实站点上

把 `targets.json` 里的 `source` 换成真实 URL：

```json
{"sku": "ATLAS-14", "site": "atlas", "source": "https://atlas.example/products/atlas-14"}
```

其他都不用改 —— 抓取层已经处理 `http(s)://`，提取器也不关心 HTML 从哪来。只指向你自己拥有、或被允许监控的页面。
