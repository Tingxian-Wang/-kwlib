# -*- coding: utf-8 -*-
"""命令行：`python -m kwlib <命令> [参数]`

    python -m kwlib stats
    python -m kwlib lookup румяна
    python -m kwlib search румян --limit 10 --sort ca
    python -m kwlib top --limit 20
    python -m kwlib history румяна
    python -m kwlib search румян --json          # 喂给别的程序

表格里缺的数一律打 **—**，不打 0 —— 0 会被读成"没市场"，而缺是"没采到"。
退出码：0 正常；1 非预期错误；2 词库里没有（不是错误，是明确答案）；3 服务不可用。
"""
from __future__ import annotations

import argparse
import json
import sys

from .client import (Client, KwlibError, NotReady, RateLimited, AuthError,
                     Word, DEFAULT_BASE)

COLS = ("q", "count", "sellers", "add_to_cart", "orders", "gmv", "avg_price",
        "change", "last")


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return ("%.1f" % v).rstrip("0").rstrip(".")
    return str(v)


def _table(words, cols=COLS) -> str:
    rows = [[_fmt(getattr(w, c)) for c in cols] for w in words]
    head = list(cols)
    w = [max(len(head[i]), *(len(r[i]) for r in rows)) if rows else len(head[i])
         for i in range(len(head))]
    out = ["  ".join(h.ljust(w[i]) for i, h in enumerate(head)),
           "  ".join("-" * w[i] for i in range(len(head)))]
    for r in rows:
        out.append("  ".join(c.ljust(w[i]) for i, c in enumerate(r)))
    return "\n".join(out)


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m kwlib", description="跨境选品关键词库（公开查询客户端）")
    p.add_argument("--base", default=None,
                   help="接口根地址，默认 %s（也可用环境变量 KWLIB_BASE）" % DEFAULT_BASE)
    p.add_argument("--key", default=None,
                   help="API key（也可用环境变量 KWLIB_API_KEY）；不传就匿名查")
    p.add_argument("--json", action="store_true", help="输出 JSON，不画表格")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="库概况：多少词、数据日是哪天")

    sp = sub.add_parser("lookup", help="精确查一个词（查不到 = 没查过，不是没量）")
    sp.add_argument("q")

    sp = sub.add_parser("search", help="按词根搜近义词")
    sp.add_argument("q")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--min-count", type=int, default=0, dest="min_count")
    sp.add_argument("--sort", default="c", choices=["c", "ca", "chg"],
                    help="c=热度 / ca=加购率 / chg=变化")

    sp = sub.add_parser("top", help="全库热度最高的词")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--min-count", type=int, default=100, dest="min_count")

    sp = sub.add_parser("history", help="一个词的序列（周粒度）")
    sp.add_argument("q")
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    c = Client(base=a.base, api_key=a.key)
    try:
        if a.cmd == "stats":
            s = c.stats()
            if a.json:
                _dump(s)
                return 0
            print("词数      %s" % s.get("words"))
            print("有序列的词 %s" % s.get("history_words"))
            print("快照数    %s" % s.get("snapshots"))
            print("数据日    %s" % s.get("data_date"))
            print("导出时间  %s" % s.get("exported"))
            return 0

        if a.cmd == "lookup":
            w = c.lookup(a.q)
            if w is None:
                if a.json:
                    _dump({"q": a.q, "known": False, "note": "没查过，不等于没量"})
                else:
                    print("「%s」库里没有 —— 是没查过，不是没量。" % a.q)
                    print("换个词根试试：python -m kwlib search %s" % a.q)
                return 2
            if a.json:
                _dump(w.as_dict())
            else:
                print(_table([w]))
                if w.stale_days is not None and w.stale_days > 30:
                    print("\n⚠️ 这个数已经 %d 天了，只能当参考。" % w.stale_days)
            return 0

        if a.cmd == "search":
            r = c.search(a.q, limit=a.limit, min_count=a.min_count, sort=a.sort)
            if a.json:
                _dump({"q": r.q, "total": r.total, "returned": r.returned,
                       "items": [w.as_dict() for w in r]})
                return 0
            if not len(r):
                print("词根「%s」没有匹配 —— 库里没查过这类词，不代表没量。" % a.q)
                return 2
            print(_table(list(r)))
            print("\n%d 条匹配，本次返回 %d 条。" % (r.total, r.returned))
            return 0

        if a.cmd == "top":
            ws = c.top(limit=a.limit, min_count=a.min_count)
            if a.json:
                _dump([w.as_dict() for w in ws])
                return 0
            print(_table(ws))
            return 0

        if a.cmd == "history":
            pts = c.history(a.q)
            if a.json:
                _dump([p.__dict__ for p in pts])
                return 0
            if not pts:
                print("「%s」没有两个以上时间点 —— 一个点不叫趋势。" % a.q)
                return 2
            rows = [p for p in pts]
            head = ["date", "count", "sellers", "add_to_cart", "orders", "gmv", "avg_price"]
            out = ["  ".join(h.ljust(10) for h in head)]
            for p in rows:
                out.append("  ".join(_fmt(getattr(p, k)).ljust(10) for k in head))
            print("\n".join(out))
            print("\n共 %d 个时间点。" % len(rows))
            return 0

        print("未知命令 %s" % a.cmd)
        return 1
    except ValueError as e:
        print("参数不对：%s" % e, file=sys.stderr)
        return 1
    except NotReady as e:
        print("词库未就绪（503）：%s" % e, file=sys.stderr)
        return 3
    except RateLimited as e:
        print("查得太快（429）：%s" % e, file=sys.stderr)
        return 1
    except AuthError as e:
        print("钥不对（%s）：%s" % (e.status, e), file=sys.stderr)
        return 1
    except KwlibError as e:
        print("查询失败：%s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
