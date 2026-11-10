# -*- coding: utf-8 -*-
import io
import json

import link_check as lc


class Fake(object):
    """Offline fetcher: url -> dict(status, final_url, text, error)."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, url, timeout=10):
        self.calls.append(url)
        return dict(self.table.get(url, {"status": None, "error": "dns_noname", "final_url": url, "text": ""}))


def page(title, body=""):
    return "<html><head><title>%s</title></head><body><script>x</script>%s</body></html>" % (title, body)


def run(items, table, tmp_path):
    f = Fake(table)
    sleeps = []
    out = str(tmp_path / "link_check.json")
    res = lc.check_items(items, fetch=f, sleep=sleeps.append, out_path=out, robots=lambda u: True)
    return res, f, sleeps, out


def test_states(tmp_path):
    items = [
        {"url": "http://a.test/ok", "evidence": "정확한   문장"},
        {"url": "http://a.test/gone"},
        {"url": "http://a.test/forbidden"},
        {"url": "http://nodomain.test/x"},
        {"url": "http://a.test/loginwall"},
    ]
    table = {
        "http://a.test/ok": {"status": 200, "final_url": "http://a.test/ok", "text": page("제목 A", "여기 정확한 문장 있음")},
        "http://a.test/gone": {"status": 404, "final_url": "http://a.test/gone", "text": ""},
        "http://a.test/forbidden": {"status": 403, "final_url": "http://a.test/forbidden", "text": ""},
        "http://a.test/loginwall": {"status": 200, "final_url": "http://a.test/accounts/login?next=/x", "text": page("Log in")},
    }
    res, f, sleeps, out = run(items, table, tmp_path)
    st = [r["state"] for r in res["results"]]
    assert st == ["opened", "dead", "unverified", "dead", "unverified"]
    assert res["results"][0]["title"] == "제목 A"
    assert res["results"][0]["evidence_found"] is True
    assert res["results"][1]["status_code"] == 404
    assert res["results"][3]["reason"] == "dns_noname"
    assert res["results"][4]["reason"] == "login"
    with io.open(out, encoding="utf-8") as fh:
        assert json.load(fh)["summary"]["total"] == 5


def test_410_is_dead_and_timeout_unverified(tmp_path):
    table = {
        "http://a.test/g": {"status": 410, "final_url": "http://a.test/g", "text": ""},
        "http://a.test/t": {"status": None, "error": "timeout", "final_url": "http://a.test/t", "text": ""},
    }
    res, _, _, _ = run([{"url": "http://a.test/g"}, {"url": "http://a.test/t"}], table, tmp_path)
    assert [r["state"] for r in res["results"]] == ["dead", "unverified"]


def test_login_hosts_not_opened(tmp_path):
    items = [{"url": "https://www.instagram.com/p/abc/"}, {"url": "https://www.facebook.com/x"},
             {"url": "https://blog.naver.com/x"}]
    res, f, _, _ = run(items, {}, tmp_path)
    assert f.calls == []
    assert all(r["state"] == "unverified" and r["reason"] == "login_host_skipped" for r in res["results"])


def test_evidence_missing_and_conflict(tmp_path):
    items = [{"url": "http://a.test/p", "title": "완전히 다른 제목", "evidence": "없는 문장"}]
    table = {"http://a.test/p": {"status": 200, "final_url": "http://a.test/p", "text": page("실제 페이지 제목")}}
    res, _, _, _ = run(items, table, tmp_path)
    r = res["results"][0]
    assert r["evidence_found"] is False
    assert r["conflict"] is True
    assert res["conflicts"] and res["conflicts"][0]["url"] == "http://a.test/p"


def test_title_suffix_is_not_conflict(tmp_path):
    items = [{"url": "http://a.test/p", "title": "실제 제목"}]
    table = {"http://a.test/p": {"status": 200, "final_url": "http://a.test/p", "text": page("실제 제목 - 사이트명")}}
    res, _, _, _ = run(items, table, tmp_path)
    assert res["results"][0]["conflict"] is False


def test_youtube_uses_oembed_only(tmp_path):
    yt = "https://youtu.be/dQw4w9WgXcQ"
    oe = lc.oembed_url(yt)
    assert oe.startswith("https://www.youtube.com/oembed?url=") and "format=json" in oe
    body = json.dumps({"title": "Never Gonna", "author_name": "Rick"})
    table = {oe: {"status": 200, "final_url": oe, "text": body}}
    items = [{"url": yt, "title": "Never Gonna", "account": "Rick", "evidence": "never gonna"},
             {"url": yt, "account": "Someone Else"}]
    res, f, _, _ = run(items, table, tmp_path)
    assert f.calls == [oe, oe]
    r0, r1 = res["results"]
    assert r0["state"] == "opened" and r0["title"] == "Never Gonna" and r0["channel"] == "Rick"
    assert r0["conflict"] is False and r0["evidence_found"] is True
    assert r1["conflict"] is True


def test_youtube_oembed_404_dead_401_unverified(tmp_path):
    a, b = "https://youtu.be/AAAAAAAAAAA", "https://youtu.be/BBBBBBBBBBB"
    table = {lc.oembed_url(a): {"status": 404, "final_url": "", "text": ""},
             lc.oembed_url(b): {"status": 401, "final_url": "", "text": ""}}
    res, _, _, _ = run([{"url": a}, {"url": b}], table, tmp_path)
    assert [r["state"] for r in res["results"]] == ["dead", "unverified"]


def test_robots_disallow_unverified(tmp_path):
    f = Fake({"http://a.test/x": {"status": 200, "final_url": "http://a.test/x", "text": page("t")}})
    res = lc.check_items([{"url": "http://a.test/x"}], fetch=f, sleep=lambda s: None,
                         out_path=str(tmp_path / "o.json"), robots=lambda u: False)
    assert res["results"][0]["reason"] == "robots_denied" and f.calls == []


def test_rate_limit_one_second_between_requests(tmp_path):
    items = [{"url": "http://a.test/1"}, {"url": "http://a.test/2"}]
    table = {u["url"]: {"status": 200, "final_url": u["url"], "text": page("t")} for u in items}
    _, _, sleeps, _ = run(items, table, tmp_path)
    assert sleeps == [1.0]


def test_summary_line(tmp_path):
    items = [{"url": "http://a.test/ok", "evidence": "abc"}, {"url": "http://a.test/gone"}]
    table = {"http://a.test/ok": {"status": 200, "final_url": "http://a.test/ok", "text": page("t", "abc")},
             "http://a.test/gone": {"status": 404, "final_url": "", "text": ""}}
    res, _, _, _ = run(items, table, tmp_path)
    assert res["summary_line"] == "링크 2 중 열림 1 · 막힘 0 · 없음 1 · 근거 원문 확인 1"


def test_real_fetch_retries_once(monkeypatch):
    calls = []

    def boom(req, timeout=10):
        calls.append(1)
        raise OSError("x")

    monkeypatch.setattr(lc, "_urlopen", boom)
    monkeypatch.setattr(lc.time, "sleep", lambda s: None)
    r = lc.fetch("http://a.test/")
    assert len(calls) == 2 and r["status"] is None
