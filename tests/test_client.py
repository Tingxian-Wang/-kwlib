# -*- coding: utf-8 -*-
"""离线测试：起一个假服务端，不联网。

    python -m unittest discover -s tests -v

判据都打在那三条口径上：
  查不到 = None 而不是 0；每个数带日期；服务不可用就抛，不给你空列表。
"""
import io
import json
import os
import sys
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kwlib import (AuthError, Client, NotReady, RateLimited, SearchResult,  # noqa: E402
                   Word, cli, normalize)

HIT = {"q": "румяна", "count": 31915, "sellers": 15, "ca": 30.8, "ord": 41,
       "gmv": 0, "avg": 663, "date": "2026-11-09", "last": "2026-11-09",
       "n": 3, "prev": 30000, "chg": 6.4, "peak": None}
LIKE = {"q": "румяна для лица", "count": 4241, "sellers": 60, "ca": 35.6,
        "ord": 12, "gmv": None, "avg": None, "date": "2026-11-09",
        "last": "2026-11-09", "n": 2, "prev": None, "chg": None, "peak": None}
STATS = {"words": 47957, "history_words": 2731, "snapshots": "364",
         "data_date": "2026-11-09", "built": "2026-11-09 17:07",
         "exported": "2026-11-09 19:54"}


class Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        Handler.seen.append((u.path, qs, self.headers.get("X-Api-Key")))
        if u.path == "/api/kwlib/stats":
            return self._send(STATS)
        if u.path == "/api/kwlib/lookup":
            if qs.get("q") == "румяна":
                return self._send({"q": "румяна", "known": True, "word": HIT})
            if qs.get("q") == "boom":
                return self._send({"detail": "钥无效"}, 401)
            if qs.get("q") == "slow":
                return self._send({"detail": "查得太快"}, 429)
            if qs.get("q") == "down":
                return self._send({"detail": "词库未就绪"}, 503)
            return self._send({"q": qs.get("q"), "known": False,
                               "note": "库里没有这个词 —— 是没查过，不是没量。"})
        if u.path == "/api/kwlib/search":
            items = [HIT, LIKE]
            return self._send({"q": qs.get("q"), "total": 128, "returned": 2,
                               "items": items})
        if u.path == "/api/kwlib/top":
            return self._send({"returned": 1, "items": [HIT]})
        if u.path == "/api/kwlib/history":
            return self._send({
                "q": qs.get("q"), "points": 2,
                "cols": ["date", "count", "sellers", "ca", "ord", "gmv", "avg"],
                "series": [["2026-10-12", 30000, 9, 34.0],
                           ["2026-11-09", 31915, 15, 30.8, 41, 0, 663]]})
        return self._send({"detail": "not found"}, 404)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Handler.seen.clear()
        self.c = Client(base=self.base, timeout=5)


class TLookup(Base):
    def test_hit(self):
        w = self.c.lookup("румяна")
        self.assertIsInstance(w, Word)
        self.assertEqual(w.count, 31915)
        self.assertEqual(w.add_to_cart, 30.8)      # ca → add_to_cart
        self.assertEqual(w.avg_price, 663)
        self.assertEqual(w.change, 6.4)
        self.assertEqual(w.last, "2026-11-09")

    def test_unknown_is_none_not_zero(self):
        self.assertIsNone(self.c.lookup("пазл"))

    def test_gmv_zero_stays_zero(self):
        # 0 和 None 是两件事：0 是"真的是 0"，None 是"没采到"
        w = self.c.lookup("румяна")
        self.assertEqual(w.gmv, 0)
        w2 = self.c.search("румян")[1]
        self.assertIsNone(w2.gmv)

    def test_normalize(self):
        self.c.lookup("  РУМЯНА  ")
        self.assertEqual(Handler.seen[0][1]["q"], "румяна")

    def test_empty_query_rejected_locally(self):
        with self.assertRaises(ValueError):
            self.c.lookup("   ")

    def test_too_long_rejected_locally(self):
        with self.assertRaises(ValueError):
            self.c.lookup("я" * 81)


class TErrors(Base):
    def test_503_not_ready(self):
        with self.assertRaises(NotReady):
            self.c.lookup("down")

    def test_429(self):
        with self.assertRaises(RateLimited):
            self.c.lookup("slow")

    def test_401_carries_api_key(self):
        c = Client(base=self.base, api_key="sk_test")
        with self.assertRaises(AuthError):
            c.lookup("boom")
        self.assertEqual(Handler.seen[0][2], "sk_test")

    def test_no_key_header_when_anonymous(self):
        self.c.lookup("румяна")
        self.assertIsNone(Handler.seen[0][2])


class TSearch(Base):
    def test_total_vs_returned(self):
        r = self.c.search("румян")
        self.assertIsInstance(r, SearchResult)
        self.assertEqual(r.total, 128)       # 库里全部匹配
        self.assertEqual(r.returned, 2)      # 这次给了几条
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0].q, "румяна")
        self.assertEqual([w.q for w in r], ["румяна", "румяна для лица"])

    def test_sort_validation(self):
        with self.assertRaises(ValueError):
            self.c.search("румян", sort="nope")

    def test_top(self):
        self.assertEqual(len(self.c.top()), 1)


class THistory(Base):
    def test_points_pad_short_rows(self):
        pts = self.c.history("румяна")
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[0].count, 30000)
        self.assertIsNone(pts[0].orders)     # 行短了补 None，不是补 0
        self.assertEqual(pts[1].avg_price, 663)


class TWord(unittest.TestCase):
    def test_stale_days(self):
        w = Word(q="x", last="2020-01-01")
        self.assertGreater(w.stale_days, 365)
        self.assertIsNone(Word(q="x").stale_days)

    def test_as_dict_roundtrip(self):
        w = Word.from_dict(HIT)
        self.assertEqual(Word.from_dict(w.as_dict()), w)

    def test_normalize(self):
        self.assertEqual(normalize("  Румяна   для   Лица "), "румяна для лица")


class TCli(Base):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["--base", self.base] + list(argv))
        return rc, buf.getvalue()

    def test_stats(self):
        rc, out = self.run_cli("stats")
        self.assertEqual(rc, 0)
        self.assertIn("47957", out)

    def test_lookup_miss_exit_2_and_says_why(self):
        rc, out = self.run_cli("lookup", "пазл")
        self.assertEqual(rc, 2)
        self.assertIn("没查过", out)
        self.assertNotIn("0", out.replace("0", "", 0))  # 只要没画 0 就行（下面这条更准）
        self.assertNotIn(" 0 ", out)

    def test_lookup_json(self):
        rc, out = self.run_cli("--json", "lookup", "румяна")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["count"], 31915)

    def test_table_uses_dash_for_missing(self):
        rc, out = self.run_cli("search", "румян")
        self.assertEqual(rc, 0)
        self.assertIn("—", out)
        self.assertIn("128", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
