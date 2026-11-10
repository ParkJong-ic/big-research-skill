# -*- coding: utf-8 -*-
import time

import pytest

from norm_id import norm_id

VID = "dQw4w9WgXcQ"
SAME_VIDEO = [
    "https://www.youtube.com/watch?v=" + VID,
    "https://youtu.be/" + VID,
    "https://www.youtube.com/shorts/" + VID,
    "https://www.youtube.com/embed/" + VID,
    "https://m.youtube.com/watch?v=" + VID + "&t=30s",
]


def test_five_formats_same_id():
    ids = {norm_id(u) for u in SAME_VIDEO}
    assert ids == {"yt:" + VID}


def test_different_videos_differ():
    a = norm_id("https://www.youtube.com/watch?v=AAAAAAAAAAA")
    b = norm_id("https://www.youtube.com/watch?v=BBBBBBBBBBB")
    assert a != b and a and b


@pytest.mark.parametrize("tail", ["?si=abc123", "?igsh=xyz", "?utm_source=x&feature=share"])
def test_tracking_tails_ignored(tail):
    assert norm_id("https://youtu.be/" + VID + tail) == "yt:" + VID
    assert norm_id("https://www.instagram.com/reel/C1abcDEF2gh/" + tail) == "ig:C1abcDEF2gh"


def test_channel_url_is_none():
    assert norm_id("https://www.youtube.com/@somechannel") is None
    assert norm_id("https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx") is None


def test_instagram_host_normalization_regression():
    ids = {
        norm_id("https://instagram.com/p/Abc_123-x/"),
        norm_id("https://www.instagram.com/p/Abc_123-x/?igsh=1"),
        norm_id("https://m.instagram.com/p/Abc_123-x"),
    }
    assert ids == {"ig:Abc_123-x"}
    assert norm_id("https://www.instagram.com/reels/Zzz999/") == "ig:Zzz999"


def test_other_platforms():
    assert norm_id("https://x.com/user/status/12345?s=20") == "x:12345"
    assert norm_id("https://twitter.com/user/status/12345") == "x:12345"
    assert norm_id("https://www.tiktok.com/@u/video/777?lang=ko") == "tt:777"
    assert norm_id("https://www.threads.net/@u/post/AbC1") == "th:AbC1"


def test_web_fallback_keeps_path_case_and_strips_slash():
    assert norm_id("https://Example.com/Path/") == "web:example.com/Path"
    assert norm_id("https://www.example.com/a") == "web:example.com/a"


def test_whitespace_stripped():
    assert norm_id("  https://youtu.be/" + VID + "\n") == "yt:" + VID


@pytest.mark.perf
def test_perf_10k_under_1s():
    t = time.time()
    for _ in range(10000):
        norm_id(SAME_VIDEO[0])
    assert time.time() - t < 1.0


# ---- 정정1 (반증 1회차 #1·#2) ----
def test_web_query_kept_except_tracking():
    assert norm_id("https://a.com/item?id=1") != norm_id("https://a.com/item?id=2")
    assert norm_id("https://a.com/item?id=1&utm_source=x&fbclid=z&gclid=g") == "web:a.com/item?id=1"
    assert norm_id("https://a.com/p?b=2&a=1") != norm_id("https://a.com/p?a=1&b=2")  # 순서 보존(정정2)
    assert norm_id("https://a.com/p?igsh=4&igshid=5&utm_x=1") == "web:a.com/p"


def test_web_path_case_and_fragment_rules():
    assert norm_id("https://a.com/Report") != norm_id("https://a.com/report")
    assert norm_id("https://a.com/#/item/1") != norm_id("https://a.com/#/item/2")
    assert norm_id("https://a.com/#!/x") != norm_id("https://a.com/#!/y")
    assert norm_id("https://a.com/page#section") == norm_id("https://a.com/page")


def test_web_m_prefix_kept_www_removed():
    assert norm_id("https://m.a.com/x") == "web:m.a.com/x"
    assert norm_id("https://www.a.com/x") == "web:a.com/x"


def test_music_youtube_is_youtube():
    assert norm_id("https://music.youtube.com/watch?v=" + VID) == "yt:" + VID
    assert norm_id("https://music.youtube.com/watch?v=AAAAAAAAAAA") != norm_id("https://music.youtube.com/watch?v=BBBBBBBBBBB")


def test_host_must_match_exactly():
    assert norm_id("https://notinstagram.com/p/ABC") == "web:notinstagram.com/p/ABC"
    assert norm_id("https://faketiktok.com/@u/video/777") .startswith("web:")
    assert norm_id("https://notyoutube.com/watch?v=" + VID).startswith("web:")
    assert norm_id("https://evilx.com/u/status/12345").startswith("web:")


def test_id_boundary_and_ascii_only():
    assert norm_id("https://youtu.be/" + VID + "XYZ") is None
    assert norm_id("https://youtu.be/Äbcdefghijk") is None
    assert norm_id("https://www.youtube.com/watch?v=" + VID + "XYZ") is None
    assert norm_id("https://www.youtube.com/shorts/" + VID + "?feature=share") == "yt:" + VID


def test_tiktok_short_link_is_none_with_reason():
    import norm_id as n
    assert norm_id("https://vm.tiktok.com/ZMabc/") is None
    assert norm_id("https://vt.tiktok.com/ZSabc/") is None
    ident, reason = n.norm_id_reason("https://vm.tiktok.com/ZMabc/")
    assert ident is None and "tiktok" in reason and "unresolved" in reason
    assert n.norm_id_reason("https://youtu.be/" + VID) == ("yt:" + VID, "")
