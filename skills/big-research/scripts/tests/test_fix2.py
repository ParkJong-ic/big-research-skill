# -*- coding: utf-8 -*-
"""정정2 (반증 2회차 F1~F13 · 표 #17) — 재현 입력 + 외부 검토 반례. 모두 «보존 쪽»."""
import io
import json
import os
import urllib.request
from decimal import Decimal

import pytest

import cards_html as ch
import ledger as ledger_mod
import link_check as lc
import rounds
from ledger import BudgetExceeded, Ledger
from norm_id import norm_id, norm_id_reason

V = "dQw4w9WgXcQ"


# ---------------- F1 / F2 : norm_id ----------------
def test_f1_ref_and_si_mc_are_preserved_on_web():
    assert norm_id("https://a.test/doc?ref=releaseA") != norm_id("https://a.test/doc?ref=releaseB")
    assert norm_id("https://a.test/doc?si=1") != norm_id("https://a.test/doc?si=2")
    assert norm_id("https://a.test/doc?mc_cid=1") != norm_id("https://a.test/doc?mc_cid=2")
    assert norm_id("https://a.test/doc?spm=1") != norm_id("https://a.test/doc?spm=2")
    assert norm_id("https://a.test/doc?ref_src=a") != norm_id("https://a.test/doc?ref_src=b")


def test_f1_only_five_tracking_keys_removed():
    for q in ["utm_source=x", "utm_anything=1", "fbclid=z", "gclid=g", "igsh=4", "igshid=5"]:
        assert norm_id("https://a.test/doc?" + q) == "web:a.test/doc", q
    assert norm_id("https://a.test/doc?id=7&utm_source=x") == "web:a.test/doc?id=7"


def test_f1_query_order_and_repeats_preserved():
    assert norm_id("https://a.test/p?step=wash&step=dry") != norm_id("https://a.test/p?step=dry&step=wash")
    assert norm_id("https://a.test/p?a=1&b=2") != norm_id("https://a.test/p?b=2&a=1")


def test_f1_port_only_scheme_default_removed():
    assert norm_id("http://a.test:443/p") != norm_id("http://a.test/p")
    assert norm_id("https://a.test:80/p") != norm_id("https://a.test/p")
    assert norm_id("http://a.test:80/p") == norm_id("http://a.test/p")
    assert norm_id("https://a.test:443/p") == norm_id("https://a.test/p")
    assert norm_id("http://a.test:8080/p") != norm_id("http://a.test/p")


def test_f2_segment_must_match_whole():
    assert norm_id("https://youtu.be/" + V + "Ä") is None
    assert norm_id("https://youtu.be/" + V + "!") is None
    assert norm_id("https://instagram.com/p/ABC!DEF") is None
    assert norm_id("https://www.youtube.com/shorts/" + V + "X") is None
    assert norm_id("https://x.com/u/status/123abc") is None
    assert norm_id("https://www.tiktok.com/@u/video/77x") is None
    assert norm_id("https://www.threads.net/@u/post/Ab!c") is None
    assert norm_id("https://youtu.be/" + V + "/") == "yt:" + V
    ident, reason = norm_id_reason("https://instagram.com/p/ABC!DEF")
    assert ident is None and reason


def test_f2_host_trailing_dot_normalized_in_all_branches():
    assert norm_id("https://youtube.com./watch?v=" + V) == "yt:" + V
    assert norm_id("https://www.youtube.com./watch?v=" + V) == "yt:" + V
    assert norm_id("https://www.instagram.com./p/ABC/") == "ig:ABC"
    assert norm_id("https://x.com./u/status/5") == "x:5"
    assert norm_id("https://Example.com./a") == norm_id("https://example.com/a")


# ---------------- F3 / F4 : ledger ----------------
def _write_legacy(path, rows):
    with io.open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_f3_legacy_negative_row_rejected_not_imported(tmp_path):
    p = str(tmp_path / "l.jsonl")
    _write_legacy(p, [{"tool": "old", "unit_cost": -1, "cumulative": -1}])
    with pytest.raises(ValueError):
        Ledger(p, cap="1")
    for bad in ('"nan"', '"abc"', "null"):
        _write_legacy(p, [])
        with io.open(p, "w", encoding="utf-8") as f:
            f.write('{"tool":"o","unit_cost":%s,"cumulative":0}\n' % bad)
        with pytest.raises(ValueError):
            Ledger(str(tmp_path / "x.jsonl") if False else p, cap="1")


