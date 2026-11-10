# -*- coding: utf-8 -*-
"""정정1 (반증 1회차 #13~#16) — cards_html 새 규칙."""
import io
import json

import pytest

import cards_html as ch


def embedded(h):
    start = h.index("const CARDS = ") + len("const CARDS = ")
    end = h.index(";\n", start)
    return json.loads(h[start:end])


def test_comment_script_title_does_not_break_page():
    cards = [{"no": 1, "title": "<!-- <script>", "score": 3}, {"no": 2, "title": "정상", "score": 4}]
    h = ch.build_html(cards, title="t")
    script = h[h.index("const CARDS"):]
    assert "<!--" not in script.split("\n", 1)[0]
    assert "<script>" not in script.split("\n", 1)[0]
    assert "\\u003c!-- \\u003cscript\\u003e" in h
    assert embedded(h)[0]["title"] == "<!-- <script>"


def test_json_escapes_lt_gt_amp():
    h = ch.build_html([{"no": 1, "title": "a<b>&c", "score": 1}], title="t")
    line = h[h.index("const CARDS"):].split("\n", 1)[0]
    assert "<" not in line.replace("<\\", "") and ">" not in line and "&" not in line
    assert embedded(h)[0]["title"] == "a<b>&c"


@pytest.mark.parametrize("bad", [[{"no": 1}, {"no": 1}], [{"no": "1"}], [{"no": 1.5}], [{"no": True}]])
def test_bad_no_raises_before_build(bad):
    with pytest.raises(ValueError):
        ch.build_html(bad, title="t")


def test_missing_no_gets_sequence_number():
    h = ch.build_html([{"title": "a"}, {"title": "b"}], title="t")
    assert [c["no"] for c in embedded(h)] == [1, 2]


def test_picks_keyed_separately_from_display_no():
    h = ch.build_html([{"no": 7, "title": "a"}, {"no": 3, "title": "b"}], title="t")
    assert "picks[i]" in h or "picks[k]" in h or "picks[key]" in h
    assert "picks[no]" not in h


def test_copy_feedback_in_page():
    h = ch.build_html([{"no": 1, "title": "a"}], title="t")
    assert 'id="copystat"' in h
    assert "복사됨" in h and "복사 실패" in h
    assert "execCommand" in h and "selectNodeContents" in h


@pytest.mark.parametrize("c", [{"score": float("nan")}, {"score": float("inf")}, {"measured_score": "abc"},
                               {"score": True}, {"score": "4"}])
def test_bad_score_raises(c):
    with pytest.raises(ValueError):
        ch.compute_stats([c])


def test_measured_must_be_bool():
    with pytest.raises(ValueError):
        ch.build_html([{"no": 1, "measured": "yes"}], title="t")
    ch.build_html([{"no": 1, "measured": True}, {"no": 2, "measured": False}, {"no": 3}], title="t")


def test_unknown_status_counted():
    cards = [{"status": "opened"}, {"status": "weird"}, {}, {"status": None}]
    s = ch.compute_stats(cards)
    assert s["opened"] == 1 and s["unknown"] == 3
    h = ch.build_html([dict(c, no=i + 1) for i, c in enumerate(cards)], title="t")
    assert "상태 미상 <b>3</b>" in h


def test_cards_from_link_check_merges_fields():
    items = [{"url": "http://a.test/1", "title": "A", "score": 4, "evidence_strength": "강", "source": "gpt", "no": 5},
             {"url": "http://a.test/2", "title": "B"}]
    lcj = {"results": [
        {"url": "http://a.test/1", "state": "opened", "reason": "", "evidence_status": "found", "evidence_found": True,
         "conflict": False, "account_match": "match", "title_match": "match", "check_method": "page"},
        {"url": "http://a.test/2", "state": "dead", "reason": "http_404", "evidence_status": "not_checked",
         "evidence_found": None, "conflict": False, "account_match": "not_compared", "title_match": "not_compared",
         "check_method": "page"}]}
    cards = ch.cards_from_link_check(items, lcj)
    assert cards[0]["status"] == "opened" and cards[0]["no"] == 5 and cards[0]["source"] == "gpt"
    assert cards[0]["score"] == 4 and cards[0]["evidence_strength"] == "강"
    assert cards[0]["evidence_status"] == "found" and cards[0]["check_method"] == "page"
    assert cards[1]["status"] == "dead" and cards[1]["state_reason"] == "http_404" and cards[1]["no"] == 2
    assert "status" not in items[0]  # 원본 변형 금지
    ch.build_html(cards, title="t")


def test_cards_from_link_check_length_mismatch_and_path(tmp_path):
    with pytest.raises(ValueError):
        ch.cards_from_link_check([{"url": "a"}], {"results": []})
    p = tmp_path / "lc.json"
    p.write_text(json.dumps({"results": [{"url": "a", "state": "opened"}]}), encoding="utf-8")
    assert ch.cards_from_link_check([{"url": "a"}], str(p))[0]["status"] == "opened"


def test_unknown_state_becomes_missing_status():
    cards = ch.cards_from_link_check([{"url": "a"}], {"results": [{"url": "a", "state": "???"}]})
    assert cards[0].get("status") in (None, "")


def test_main_bom_and_link_check_flag(tmp_path):
    items = tmp_path / "i.json"
    items.write_bytes(b"\xef\xbb\xbf" + json.dumps([{"url": "http://a.test/1", "title": "x"}]).encode("utf-8"))
    lcp = tmp_path / "lc.json"
    lcp.write_text(json.dumps({"results": [{"url": "http://a.test/1", "state": "opened"}]}), encoding="utf-8")
    out = tmp_path / "o.html"
    assert ch.main(["c", "--link-check", str(items), str(lcp), str(out), "제목"]) == 0
    assert "총 1건" in out.read_text(encoding="utf-8")
    cards = tmp_path / "c.json"
    cards.write_bytes(b"\xef\xbb\xbf" + json.dumps([{"no": 1, "title": "a"}]).encode("utf-8"))
    assert ch.main(["c", str(cards), str(tmp_path / "o2.html")]) == 0
