# -*- coding: utf-8 -*-
"""처분 #17 — 3묶음: 동일성 계약 · 저장/비용 무결성(다중 프로세스) · 링크→카드 파이프라인(로컬 http.server)."""
import datetime
import io
import json
import multiprocessing
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import cards_html as ch
import link_check as lc
from ledger import BudgetExceeded, Ledger
from norm_id import norm_id
from rounds import load_seen, save_round

V = "dQw4w9WgXcQ"
V2 = "AAAAAAAAAAA"
V3 = "BBBBBBBBBBB"

SAME = [
    ("https://www.youtube.com/watch?v=" + V, "https://youtu.be/" + V),
    ("https://m.youtube.com/watch?v=" + V + "&t=30s", "https://music.youtube.com/watch?v=" + V),
    ("https://www.youtube.com/live/" + V, "https://www.youtube.com/embed/" + V),
    ("https://YOUTU.BE/" + V, "https://youtu.be/" + V + "?si=zzz"),
    ("https://x.com/u/status/123?s=20", "https://twitter.com/other/status/123"),
    ("https://www.tiktok.com/@u/video/777", "https://m.tiktok.com/@v/video/777?lang=ko"),
    ("https://www.instagram.com/p/Ab_1/", "https://m.instagram.com/p/Ab_1?igsh=1"),
    ("https://www.threads.net/@u/post/Zz9", "https://www.threads.com/@u/post/Zz9"),
    ("https://Example.com/Path/", "https://www.example.com/Path"),
    ("https://a.com/p?a=1&b=2", "https://a.com/p?a=1&utm_campaign=x&b=2"),
    ("https://a.com/page#top", "https://a.com/page"),
]
DIFFERENT = [
    ("https://youtu.be/" + V2, "https://youtu.be/" + V3),
    ("https://music.youtube.com/watch?v=" + V2, "https://music.youtube.com/watch?v=" + V3),
    ("https://a.com/item?id=1", "https://a.com/item?id=2"),
    ("https://a.com/Report", "https://a.com/report"),
    ("https://a.com/#/item/1", "https://a.com/#/item/2"),
    ("https://notinstagram.com/p/ABC", "https://www.instagram.com/p/ABC"),
    ("https://m.a.com/x", "https://a.com/x"),
    ("https://a.com:8080/x", "https://a.com/x"),
]


def test_identity_contract():
    for a, b in SAME:
        assert norm_id(a) is not None and norm_id(a) == norm_id(b), (a, b)
    for a, b in DIFFERENT:
        assert norm_id(a) != norm_id(b), (a, b)
    for bad in ["https://youtu.be/" + V + "XYZ", "https://youtu.be/Äbcdefghijk",
                "https://vm.tiktok.com/ZMabc/", "https://www.youtube.com/@chan"]:
        assert norm_id(bad) is None, bad


# ---------------- 묶음 2: 저장·비용 무결성 ----------------
def _ledger_worker(args):
    path, n = args
    lg = Ledger(path, cap="1.0")
    ok = 0
    for _ in range(n):
        try:
            lg.record("w", "0.1")
            ok += 1
        except BudgetExceeded:
            pass
    return ok


def _rounds_worker(args):
    folder, k, n = args
    for j in range(n):
        save_round(folder, "r", [{"url": "https://a.test/p%d_%d" % (k, j)}])
    return n


