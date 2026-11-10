# -*- coding: utf-8 -*-
import json

import cards_html as ch

CARDS = [
    {"no": 1, "title": "A <b>x</b>", "url": "http://a.test/1", "score": 5, "status": "opened",
     "evidence_strength": "강", "measured": True, "source": "claude"},
    {"no": 2, "title": "B", "url": "http://a.test/2", "score": 4, "status": "unverified",
     "evidence_strength": "중", "measured": False, "source": "gpt"},
    {"no": 3, "title": "C", "url": "http://a.test/3", "score": 2, "status": "dead",
     "evidence_strength": "약", "source": "claude"},
]


def test_stats_computed_from_json():
    s = ch.compute_stats(CARDS)
    assert s["total"] == 3 and s["opened"] == 1 and s["unverified"] == 1 and s["dead"] == 1
    assert s["strong"] == 1 and s["measured"] == 1 and s["gpt"] == 1
    assert s["score_avg"] == "3.7"


def test_rounding_half_up():
    s = ch.compute_stats([{"score": 4}, {"score": 5}, {"score": 4}, {"score": 4}])  # 4.25 -> 4.3
    assert s["score_avg"] == "4.3"
    assert ch.compute_stats([])["score_avg"] == "-"


def test_html_contains_chips_summary_and_escapes():
    h = ch.build_html(CARDS, title="테스트 <판>")
    for chip in ["점수 4 이상", "열어 본 것만", "근거 강", "실측한 것", "2차 조사분"]:
        assert chip in h
    assert "마음에 듦" in h and "복사" in h
    assert "<b>x</b>" not in h.split("const CARDS")[0]  # escaped in markup
    assert "테스트 &lt;판&gt;" in h
    assert "총 3건" in h


def test_embedded_json_roundtrips_and_safe():
    cards = [{"no": 1, "title": "</script><script>alert(1)</script>", "score": 3}]
    h = ch.build_html(cards, title="t")
    assert "</script><script>alert(1)" not in h
    start = h.index("const CARDS = ") + len("const CARDS = ")
    end = h.index(";\n", start)
    assert json.loads(h[start:end])[0]["title"] == cards[0]["title"]


def test_deterministic():
    assert ch.build_html(CARDS, title="t") == ch.build_html(CARDS, title="t")


def test_measured_score_overrides_estimate():
    s = ch.compute_stats([{"score": 5, "measured_score": 3}])
    assert s["score_avg"] == "3.0"
