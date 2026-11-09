# -*- coding: utf-8 -*-
"""kwlib 客户端 —— 只用标准库，一个文件就能读明白。

三条口径决定了这个库的形状（详见 PROTOCOL.md）：

1. **库里没有的词 = 没查过，不等于没量。**
   所以 `lookup()` 查不到时返回 `None`，**不返回 0**。
   `None` 是"我们没有它的数据"，`Word(count=0)` 才是"它没人搜" —— 这两件事不一样。

2. **每个数都带日期。** `Word.last` 是最后一次量到的日子；
   `Word.stale_days` 告诉你这个数有多旧。三十天前的数和昨天的数不能平起平坐。

3. **服务不可用就是不可用。** 库没就绪时抛 `NotReady`，不是给你一个空列表
   —— 空列表会被读成"这些词都没量"。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterator, List, Optional, Sequence

__all__ = [
    "Client", "Word", "Point", "SearchResult",
    "KwlibError", "BadRequest", "AuthError", "RateLimited", "NotReady", "ServerError",
    "DEFAULT_BASE",
]

DEFAULT_BASE = "https://yunlinghanyin.cn"
USER_AGENT = "kwlib-python/1.0"
MAX_Q = 80          # 服务端同一条限制：查询词 ≤ 80 字符
MAX_LIMIT = 100     # 单次最多返回 100 条


# ── 异常 ────────────────────────────────────────────────────────────────
class KwlibError(Exception):
    """所有异常的基类。`status` 是 HTTP 状态码；网络层失败时为 None。"""

    status: Optional[int] = None

    def __init__(self, message: str, status: Optional[int] = None,
                 url: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.url = url
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - 只是好看点
        bits = [self.message]
        if self.status is not None:
            bits.append("[HTTP %s]" % self.status)
        if self.detail:
            bits.append(self.detail)
        if self.url:
            bits.append(self.url)
        return " ".join(b for b in bits if b)


class BadRequest(KwlibError):
    """参数不对（400）。"""


class AuthError(KwlibError):
    """钥无效 / 已撤销 / 账号不可用（401、403）。

    🔴 带了钥但钥无效时服务端会直接 401，**不会退回匿名额度** ——
    否则你会以为在花自己的额度，实际在花公共的。
    """


class RateLimited(KwlibError):
    """查得太快（429）。匿名每 IP 60 次/分钟；带钥每把钥 120 次/分钟。"""


class NotReady(KwlibError):
    """词库未就绪（503）。**不等于**查不到 —— 这时候任何词都"没数据"。"""


class ServerError(KwlibError):
    """服务端 5xx。"""


_STATUS_MAP = {400: BadRequest, 401: AuthError, 403: AuthError,
               429: RateLimited, 503: NotReady}


def _error_for(status: int, message: str, url: str, detail: str) -> KwlibError:
    cls = _STATUS_MAP.get(status) or (ServerError if status >= 500 else KwlibError)
    return cls(message, status=status, url=url, detail=detail)


# ── 数据 ────────────────────────────────────────────────────────────────
def normalize(q: str) -> str:
    """和服务器同一套归一：小写 + 单空格。查之前先归一，客户端缓存才和库里对得上。"""
    return " ".join((q or "").split()).lower()


def _may(value: Any) -> Any:
    return None if value is None or value == "" else value


def _pick(d: Dict[str, Any], *names: str) -> Any:
    """服务端缩写（ca/ord/avg/chg）和本库的长名（add_to_cart/orders/…）都认。

    这样 `Word.as_dict()` 存成 JSON 再 `Word.from_dict()` 读回来是同一个对象。
    """
    for n in names:
        if n in d:
            return _may(d[n])
    return None


@dataclass(frozen=True)
class Word:
    """一个词在最后一次被量到时的样子。

    注意 `count` 可能是 None —— 意思是"这一列没采到"，**不是 0**。
    """

    q: str
    count: Optional[int] = None          # 搜索热度（7 天口径）
    sellers: Optional[int] = None        # 卖家数
    add_to_cart: Optional[float] = None  # 加购率 %（无量的品类里这个比热度有用）
    orders: Optional[int] = None         # 下单买家数
    gmv: Optional[int] = None            # 成交额
    avg_price: Optional[float] = None    # 客单价
    date: Optional[str] = None           # 快照日
    last: Optional[str] = None           # 最后一次量到的日子
    n: Optional[int] = None              # 被查过几次
    prev: Optional[int] = None           # 上一次的热度
    change: Optional[float] = None       # 相对上次变化 %
    peak: Optional[int] = None           # 历史最高（只在当前不是最高时有值）

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Word":
        return cls(q=d.get("q") or "",
                   count=_pick(d, "count"), sellers=_pick(d, "sellers"),
                   add_to_cart=_pick(d, "add_to_cart", "ca"),
                   orders=_pick(d, "orders", "ord"),
                   gmv=_pick(d, "gmv"), avg_price=_pick(d, "avg_price", "avg"),
                   date=_pick(d, "date"), last=_pick(d, "last"),
                   n=_pick(d, "n"), prev=_pick(d, "prev"),
                   change=_pick(d, "change", "chg"), peak=_pick(d, "peak"))

    @property
    def stale_days(self) -> Optional[int]:
        """这个数离今天几天。解析不了就 None —— **不要**拿它当 0。"""
        if not self.last:
            return None
        try:
            y, m, d = (int(x) for x in self.last.split("-"))
            return (date.today() - date(y, m, d)).days
        except (ValueError, TypeError):
            return None

    def as_dict(self) -> Dict[str, Any]:
        return {"q": self.q, "count": self.count, "sellers": self.sellers,
                "add_to_cart": self.add_to_cart, "orders": self.orders,
                "gmv": self.gmv, "avg_price": self.avg_price,
                "date": self.date, "last": self.last, "n": self.n,
                "prev": self.prev, "change": self.change, "peak": self.peak}


@dataclass(frozen=True)
class Point:
    """时间序列上的一个点（一天）。"""

    date: str
    count: Optional[int] = None
    sellers: Optional[int] = None
    add_to_cart: Optional[float] = None
    orders: Optional[int] = None
    gmv: Optional[int] = None
    avg_price: Optional[float] = None


class SearchResult(Sequence[Word]):
    """词根搜索的结果。

    `total` 是**库里匹配的总数**，`returned` 是这次真的给了几条 —— 这两个数不一样，
    别把 `returned` 当市场容量。
    """

    __slots__ = ("q", "total", "returned", "items")

    def __init__(self, q: str, total: int, returned: int, items: List[Word]) -> None:
        self.q = q
        self.total = total
        self.returned = returned
        self.items = items

    def __iter__(self) -> Iterator[Word]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i):  # type: ignore[override]
        return self.items[i]

    def __repr__(self) -> str:
        return "SearchResult(q=%r, total=%d, returned=%d)" % (
            self.q, self.total, self.returned)


# ── 客户端 ──────────────────────────────────────────────────────────────
class Client:
    """查关键词库。

        c = Client()
        c.stats()["words"]        # 47957
        w = c.lookup("румяна")    # Word，或者 None（= 没查过）

    不传 `api_key` 就按 IP 匿名查（60 次/分钟）。
    传了钥就不占公共额度，按钥限速限量（默认 2000 次/天）。
    """

    def __init__(self, base: Optional[str] = None,
                 api_key: Optional[str] = None,
                 timeout: float = 20.0,
                 user_agent: str = USER_AGENT) -> None:
        self.base = (base or os.environ.get("KWLIB_BASE") or DEFAULT_BASE).rstrip("/")
        self.api_key = (api_key or os.environ.get("KWLIB_API_KEY") or "").strip()
        self.timeout = timeout
        self.user_agent = user_agent

    # -- 底层 ------------------------------------------------------------
    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base + "/api/kwlib" + path
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            detail = ""
            try:
                detail = (json.loads(body.decode("utf-8", "replace")) or {}).get("detail") or ""
            except (ValueError, AttributeError):
                detail = body[:200].decode("utf-8", "replace")
            raise _error_for(e.code, _hint(e.code), url, detail) from None
        except Exception as e:  # 网络层：DNS / 超时 / 连接被拒
            raise KwlibError("连不上 %s：%s" % (self.base, e), url=url) from e
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError:
            raise KwlibError("服务端返回的不是 JSON", url=url,
                             detail=body[:200].decode("utf-8", "replace")) from None

    # -- 端点 ------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        """库概况：词数、快照数、数据日、导出时间。先调这个判断服务活没活。"""
        return self._get("/stats", {})

    def lookup(self, q: str) -> Optional[Word]:
        """精确查一个词。

        **查不到返回 None —— 那是"没查过"，不是"没量"。**
        想宽一点就用 `search()` 按词根找近义词。
        """
        q = _check_q(q)
        data = self._get("/lookup", {"q": q})
        if not data.get("known"):
            return None
        return Word.from_dict(data.get("word") or {})

    def search(self, q: str, limit: int = 20, min_count: int = 0,
               sort: str = "c") -> SearchResult:
        """按词根搜近义词。`sort`：c=热度 / ca=加购率 / chg=变化。"""
        q = _check_q(q)
        if sort not in ("c", "ca", "chg"):
            raise ValueError("sort 只能是 c、ca、chg")
        limit = max(1, min(int(limit), MAX_LIMIT))
        data = self._get("/search", {"q": q, "limit": limit,
                                     "min_c": max(0, int(min_count)), "sort": sort})
        return SearchResult(q=q,
                            total=int(data.get("total") or 0),
                            returned=int(data.get("returned") or 0),
                            items=[Word.from_dict(x) for x in (data.get("items") or [])])

    def top(self, limit: int = 50, min_count: int = 100) -> List[Word]:
        """全库热度最高的词。"""
        limit = max(1, min(int(limit), MAX_LIMIT))
        data = self._get("/top", {"limit": limit, "min_c": max(0, int(min_count))})
        return [Word.from_dict(x) for x in (data.get("items") or [])]

    def history(self, q: str) -> List[Point]:
        """一个词的周粒度序列。

        少于两个时间点就返回空列表 —— **一个点不叫趋势**，服务端不会编一个给你。
        """
        q = _check_q(q)
        data = self._get("/history", {"q": q})
        out: List[Point] = []
        for row in data.get("series") or []:
            row = list(row) + [None] * (7 - len(row))
            out.append(Point(date=row[0], count=row[1], sellers=row[2],
                             add_to_cart=row[3], orders=row[4],
                             gmv=row[5], avg_price=row[6]))
        return out

    def __repr__(self) -> str:
        return "Client(base=%r, api_key=%s)" % (
            self.base, "有" if self.api_key else "无")


def _check_q(q: str) -> str:
    n = normalize(q)
    if not n:
        raise ValueError("给个词再查")
    if len(n) > MAX_Q:
        raise ValueError("词太长了（≤%d 字符）" % MAX_Q)
    return n


def _hint(status: int) -> str:
    return {
        400: "参数不对",
        401: "钥无效或已撤销（带了钥就不会退回匿名额度）",
        403: "钥无效或已撤销（带了钥就不会退回匿名额度）",
        413: "请求太大",
        429: "查得太快：匿名每 IP 60 次/分钟，带钥每把钥 120 次/分钟",
        503: "词库未就绪 —— 这时候所有词都会显示没数据，别当成没量",
    }.get(status, "服务端出错" if status >= 500 else "请求失败")