def test_f3_legacy_valid_rows_imported_once(tmp_path):
    p = str(tmp_path / "l.jsonl")
    _write_legacy(p, [{"tool": "o", "unit_cost": 0.25, "cumulative": 0.25},
                      {"tool": "o", "unit_cost": 0.5, "cumulative": 0.75}])
    lg = Ledger(p, cap="1")
    assert lg.cumulative() == Decimal("0.75")
    # 이관 표시(meta.legacy_imported) 뒤에는 jsonl 을 다시 옛 장부로 보지 않는다
    with io.open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": "x", "unit_cost": 0.2, "cumulative": 0.95}) + "\n")
    assert Ledger(p, cap="1").cumulative() == Decimal("0.75")


def test_f3_codex_precision_counterexample(tmp_path):
    lg = Ledger(str(tmp_path / "l.jsonl"), cap="1")
    lg.record("t", "1")
    with pytest.raises(ValueError):
        lg.record("t", "1e-28")  # 소수 6자리 초과는 받지 않는다
    with pytest.raises(ValueError):
        lg.record("t", "0.0000001")
    with pytest.raises(BudgetExceeded):
        lg.record("t", "0.000001")  # 최소 단위도 상한을 넘기면 막힘
    assert lg.cumulative() == Decimal("1")


def test_f3_micro_units_exact_sum(tmp_path):
    lg = Ledger(str(tmp_path / "l.jsonl"), cap="0.000003")
    for _ in range(3):
        lg.record("t", "0.000001")
    with pytest.raises(BudgetExceeded):
        lg.record("t", "0.000001")
    assert lg.cumulative() == Decimal("0.000003")
    with pytest.raises(ValueError):
        Ledger(str(tmp_path / "m.jsonl"), cap="1e-7")


def test_f4_first_failed_record_leaves_no_jsonl_row_and_no_resurrection(tmp_path):
    p = str(tmp_path / "l.jsonl")
    lg = Ledger(p, cap="1")
    with pytest.raises(BudgetExceeded):
        lg.record("t", "2")
    assert not os.path.exists(p) or io.open(p, encoding="utf-8").read().strip() == ""
    assert Ledger(p, cap="1").cumulative() == Decimal("0")


def test_f4_jsonl_failure_does_not_undo_committed_row_and_export_rebuilds(tmp_path):
    p = str(tmp_path / "l.jsonl")
    lg = Ledger(p, cap="1")
    os.mkdir(p)  # jsonl 경로가 폴더 → 사본 쓰기 실패
    row = lg.record("t", "0.25")
    assert row.get("jsonl_ok") is False
    assert lg.cumulative() == Decimal("0.25")  # DB 가 정본
    os.rmdir(p)
    lg.export_jsonl()
    rows = [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]
    assert [r["unit_cost"] for r in rows] == [0.25] and rows[0]["cumulative"] == 0.25
    lg.record("t", "0.5")
    lg.export_jsonl()
    assert len([x for x in io.open(p, encoding="utf-8") if x.strip()]) == 2


def test_f4_old_schema_db_refused(tmp_path):
    import sqlite3
    db = str(tmp_path / "l.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE calls (id INTEGER PRIMARY KEY, ts TEXT, tool TEXT, unit_cost TEXT, cumulative TEXT, note TEXT)")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError):
        Ledger(str(tmp_path / "l.jsonl"), cap="1")


# ---------------- F5 : rounds ----------------
def test_f5_lock_timeout_writes_no_round_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rounds, "LOCK_WAIT", 0.3)
    (tmp_path / "seen_ids.lock").write_text("x")
    with pytest.raises(TimeoutError):
        rounds.save_round(str(tmp_path), "r", [{"url": "https://a.test/1"}])
    rd = tmp_path / "research"
    assert not rd.exists() or [x for x in os.listdir(str(rd))] == []


def test_f5_rebuild_takes_lock_and_ignores_tmp(tmp_path, monkeypatch):
    rounds.save_round(str(tmp_path), "r", [{"url": "https://a.test/1"}])
    (tmp_path / "research" / "half.json.123.tmp").write_text("[{broken")
    assert rounds.rebuild_seen(str(tmp_path)) == {"web:a.test/1"}
    monkeypatch.setattr(rounds, "LOCK_WAIT", 0.3)
    (tmp_path / "seen_ids.lock").write_text("x")
    with pytest.raises(TimeoutError):
        rounds.rebuild_seen(str(tmp_path))


