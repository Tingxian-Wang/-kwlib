# kwlib

**跨境选品的关键词库，公开查询。** 零依赖 Python 客户端 + 命令行，查一个词在俄罗斯电商站内有多少人搜、多少卖家、加购率多少、最近在涨还是在跌。

数据我们自己爬、自己存、每天更新一次。这个仓库开源的是**查询端**：客户端、命令行和接口契约。

```
$ python -m kwlib lookup румяна
q       count  sellers  add_to_cart  orders  gmv     avg_price  change  last
------  -----  -------  -----------  ------  ------  ---------  ------  ----------
румяна  31915  15       34.1         1911    580605  663        3       2026-10-12
```

---

## 它和别的关键词工具不一样的地方

不是功能多，是**不乱给你数**。三条规矩写在接口里，客户端改不了：

**1. 查不到 = 没查过，不等于没量。**
`lookup()` 查不到返回 `None`，**不返回 0**。0 会被读成"这个词没人搜"，于是你放弃一个其实是没人量过的词。缺数据和零是两件事，这个库不帮你把两件事混成一件。

**2. 每个数都带日期。**
`Word.last` 是最后一次量到它的日子，`Word.stale_days` 直接告诉你旧了几天。库里一定有你上个月查的词 —— 三十天前的热度和昨天的不该平起平坐。接口从来没有裸数字。

**3. 服务挂了就说挂了。**
词库没就绪抛 `NotReady`（503），**不给你空列表**。空列表长得太像"这些词都没量"。

顺带一个：`search()` 返回的 `total` 是库里匹配的总数，`returned` 是这次真给了几条 —— 这两个数不合并，合并了就会把"我分页了"读成"市场就这么大"。

---

## 装

```bash
git clone https://github.com/Tingxian-Wang/-kwlib.git
cd kwlib
pip install -e .
```

零依赖，Python 3.9+。

## 用

```bash
python -m kwlib stats                          # 库多大、数据是哪天的
python -m kwlib lookup румяна                  # 精确查
python -m kwlib search румян --limit 20        # 按词根找近义词
python -m kwlib search румян --sort ca         # 按加购率排
python -m kwlib history румяна                 # 序列（周粒度）
python -m kwlib top --limit 50                 # 全库热度榜
python -m kwlib search румян --json            # 喂给别的程序
```

```python
from kwlib import Client

c = Client()                    # 匿名查，不用注册
w = c.lookup("румяна")

if w is None:
    print("库里没有这个词 —— 是没查过，不是没量")
else:
    print(w.count, w.sellers, w.add_to_cart, w.last)
    if w.stale_days > 30:
        print("这个数已经 %d 天了，只能当参考" % w.stale_days)
```

选品时通常这么用：**别只查一个词**。先 `search(词根)` 把一族词拉出来，按 `add_to_cart`（加购率）排。

但加购率**必须配热度下限**：只有 5 次搜索的词也能有 100% 加购率，那不是机会，是小样本噪音。所以排 `ca` 时要带 `min_count`：

```python
r = c.search("румян", min_count=200, sort="ca")   # 少这个下限，排前面的全是噪音
```

---

## 接口

基址 `https://yunlinghanyin.cn/api/kwlib`，全部 GET，全部只读。

| 端点 | 参数 | 给你什么 |
|---|---|---|
| `/stats` | — | 词数、快照数、数据日、导出时间 |
| `/lookup` | `q` | 一个词；`known:false` = 没查过 |
| `/search` | `q` `limit` `min_c` `sort` | 词根匹配；`sort` = `c` 热度 / `ca` 加购率 / `chg` 变化 |
| `/history` | `q` | 时间序列；少于两点就没有 |
| `/top` | `limit` `min_c` | 全库热度榜 |

字段口径、错误码、限速规则见 [PROTOCOL.md](PROTOCOL.md)。

**限速**：匿名每 IP 60 次/分钟。要跑批就去平台申请一把 API key（默认 2000 次/天，每分钟 120 次），带上 `X-Api-Key` 就不占公共额度。

---

## 数据从哪来，多久新一次

俄罗斯电商后台的选品分析里按词族抓的站内数据，**每天凌晨跑 40 个词族，一周把整库刷一轮** —— 所以是周粒度的时间序列，不是实时。每个数都记着它是什么时候量到的，这一点没法糊弄，也不打算糊弄。

现在库里有 4.7 万个词、360 多份快照。

## 不在这里的东西

- **爬虫不开源**：它要浏览器登录态，给出去也跑不起来。
- **原始全量数据不在这里**：爬取成本是我们的，这个仓库给的是查询能力。要批量导出，走 API。

## 许可

MIT。用得上就用，改了就改，别拿它去骗人。

---

## English

**A keyword library for cross-border sellers, open to query.** Zero-dependency Python client + CLI over a public read-only API of Russian marketplace search data: search volume, seller count, add-to-cart rate, and week-granularity history.

```python
from kwlib import Client
c = Client()
w = c.lookup("румяна")          # None means "never measured", not "zero demand"
```

Three rules are baked into the API: missing data is never returned as `0`; every number carries the date it was measured; an unavailable service raises instead of returning an empty list. Details in [PROTOCOL.md](PROTOCOL.md). MIT licensed.
