# -*- coding: utf-8 -*-
"""把一族词导成 CSV，按加购率排 —— 选品时最先看的那张表。

    python examples/top_csv.py румян out.csv
    python examples/top_csv.py румян out.csv --sort chg     # 看谁在涨
    python examples/top_csv.py румян out.csv --min-count 1000

加购率比热度诚实：热度是"多少人搜"，加购率是"搜的人里多少人真的想要"。
**但加购率必须配上热度下限看** —— 只有 5 次搜索的词也能有 100% 加购率，
那不是机会，是噪音。所以这里默认 `--min-count 200`，别把下限调到 0 去排 `ca`。
"""
import csv
import os
import sys

# 还没 pip install 时也能直接跑：把仓库根目录放进 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kwlib import Client  # noqa: E402

COLS = ["q", "count", "sellers", "add_to_cart", "orders", "gmv", "avg_price",
        "change", "last"]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    root, out = argv[0], argv[1]
    sort = "ca"
    if "--sort" in argv:
        sort = argv[argv.index("--sort") + 1]
    min_count = 200
    if "--min-count" in argv:
        min_count = int(argv[argv.index("--min-count") + 1])

    c = Client()
    r = c.search(root, limit=100, min_count=min_count, sort=sort)
    print("排序 %s，热度下限 %d（低于它的词样本太小，加购率不可信）" % (sort, min_count))
    if not r:
        print("词根「%s」库里没有 —— 是没查过，不是没量。" % root)
        return 2

    # utf-8-sig：Excel 直接双击打开不乱码
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for x in r:
            w.writerow(["" if getattr(x, k) is None else getattr(x, k) for k in COLS])

    print("写了 %d 行 → %s（库里共 %d 条匹配）" % (len(r), out, r.total))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