def test_f5_round_published_atomically_no_leftovers(tmp_path):
    p = rounds.save_round(str(tmp_path), "r", [{"url": "https://a.test/1"}])
    p2 = rounds.save_round(str(tmp_path), "r", [{"url": "https://a.test/2"}])
    names = sorted(os.listdir(str(tmp_path / "research")))
    assert len(names) == 2 and all(n.endswith(".json") for n in names)
    assert p != p2
    assert json.load(io.open(p, encoding="utf-8"))[0]["url"] == "https://a.test/1"


# ---------------- F6 / F7 / F8 / F9 / F13 : link_check ----------------
class Fake(object):
    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, url, timeout=10):
        self.calls.append(url)
        return dict(self.table.get(url, {"status": None, "error": "dns_noname", "final_url": url, "text": ""}))


def run(items, table, tmp_path):
    f = Fake(table)
    return lc.check_items(items, fetch=f, sleep=lambda s: None, out_path=str(tmp_path / "o.json"),
                          robots=lambda u: True), f


def test_f6_status_3xx_is_not_opened(tmp_path):
    for code in (300, 301, 302, 303, 307, 308):
        res, _ = run([{"url": "http://a.test/p"}],
                     {"http://a.test/p": {"status": code, "final_url": "http://a.test/p", "text": ""}}, tmp_path)
        r = res["results"][0]
        assert r["state"] == "unverified" and r["reason"] == "redirect_unfollowed_%d" % code, code


@pytest.mark.parametrize("u", ["https://www.instagram.com./p/ABC/", "https://INSTAGRAM.COM./x",
                               "https://threads.net./a", "http://www.facebook.com./a"])
def test_f6_login_host_trailing_dot(u):
    assert lc._is_login_host(u)


def test_f6_login_host_trailing_dot_is_skipped(tmp_path):
    res, f = run([{"url": "https://www.instagram.com./p/ABC/"}], {}, tmp_path)
    assert f.calls == [] and res["results"][0]["reason"] == "login_host_skipped"


def test_f7_dns_nodata_is_not_noname(monkeypatch):
    import socket
    import urllib.error
    monkeypatch.setattr(lc.time, "sleep", lambda s: None)

    def nodata(req, timeout=10):
        raise urllib.error.URLError(socket.gaierror(-5, "no data"))
    monkeypatch.setattr(lc, "_urlopen", nodata)
    assert lc.fetch("http://a.test/")["error"] == "dns_nodata"
    assert lc._classify({"status": None, "error": "dns_nodata"}) == ("unverified", "dns_nodata")
    assert lc._classify({"status": None, "error": "dns_noname"}) == ("dead", "dns_noname")


def test_f8_retry_after_parse():
    import email.utils
    import datetime as dt
    g = lambda v: lc._retry_after({"Retry-After": v})
    assert g("0") == 1.0 and g("3") == 3.0 and g("99") == 10.0
    assert g("nan") == 1.0 and g("inf") == 1.0 and g("abc") == 1.0 and g("-5") == 1.0
    assert lc._retry_after({}) == 1.0
    soon = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=6), usegmt=True)
    assert 4.0 <= g(soon) <= 7.0
    past = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1), usegmt=True)
    assert g(past) == 1.0
    far = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5), usegmt=True)
    assert g(far) == 10.0


def test_f9_surrogate_url_does_not_stop_the_run(tmp_path):
    items = [{"url": "http://a.test/\ud800"}, {"url": "http://a.test/ok"}]
    table = {"http://a.test/ok": {"status": 200, "final_url": "http://a.test/ok",
                                  "text": "<html><head><title>t</title></head></html>"}}
    res, _ = run(items, table, tmp_path)
    assert res["results"][0]["state"] == "unverified" and res["results"][0]["reason"] == "encode_error"
    assert "\\ud800" in res["results"][0]["url"]
    assert res["results"][1]["state"] == "opened"
    out = json.load(io.open(str(tmp_path / "o.json"), encoding="utf-8"))
    assert out["summary"]["total"] == 2
    lines = [json.loads(x) for x in io.open(str(tmp_path / "o.partial.jsonl"), encoding="utf-8") if x.strip()]
    assert len(lines) == 2


