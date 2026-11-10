# -*- coding: utf-8 -*-
"""고유 ID 추출 (v1.2 · 파이썬 3.8.6). 원칙: 애매하면 합치지 않는다(보존).

- 호스트는 소문자 + 끝 `.` 제거 뒤 모든 분기에서 쓴다. 플랫폼(유튜브·X·틱톡·인스타·스레드)은 호스트 정확 일치
  (`h == d` 또는 `h.endswith("." + d)`)로만 인정한다.
- 플랫폼 ID 는 경로 «세그먼트 전체»가 패턴과 일치할 때만 뽑는다(뒤에 잘못된 문자가 붙으면 None + 사유).
  못 뽑으면 None — 버리지 말고 id=None 으로 남겨 사람이 본다.
- 일반 웹: `www.` 만 제거 · 경로 대소문자 보존 · 쿼리는 `utm_*`·`fbclid`·`gclid`·`igsh`·`igshid` 5종만 제거하고
  나머지는 **원래 순서·원문 그대로** 보존(`ref`·`si`·`spm`·`mc_*` 도 보존) · 포트는 스킴 기본값(http:80·https:443)만 제거 ·
  조각(#)은 `#/`·`#!` 로 시작할 때만 보존 · 끝 `/` 제거.
- 틱톡 단축 주소(vm.·vt.)는 해석 단계(리다이렉트 추적)가 없으므로 None + 사유.
`norm_id_reason(url)` 은 (ID, 사유) 를 돌려준다. 사유가 빈 문자열이면 정상.
"""
import re
from urllib.parse import unquote_plus, urlparse

_ID11 = re.compile(r"[A-Za-z0-9_-]{11}")
_IDWORD = re.compile(r"[A-Za-z0-9_-]+")
_DIGITS = re.compile(r"[0-9]+")
_TRACK_EXACT = frozenset(["fbclid", "gclid", "igsh", "igshid"])
_DEFAULT_PORT = {"http": 80, "https": 443}


def _on(h, domain):
    return h == domain or h.endswith("." + domain)


def _is_tracking(key):
    k = key.lower()
    return k in _TRACK_EXACT or k.startswith("utm_")


def _segments(path):
    return [s for s in path.split("/") if s]


def _after(segs, markers, pattern):
    """markers 중 하나인 세그먼트의 다음 세그먼트를 찾는다. (found_marker, id 또는 None)."""
    for i, s in enumerate(segs):
        if s in markers and i + 1 < len(segs):
            nxt = segs[i + 1]
            return True, (nxt if pattern.fullmatch(nxt) else None)
    return False, None


def _web(u, h):
    path = u.path.rstrip("/")
    out = "web:" + h
    try:
        port = u.port
        bad = False
    except ValueError:
        port, bad = None, True
    if bad:
        out += ":invalid"
    elif port is not None and port != _DEFAULT_PORT.get((u.scheme or "").lower()):
        out += ":" + str(port)
    out += path
    kept = []
    for part in u.query.split("&"):
        if not part:
            continue
        key = unquote_plus(part.split("=", 1)[0])
        if not _is_tracking(key):
            kept.append(part)  # 원문 그대로 · 순서 보존
    if kept:
        out += "?" + "&".join(kept)
    if u.fragment[:1] in ("/", "!"):
        out += "#" + u.fragment
    return out


def norm_id_reason(url):
    u = urlparse(url.strip())
    host = (u.hostname or "").lower().rstrip(".")
    h = re.sub(r"^www\.", "", host)
    segs = _segments(u.path)

    if _on(h, "youtu.be") or _on(h, "youtube.com") or _on(h, "youtube-nocookie.com"):
        if _on(h, "youtu.be"):
            if segs and _ID11.fullmatch(segs[0]):
                return "yt:" + segs[0], ""
            return None, "youtube_no_video_id"
        for k, v in [p.split("=", 1) for p in u.query.split("&") if p.startswith("v=")][:1]:
            if _ID11.fullmatch(unquote_plus(v)):
                return "yt:" + unquote_plus(v), ""
        if len(segs) >= 2 and segs[0] in ("shorts", "embed", "live", "v") and _ID11.fullmatch(segs[1]):
            return "yt:" + segs[1], ""
        return None, "youtube_no_video_id"

    if _on(h, "x.com") or _on(h, "twitter.com"):
        found, ident = _after(segs, ("status", "statuses"), _DIGITS)
        if found:
            return ("x:" + ident, "") if ident else (None, "invalid_id_segment")

    if _on(h, "tiktok.com"):
        if h.split(".")[0] in ("vm", "vt") and h.count(".") >= 2:
            return None, "tiktok_short_link_unresolved"
        found, ident = _after(segs, ("video",), _DIGITS)
        if found:
            return ("tt:" + ident, "") if ident else (None, "invalid_id_segment")

    if _on(h, "instagram.com"):
        found, ident = _after(segs, ("p", "reel", "reels", "tv"), _IDWORD)
        if found:
            return ("ig:" + ident, "") if ident else (None, "invalid_id_segment")

    if _on(h, "threads.net") or _on(h, "threads.com"):
        found, ident = _after(segs, ("post",), _IDWORD)
        if found:
            return ("th:" + ident, "") if ident else (None, "invalid_id_segment")

    return _web(u, h), ""


def norm_id(url):
    return norm_id_reason(url)[0]