def test_storage_and_budget_integrity(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    path = str(tmp_path / "비용장부_동시.jsonl")
    with ctx.Pool(4) as pool:
        oks = pool.map(_ledger_worker, [(path, 5)] * 8)
    assert sum(oks) == 10  # 상한 1.0 / 단가 0.1 — 40회 시도 중 정확히 10회만 기록
    lg = Ledger(path, cap="1.0")
    from decimal import Decimal
    assert lg.cumulative() == Decimal("1.0")
    rows = [json.loads(x) for x in io.open(path, encoding="utf-8") if x.strip()]
    assert len(rows) == 10 and max(r["cumulative"] for r in rows) == 1.0

    folder = str(tmp_path / "조사")
    with ctx.Pool(4) as pool:
        pool.map(_rounds_worker, [(folder, k, 6) for k in range(4)])
    want = {norm_id("https://a.test/p%d_%d" % (k, j)) for k in range(4) for j in range(6)}
    assert len(want) == 24 and load_seen(folder) == want  # seen 합집합 보존(손실 0)
    files = os.listdir(os.path.join(folder, "research"))
    assert len(files) == 24  # 덮어쓰기 0
    assert not os.path.exists(os.path.join(folder, "seen_ids.lock"))


def test_ledger_rejects_bad_values_and_exact_decimals(tmp_path):
    from decimal import Decimal
    lg = Ledger(str(tmp_path / "l.jsonl"), cap="0.3")
    for bad in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            lg.record("t", bad)
    for _ in range(3):
        lg.record("t", "0.1")
    assert lg.cumulative() == Decimal("0.3")
    with pytest.raises(BudgetExceeded):
        lg.record("t", "0.000001")


# ---------------- 묶음 3: 링크 → 카드 → HTML ----------------
class _Site(object):
    def __init__(self, routes, robots=(404, "")):
        self.routes = routes
        self.robots = robots
        self.hits = {}
        site = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                site.hits[path] = site.hits.get(path, 0) + 1
                if path == "/robots.txt":
                    code, body = site.robots
                    return self._send(code, {}, body.encode("utf-8"))
                r = site.routes.get(path)
                if callable(r):
                    r = r(site.hits[path])
                if r is None:
                    return self._send(404, {}, b"")
                self._send(r[0], r[1], r[2] if isinstance(r[2], bytes) else r[2].encode("utf-8"))

            def _send(self, code, headers, body):
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                if "Content-Type" not in headers:
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever)
        self.t.daemon = True
        self.t.start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _html(title, body=""):
    return (200, {}, "<html><head><title>%s</title></head><body>%s</body></html>" % (title, body))


@pytest.fixture
def net(monkeypatch):
    monkeypatch.setattr(lc.time, "sleep", lambda s: None)
    proxyless = urllib.request.ProxyHandler({})

    def op(req, timeout=10):
        return lc._build_opener(proxyless).open(req, timeout=timeout)
    monkeypatch.setattr(lc, "_urlopen", op)
    sites = []

    def make(routes, robots=(404, "")):
        s = _Site(routes, robots)
        sites.append(s)
        return s
    yield make
    for s in sites:
        s.close()


