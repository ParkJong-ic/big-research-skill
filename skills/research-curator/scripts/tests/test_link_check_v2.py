# -*- coding: utf-8 -*-
"""정정1 (반증 1회차 #6~#12) — link_check 새 규칙. 오프라인 Fake 로 확인."""
import io
import json

import pytest

import link_check as lc


class Fake(object):
    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, url, timeout=10):
        self.calls.append(url)
        return dict(self.table.get(url, {"status": None, "error": "dns_noname", "final_url": url, "text": ""}))


def page(title, body=""):
    return "<html><head><title>%s</title></head><body><script>x</script>%s</body></html>" % (title, body)


def one(item, table, tmp_path):
    f = Fake(table)
    res = lc.check_items([item], fetch=f, sleep=lambda s: None, out_path=str(tmp_path / "o.json"),
                         robots=lambda u: True)
    return res["results"][0], f


def ok_page(url, title="제목", body=""):
    return {url: {"status": 200, "final_url": url, "text": page(title, body)}}


def test_dns_noname_vs_temp(tmp_path):
    a, _ = one({"url": "http://x.test/a"}, {"http://x.test/a": {"status": None, "error": "dns_noname", "final_url": "", "text": ""}}, tmp_path)
    b, _ = one({"url": "http://x.test/b"}, {"http://x.test/b": {"status": None, "error": "dns_temp", "final_url": "", "text": ""}}, tmp_path)
    assert (a["state"], a["reason"]) == ("dead", "dns_noname")
    assert (b["state"], b["reason"]) == ("unverified", "dns_temp")


def test_real_fetch_gaierror_split(monkeypatch):
    import socket
    import urllib.error
    monkeypatch.setattr(lc.time, "sleep", lambda s: None)

    def noname(req, timeout=10):
        raise urllib.error.URLError(socket.gaierror(socket.EAI_NONAME, "x"))

    def again(req, timeout=10):
        raise urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, "x"))
    monkeypatch.setattr(lc, "_urlopen", noname)
    assert lc.fetch("http://a.test/")["error"] == "dns_noname"
    monkeypatch.setattr(lc, "_urlopen", again)
    assert lc.fetch("http://a.test/")["error"] == "dns_temp"


def test_check_method_recorded(tmp_path):
    r, _ = one({"url": "http://a.test/p"}, ok_page("http://a.test/p"), tmp_path)
    assert r["check_method"] == "page"
    yt = "https://youtu.be/dQw4w9WgXcQ"
    body = json.dumps({"title": "T", "author_name": "A"})
    r, _ = one({"url": yt}, {lc.oembed_url(yt): {"status": 200, "final_url": "", "text": body}}, tmp_path)
    assert r["check_method"] == "oembed"
    r, _ = one({"url": yt}, {lc.oembed_url(yt): {"status": 404, "final_url": "", "text": ""}}, tmp_path)
    assert (r["state"], r["check_method"]) == ("dead", "oembed")


@pytest.mark.parametrize("text", ["[]", "<html>nope</html>", "", '"str"', '{"author_name":"x"}', '{"title":""}'])
def test_oembed_invalid_unverified(tmp_path, text):
    yt = "https://youtu.be/dQw4w9WgXcQ"
    r, _ = one({"url": yt}, {lc.oembed_url(yt): {"status": 200, "final_url": "", "text": text}}, tmp_path)
    assert (r["state"], r["reason"]) == ("unverified", "oembed_invalid")


def test_login_redirect_final_host(tmp_path):
    u = "http://a.test/x"
    t = {u: {"status": 200, "final_url": "https://www.threads.com/login", "text": page("t")}}
    r, _ = one({"url": u}, t, tmp_path)
    assert (r["state"], r["reason"]) == ("unverified", "login_redirect")
    t = {u: {"status": None, "error": "login_redirect", "final_url": "https://www.instagram.com/accounts/login/", "text": ""}}
    r, _ = one({"url": u}, t, tmp_path)
    assert (r["state"], r["reason"]) == ("unverified", "login_redirect")


def test_threads_com_is_login_host(tmp_path):
    r, f = one({"url": "https://www.threads.com/@u/post/abc"}, {}, tmp_path)
    assert f.calls == [] and r["reason"] == "login_host_skipped"


def test_blocked_and_soft404_pages(tmp_path):
    u = "http://a.test/x"
    for title, body in [("Just a moment", "Please complete the CAPTCHA to continue"), ("Access Denied", ""),
                        ("x", "Are you a robot?")]:
        r, _ = one({"url": u}, ok_page(u, title, body), tmp_path)
        assert (r["state"], r["reason"]) == ("unverified", "blocked_page"), (title, body)
    t = {u: {"status": 200, "final_url": "http://consent.a.test/x", "text": page("t")}}
    r, _ = one({"url": u}, t, tmp_path)
    assert r["reason"] == "blocked_page"
    for title in ["404 Not Found", "Page not found - Site", "페이지를 찾을 수 없습니다"]:
        r, _ = one({"url": u}, ok_page(u, title), tmp_path)
        assert (r["state"], r["reason"]) == ("unverified", "soft404_suspect"), title


def test_exception_isolated_and_partial_jsonl(tmp_path):
    def boom(url, timeout=10):
        if url.endswith("/bad"):
            raise RuntimeError("x")
        return {"status": 200, "final_url": url, "text": page("ok")}
    out = str(tmp_path / "link_check.json")
    res = lc.check_items([{"url": "http://a.test/1"}, {"url": "http://a.test/bad"}, {"url": "http://a.test/3"}],
                         fetch=boom, sleep=lambda s: None, out_path=out, robots=lambda u: True)
    st = [(r["state"], r["reason"]) for r in res["results"]]
    assert st == [("opened", ""), ("unverified", "error:RuntimeError"), ("opened", "")]
    part = tmp_path / "link_check.partial.jsonl"
    lines = [json.loads(x) for x in io.open(str(part), encoding="utf-8") if x.strip()]
    assert [x["url"] for x in lines] == [r["url"] for r in res["results"]]


