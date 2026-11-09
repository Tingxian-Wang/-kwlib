# -*- coding: utf-8 -*-
"""kwlib —— 跨境选品的公开关键词库客户端。

    from kwlib import Client
    c = Client()
    w = c.lookup("румяна")
    if w is None:
        print("这个词库里没有 —— 是没查过，不是没量")
    else:
        print(w.count, w.last, w.stale_days)

零依赖、只读、无需注册即可用（匿名限速 60 次/分钟）。
数据口径见仓库里的 PROTOCOL.md。
"""
from .client import (  # noqa: F401
    DEFAULT_BASE, AuthError, BadRequest, Client, KwlibError, NotReady, Point,
    RateLimited, SearchResult, ServerError, Word, normalize,
)

__version__ = "1.0.0"
__all__ = [
    "Client", "Word", "Point", "SearchResult", "normalize", "DEFAULT_BASE",
    "KwlibError", "BadRequest", "AuthError", "RateLimited", "NotReady", "ServerError",
    "__version__",
]