def test_f10_results_carry_idx(tmp_path):
    res, _ = run([{"title": "no url"}, {"url": "http://a.test/ok"}, "not a dict"], {}, tmp_path)
    assert [r["idx"] for r in res["results"]] == [0, 1, 2]
    assert res["results"][0]["reason"].startswith("error:")
    assert res["results"][2]["reason"].startswith("error:")


def test_f13_empty_evidence_recorded_before_early_return(tmp_path):
    res, f = run([{"url": "https://instagram.com/p/ABC/", "evidence": "   "},
                  {"url": "http://a.test/g", "evidence": ""}],
                 {"http://a.test/g": {"status": 404, "final_url": "", "text": ""}}, tmp_path)
    assert res["results"][0]["evidence_status"] == "empty" and res["results"][0]["evidence_found"] is None
    assert res["results"][1]["evidence_status"] == "empty"
    assert res["summary"]["evidence_status"]["empty"] == 2


# ---------------- F10 / F11 / F12 : cards_html ----------------
def test_f10_cards_link_by_idx_and_keep_error_items():
    items = [{"title": "URL 없음"}, {"url": "http://a.test/ok", "title": "정상"}, "not a dict"]
    results = {"results": [
        {"idx": 0, "url": "", "state": "unverified", "reason": "error:KeyError", "evidence_status": "not_checked"},
        {"idx": 1, "url": "http://a.test/ok", "state": "opened", "reason": "", "evidence_status": "not_found",
         "evidence_scope": "page", "truncated": True, "decode_issue": True, "check_method": "page"},
        {"idx": 2, "url": "", "state": "unverified", "reason": "error:TypeError", "evidence_status": "not_checked"}]}
    cards = ch.cards_from_link_check(items, results)
    assert [c["status"] for c in cards] == ["unverified", "opened", "unverified"]
    assert cards[0]["state_reason"] == "error:KeyError"
    assert cards[1]["evidence_scope"] == "page" and cards[1]["truncated"] is True and cards[1]["decode_issue"] is True
    h = ch.build_html(cards, title="t")
    assert "잘림" in h and "메타데이터" in h  # 화면 메타 줄 문구가 페이지에 있다


def test_f10_idx_order_independent():
    items = [{"url": "a"}, {"url": "b"}]
    results = {"results": [{"idx": 1, "url": "b", "state": "dead"}, {"idx": 0, "url": "a", "state": "opened"}]}
    cards = ch.cards_from_link_check(items, results)
    assert [c["status"] for c in cards] == ["opened", "dead"]


def test_f11_decimal_score_builds_and_roundtrips():
    h = ch.build_html([{"no": 1, "score": Decimal("4.2")}, {"no": 2, "measured_score": Decimal("3")}], title="t")
    start = h.index("const CARDS = ") + len("const CARDS = ")
    data = json.loads(h[start:h.index(";\n", start)])
    assert data[0]["score"] == 4.2 and data[1]["measured_score"] == 3
    with pytest.raises(ValueError):
        ch.build_html([{"score": Decimal("NaN")}], title="t")


def test_f12_cli_failure_keeps_existing_output(tmp_path):
    out = tmp_path / "화면.html"
    out.write_text("OLD", encoding="utf-8")
    bad = tmp_path / "c.json"
    bad.write_text(json.dumps([{"no": 1}, {"no": 1}]), encoding="utf-8")
    assert ch.main(["c", str(bad), str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "OLD"
    assert not [x for x in os.listdir(str(tmp_path)) if x.endswith(".tmp")]
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps([{"no": 1, "title": "a"}]), encoding="utf-8")
    assert ch.main(["c", str(ok), str(out)]) == 0
    assert "총 1건" in out.read_text(encoding="utf-8")
    assert not [x for x in os.listdir(str(tmp_path)) if x.endswith(".tmp")]


def test_f12_link_check_main_keeps_old_output_on_bad_input(tmp_path):
    out = tmp_path / "link_check.json"
    out.write_text("OLD", encoding="utf-8")
    bad = tmp_path / "i.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        lc.main(["lc", str(bad), str(out)])
    assert out.read_text(encoding="utf-8") == "OLD"