def test_missing_url_key_isolated(tmp_path):
    r, _ = one({"title": "no url"}, {}, tmp_path)
    assert r["state"] == "unverified" and r["reason"].startswith("error:")


def test_evidence_status(tmp_path):
    u = "http://a.test/p"
    r, _ = one({"url": u, "evidence": "   "}, ok_page(u, "t", "본문"), tmp_path)
    assert (r["evidence_found"], r["evidence_status"]) == (None, "empty")
    r, _ = one({"url": u}, ok_page(u, "t", "본문"), tmp_path)
    assert (r["evidence_found"], r["evidence_status"]) == (None, "not_checked")
    r, _ = one({"url": u, "evidence": "본문"}, ok_page(u, "t", "본문"), tmp_path)
    assert (r["evidence_found"], r["evidence_status"]) == (True, "found")
    r, _ = one({"url": u, "evidence": "없음zz"}, ok_page(u, "t", "본문"), tmp_path)
    assert (r["evidence_found"], r["evidence_status"]) == (False, "not_found")
    r, _ = one({"url": "http://a.test/g", "evidence": "x"},
               {"http://a.test/g": {"status": 404, "final_url": "", "text": ""}}, tmp_path)
    assert r["evidence_status"] == "not_checked" and r["evidence_found"] is None


def test_evidence_inline_tags_and_entities(tmp_path):
    u = "http://a.test/p"
    r, _ = one({"url": u, "evidence": "근거 문장"}, ok_page(u, "t", "<b>근</b>거 <i>문</i><span>장</span>"), tmp_path)
    assert r["evidence_found"] is True
    r, _ = one({"url": u, "evidence": "Tom & Jerry"}, ok_page(u, "t", "Tom &amp; Jerry"), tmp_path)
    assert r["evidence_found"] is True
    r, _ = one({"url": u, "evidence": "두 단어"}, ok_page(u, "t", "<p>두</p><p>단어</p>"), tmp_path)
    assert r["evidence_found"] is True  # 블록 태그는 공백


def test_evidence_scope_and_truncated_flags(tmp_path):
    yt = "https://youtu.be/dQw4w9WgXcQ"
    body = json.dumps({"title": "Never", "author_name": "Rick"})
    r, _ = one({"url": yt, "evidence": "never"}, {lc.oembed_url(yt): {"status": 200, "final_url": "", "text": body}}, tmp_path)
    assert r["evidence_scope"] == "metadata"
    u = "http://a.test/p"
    t = ok_page(u, "t", "본문")
    t[u]["truncated"] = True
    t[u]["decode_issue"] = True
    r, _ = one({"url": u, "evidence": "zz"}, t, tmp_path)
    assert r["evidence_scope"] == "page" and r["truncated"] is True and r["decode_issue"] is True


def test_account_match_rules(tmp_path):
    yt = "https://youtu.be/dQw4w9WgXcQ"
    body = json.dumps({"title": "T", "author_name": "Rick Astley", "author_url": "https://www.youtube.com/@RickAstleyYT"})
    t = {lc.oembed_url(yt): {"status": 200, "final_url": "", "text": body}}
    cases = [("Rick Astley", "match"), ("rick  astley", "match"), ("@RickAstleyYT", "match"),
             ("Rick", "conflict"), ("Astley", "conflict"), ("@", "not_compared"), ("  ", "not_compared"),
             ("Someone Else", "conflict")]
    for acct, want in cases:
        r, _ = one({"url": yt, "account": acct}, t, tmp_path)
        assert r["account_match"] == want, acct
        assert r["conflict"] is (want == "conflict")
    r, _ = one({"url": yt}, t, tmp_path)
    assert r["account_match"] == "not_compared" and r["title_match"] == "not_compared"


def test_title_match_values(tmp_path):
    u = "http://a.test/p"
    r, _ = one({"url": u, "title": "실제 제목"}, ok_page(u, "실제 제목 - 사이트"), tmp_path)
    assert r["title_match"] == "match"
    r, _ = one({"url": u, "title": "전혀 다른 문장입니다"}, ok_page(u, "실제 제목"), tmp_path)
    assert r["title_match"] == "conflict" and r["conflict"] is True


def test_429_retry_after(monkeypatch):
    import urllib.error
    sleeps = []
    monkeypatch.setattr(lc.time, "sleep", sleeps.append)
    seq = []

    class H(object):
        def __init__(self, v):
            self.v = v

        def get(self, k, d=None):
            return self.v if k.lower() == "retry-after" else d

    def op(req, timeout=10):
        seq.append(1)
        raise urllib.error.HTTPError(req.full_url, 429, "x", H("3"), None)
    monkeypatch.setattr(lc, "_urlopen", op)
    r = lc.fetch("http://a.test/")
    assert len(seq) == 2 and r["status"] == 429 and sleeps == [3.0]
    seq[:] = []
    sleeps[:] = []

    def op2(req, timeout=10):
        seq.append(1)
        raise urllib.error.HTTPError(req.full_url, 429, "x", H("99"), None)
    monkeypatch.setattr(lc, "_urlopen", op2)
    lc.fetch("http://a.test/")
    assert sleeps == [10.0]  # 상한 10초


def test_main_reads_bom_json(tmp_path):
    p = tmp_path / "items.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps([{"url": "https://www.instagram.com/p/x/"}]).encode("utf-8"))
    out = tmp_path / "o.json"
    assert lc.main(["lc", str(p), str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["total"] == 1