def test_link_to_cards_pipeline(net, tmp_path, monkeypatch):
    big = "<p>" + ("가" * 1100000) + "</p><p>끝쪽근거</p>"
    A = net({
        "/ok": _html("정상 제목", "<b>근</b>거 문장 Tom &amp; Jerry"),
        "/redir_ok": (302, {"Location": "/ok"}, ""),
        "/redir_login": (302, {"Location": "https://www.instagram.com/accounts/login/"}, ""),
        "/redir_threads": (302, {"Location": "https://www.threads.com/login"}, ""),
        "/consent": (302, {"Location": "http://consent.example.invalid/x"}, ""),
        "/soft404": _html("404 Not Found"),
        "/captcha": _html("확인", "Please complete the CAPTCHA"),
        "/big": _html("큰 페이지", big),
        "/gone": (404, {}, ""),
        "/five": (500, {}, ""),
        "/limited": lambda n: (429, {"Retry-After": "0"}, "") if n == 1 else _html("재시도 뒤 열림"),
        "/oembed_list": (200, {"Content-Type": "application/json"}, "[]"),
        "/oembed_html": (200, {}, "<html>x</html>"),
        "/oembed_ok": (200, {"Content-Type": "application/json"}, json.dumps({"title": "영상", "author_name": "채널"})),
    })
    B = net({"/p": _html("B")}, robots=(401, ""))
    C = net({"/p": _html("C")}, robots=(403, ""))
    D = net({"/p": _html("D")}, robots=(429, ""))
    E = net({"/p": _html("E")}, robots=(500, ""))
    F = net({"/private/x": _html("F"), "/open": _html("F open")}, robots=(200, "User-agent: *\nDisallow: /private/\n"))

    yt = lambda i: "https://youtu.be/%s" % ("abcdefghi%02d" % i)
    monkeypatch.setattr(lc, "oembed_url", lambda u: {
        yt(1): A.base + "/oembed_list", yt(2): A.base + "/oembed_html", yt(3): A.base + "/oembed_ok"}[u])

    items = [
        {"url": A.base + "/ok", "title": "정상 제목", "evidence": "근거 문장"},          # 0 opened·found
        {"url": A.base + "/ok", "evidence": "Tom & Jerry"},                              # 1 entity
        {"url": A.base + "/redir_ok"},                                                   # 2 opened
        {"url": A.base + "/redir_login"},                                                # 3 login_redirect
        {"url": A.base + "/redir_threads"},                                              # 4 login_redirect
        {"url": A.base + "/consent"},                                                    # 5 blocked_page
        {"url": A.base + "/soft404"},                                                    # 6 soft404
        {"url": A.base + "/captcha"},                                                    # 7 blocked_page
        {"url": A.base + "/big", "evidence": "끝쪽근거"},                                 # 8 truncated·not_found
        {"url": A.base + "/gone"},                                                       # 9 dead
        {"url": A.base + "/five"},                                                       # 10 unverified http_500
        {"url": A.base + "/limited"},                                                    # 11 429 → 재시도 → opened
        {"url": yt(1)}, {"url": yt(2)},                                                  # 12·13 oembed_invalid
        {"url": yt(3), "title": "<!-- <script>", "account": "채널"},                      # 14 opened·oembed
        {"url": B.base + "/p"}, {"url": C.base + "/p"},                                  # 15·16 robots_denied
        {"url": D.base + "/p"}, {"url": E.base + "/p"},                                  # 17·18 robots_unknown
        {"url": F.base + "/private/x"}, {"url": F.base + "/open"},                       # 19 denied · 20 opened
    ]
    out = str(tmp_path / "link_check.json")
    res = lc.check_items(items, out_path=out, sleep=lambda s: None)
    got = [(r["state"], r["reason"]) for r in res["results"]]
    want = [("opened", ""), ("opened", ""), ("opened", ""), ("unverified", "login_redirect"),
            ("unverified", "login_redirect"), ("unverified", "blocked_page"), ("unverified", "soft404_suspect"),
            ("unverified", "blocked_page"), ("opened", ""), ("dead", "http_404"), ("unverified", "http_500"),
            ("opened", ""), ("unverified", "oembed_invalid"), ("unverified", "oembed_invalid"), ("opened", ""),
            ("unverified", "robots_denied"), ("unverified", "robots_denied"), ("unverified", "robots_unknown"),
            ("unverified", "robots_unknown"), ("unverified", "robots_denied"), ("opened", "")]
    assert got == want
    R = res["results"]
    assert R[0]["evidence_status"] == "found" and R[1]["evidence_status"] == "found"
    assert R[2]["final_url"].endswith("/ok")
    assert R[8]["truncated"] is True and R[8]["evidence_status"] == "not_found"
    assert A.hits["/limited"] == 2
    assert D.hits.get("/p", 0) == 0 and E.hits.get("/p", 0) == 0 and B.hits.get("/p", 0) == 0  # 본문 요청 안 함
    assert R[14]["check_method"] == "oembed" and R[14]["account_match"] == "match"

    with io.open(out, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["summary"]["total"] == len(items)
    assert os.path.exists(str(tmp_path / "link_check.partial.jsonl"))

    cards = ch.cards_from_link_check(items, saved)
    h = ch.build_html(cards, title="파이프라인")
    st = ch.compute_stats(cards)
    assert st["opened"] == saved["summary"]["opened"] and st["unverified"] == saved["summary"]["unverified"]
    assert st["dead"] == saved["summary"]["dead"] and st["unknown"] == 0
    assert "총 %d건" % len(items) in h
    assert "열림 <b>%d</b>" % saved["summary"]["opened"] in h
    line = h[h.index("const CARDS"):].split("\n", 1)[0]
    assert "<!--" not in line and "<script>" not in line
    assert len(ch.cards_from_link_check(items, saved)) == len(items)


# ---------------- 정정2: 로컬 http.server 로 3xx 반례 ----------------
def test_f6_redirect_edge_cases_via_local_server(net, tmp_path):
    A = net({
        "/ok": _html("정상"),
        "/nolocation": (302, {}, ""),
        "/r308": (308, {"Location": "/ok"}, ""),
        "/loop": (302, {"Location": "/loop"}, ""),
        "/dotted": (302, {"Location": "http://www.instagram.com./p/ABC/"}, ""),
        "/dotted2": (301, {"Location": "http://INSTAGRAM.COM./p/ABC/"}, ""),
    })
    items = [{"url": A.base + p} for p in ("/nolocation", "/r308", "/loop", "/dotted", "/dotted2")]
    res = lc.check_items(items, out_path=str(tmp_path / "o.json"), sleep=lambda s: None)
    got = [(r["state"], r["reason"]) for r in res["results"]]
    assert got[0] == ("unverified", "redirect_unfollowed_302")
    assert got[1] == ("opened", "") and res["results"][1]["final_url"].endswith("/ok")
    assert got[2][0] == "unverified" and got[2][1].startswith("redirect_unfollowed_")
    assert got[3] == ("unverified", "login_redirect") and got[4] == ("unverified", "login_redirect")
