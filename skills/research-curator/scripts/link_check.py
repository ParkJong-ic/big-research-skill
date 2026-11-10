# -*- coding: utf-8 -*-
"""링크 실재 확인 · 근거 원문 대조 (v1.2 · 파이썬 3.8.6 · 외부 패키지 0).

사용: python link_check.py 항목.json [link_check.json]      (콘솔 한글: PYTHONIOENCODING=utf-8)
항목 = [{"url":..., "title":(선택), "account":(선택), "evidence":(선택)}, ...] 또는 {"cards":[...]}

상태(state)와 사유(reason):
  opened      열림(사유 없음).
  unverified  막힘/미확인: login_host_skipped · login_redirect · login · blocked_page · soft404_suspect ·
              oembed_invalid · robots_denied · robots_unknown · redirect_unfollowed_<코드>(3xx 를 따라가지 못함 — 열림으로 확정하지 않음) ·
              http_<코드> · dns_temp · dns_nodata · timeout · error · encode_error(UTF-8 로 쓸 수 없는 문자) ·
              error:<예외 이름>(항목 하나가 예외로 실패 — 전체는 계속됨)
  dead        없음: http_404 · http_410 · dns_noname(이름 자체가 없음) — 유튜브는 oEmbed 로만 확인(check_method=oembed).
규칙: 요청 간격 1초(리다이렉트 요청 포함) · 재시도 1회(429 는 Retry-After, 최대 10초) · 타임아웃 10초는 «요청 한 번 기준»
  (항목 전체 기한은 없음) · 로그인이 필요한 사이트로 가는 리다이렉트는 따라가지 않는다.
한계: 소프트 404(200 으로 «없음» 화면)와 JS 로 그려지는 본문은 완전히 판별하지 못한다 — 제목 단서로 의심만 표시한다.
"""
import codecs
import datetime
import difflib
import email.utils
import html
import io
import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse
from urllib import robotparser

from norm_id import norm_id

UA = "research_kit-linkcheck/1.0"
TIMEOUT = 10
GAP = 1.0
MAX_BYTES = 1000000
RETRY_AFTER_MAX = 10.0

# 로그인이 있어야 내용이 보이는 곳: 열지 않고 unverified 로 따로 모은다(§4 도구로 표본 재확인).
LOGIN_HOSTS = ("instagram.com", "facebook.com", "fb.com", "x.com", "twitter.com", "threads.net", "threads.com",
               "tiktok.com", "linkedin.com", "naver.com", "kakao.com")
LOGIN_PATH = re.compile(r"(^|/)(login|signin|sign-in|log-in|auth)(/|$)", re.I)
BLOCK_MARKERS = ("captcha", "access denied", "are you a robot")
SOFT404 = re.compile(r"(?<!\d)404(?!\d)|not found|페이지를 찾을 수 없", re.I)
INLINE_TAGS = "b|i|em|strong|span|a|u|mark|small|sub|sup"

# 이름 자체가 없음(EAI_NONAME)만 dead. 주소 데이터 없음(EAI_NODATA·-5)은 dns_nodata(미확인), 나머지는 dns_temp.
_NODATA = set([-5])
if hasattr(socket, "EAI_NODATA"):
    _NODATA.add(socket.EAI_NODATA)


class _Refused(Exception):
    """따라가면 안 되는 리다이렉트(로그인 사이트·동의 화면)."""

    def __init__(self, kind, url):
        Exception.__init__(self, kind)
        self.kind = kind
        self.url = url


def _host(url):
    return re.sub(r"^(www\.|m\.)+", "", (urlparse(url).hostname or "").lower().rstrip("."))


def _is_login_host(url):
    h = _host(url)
    return any(h == d or h.endswith("." + d) for d in LOGIN_HOSTS)


def _is_consent_host(url):
    h = (urlparse(url).hostname or "").lower().rstrip(".")
    return h.startswith("consent.") or ".consent." in h


def _looks_login(final_url):
    u = urlparse(final_url)
    return u.netloc.lower().startswith("accounts.google.") or bool(LOGIN_PATH.search(u.path))


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _is_login_host(newurl) or _looks_login(newurl):
            raise _Refused("login_redirect", newurl)
        if _is_consent_host(newurl):
            raise _Refused("consent_redirect", newurl)
        time.sleep(GAP)  # 리다이렉트 요청도 간격 1초
        if code == 308:  # 3.8.6 표준 처리기는 308 을 모른다 — 307(메서드 유지)과 같게 취급
            code = 307
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)

    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302


def _build_opener(*extra):
    return urllib.request.build_opener(_RedirectHandler(), *extra)


_OPENER = _build_opener()


def _default_urlopen(req, timeout=TIMEOUT):
    return _OPENER.open(req, timeout=timeout)


_urlopen = _default_urlopen


def oembed_url(url):
    return "https://www.youtube.com/oembed?url=%s&format=json" % quote(url, safe="")


def _retry_after(headers):
    """Retry-After(초 또는 HTTP 날짜) → 대기 초. 유한값만, 최소 GAP(1초)·최대 RETRY_AFTER_MAX(10초)."""
    raw = headers.get("Retry-After") if headers is not None else None
    v = None
    if raw is not None:
        try:
            v = float(str(raw).strip())
        except ValueError:
            try:
                dt = email.utils.parsedate_to_datetime(str(raw).strip())
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                v = (dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            except (TypeError, ValueError, IndexError):
                v = None
    if v is None or v != v or v in (float("inf"), float("-inf")):
        return GAP
    return float(min(max(v, GAP), RETRY_AFTER_MAX))


def _charset(resp_headers, raw):
    cs = resp_headers.get_content_charset() if resp_headers is not None else None
    if not cs:
        m = re.search(br"(?i)<meta[^>]+charset\s*=\s*[\"']?\s*([\w-]+)", raw[:4096])
        cs = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    return cs


def _decode(raw, cs, truncated):
    """(text, decode_issue). 잘린 끝의 반쪽 글자는 문제로 세지 않는다."""
    try:
        codecs.lookup(cs)
    except LookupError:
        cs = "utf-8"
        issue_cs = True
    else:
        issue_cs = False
    try:
        dec = codecs.getincrementaldecoder(cs)("strict")
        return dec.decode(raw, final=not truncated), issue_cs
    except (UnicodeDecodeError, LookupError, TypeError):
        return raw.decode(cs, "replace"), True


def fetch(url, timeout=TIMEOUT):
    """한 주소를 가져온다. 실패하면 1초(429 는 Retry-After) 뒤 1회 재시도.
    반환: status·final_url·text·error·truncated·decode_issue."""
    last = None
    wait = GAP
    for attempt in range(2):
        if attempt:
            time.sleep(wait)
        wait = GAP
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"})
            resp = _urlopen(req, timeout=timeout)
            try:
                raw = resp.read(MAX_BYTES + 1)
                final = resp.geturl()
                code = resp.getcode()
                cs = _charset(resp.headers, raw)
            finally:
                resp.close()
            truncated = len(raw) > MAX_BYTES
            raw = raw[:MAX_BYTES]
            text, issue = _decode(raw, cs, truncated)
            last = {"status": code, "final_url": final, "text": text, "error": None,
                    "truncated": truncated, "decode_issue": issue}
            if code < 500:
                return last
        except _Refused as e:
            return {"status": None, "final_url": e.url, "text": "", "error": e.kind,
                    "truncated": False, "decode_issue": False}
        except urllib.error.HTTPError as e:
            last = {"status": e.code, "final_url": url, "text": "", "error": None,
                    "truncated": False, "decode_issue": False}
            if e.code == 429:
                wait = _retry_after(getattr(e, "headers", None))
            elif e.code < 500:
                return last
        except Exception as e:  # URLError·시간초과·OSError·http.client 오류
            reason = getattr(e, "reason", e)
            if isinstance(reason, socket.gaierror):
                if reason.errno == socket.EAI_NONAME:
                    err = "dns_noname"
                elif reason.errno in _NODATA:
                    err = "dns_nodata"
                else:
                    err = "dns_temp"
            elif isinstance(reason, socket.timeout) or isinstance(e, socket.timeout):
                err = "timeout"
            else:
                err = "error"
            last = {"status": None, "final_url": url, "text": "", "error": err,
                    "truncated": False, "decode_issue": False}
    return last


def _norm(s):
    t = unicodedata.normalize("NFKC", html.unescape(s or ""))
    return re.sub(r"\s+", " ", t).strip().lower()


def _page_text(raw):
    t = re.sub(r"(?s)<!--.*?-->", " ", raw)
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
    t = re.sub(r"(?is)</?(?:%s)(?=[\s/>])[^>]*>" % INLINE_TAGS, "", t)  # 인라인 태그는 공백 없이
    return _norm(re.sub(r"(?s)<[^>]+>", " ", t))


def _page_title(raw):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""


def _similar(a, b):
    na, nb = _norm(a), _norm(b)
    return na in nb or nb in na or difflib.SequenceMatcher(None, na, nb).ratio() >= 0.6


def _acct_norm(a):
    return _norm(a).lstrip("@").strip()


def _handle_from_url(u):
    m = re.search(r"/@([^/?#]+)", u or "")
    return _acct_norm(m.group(1)) if m else ""


def _page_accounts(raw, final_url):
    names = set()
    for tag in re.findall(r"(?is)<meta\b[^>]*>", raw):
        k = re.search(r"(?i)\b(?:name|property)\s*=\s*[\"']([^\"']+)[\"']", tag)
        v = re.search(r"(?i)\bcontent\s*=\s*[\"']([^\"']*)[\"']", tag)
        if k and v and k.group(1).lower() in ("author", "article:author", "og:site_name", "twitter:creator",
                                              "twitter:site"):
            n = _acct_norm(v.group(1))
            if n:
                names.add(n)
    h = _handle_from_url(final_url)
    if h:
        names.add(h)
    return names


def make_robots(fetch_fn, gap):
    """robots(url) → True(허용) / False(금지: 401·403 또는 Disallow) / None(알 수 없음: 429·5xx·시간초과 등)."""
    cache = {}

    def allowed(url):
        u = urlparse(url)
        base = "%s://%s" % (u.scheme or "http", u.netloc)
        if base not in cache:
            gap()
            r = fetch_fn(base + "/robots.txt")
            st = r.get("status")
            if st == 200:
                rp = robotparser.RobotFileParser()
                rp.parse(r.get("text", "").splitlines())
                cache[base] = rp
            elif st in (404, 410):
                rp = robotparser.RobotFileParser()
                rp.parse([])
                cache[base] = rp  # 404 = robots 없음 = 허용
            elif st in (401, 403):
                cache[base] = "deny"
            else:
                cache[base] = "unknown"
        v = cache[base]
        if v == "deny":
            return False
        if v == "unknown":
            return None
        return v.can_fetch(UA, url)
    return allowed


def _classify(r):
    """fetch 결과 → (state, reason)."""
    st = r.get("status")
    if st is None:
        err = r.get("error") or "error"
        if err == "login_redirect":
            return "unverified", "login_redirect"
        if err == "consent_redirect":
            return "unverified", "blocked_page"
        if err in ("dns", "dns_noname"):
            return "dead", "dns_noname"
        return "unverified", err
    if 300 <= st < 400:  # 따라가지 못한 리다이렉트(Location 없음·루프·미지원 코드)는 열림으로 확정하지 않는다
        return "unverified", "redirect_unfollowed_%d" % st
    if st in (404, 410):
        return "dead", "http_%d" % st
    if st >= 400:
        return "unverified", "http_%d" % st
    final = r.get("final_url") or ""
    if _is_consent_host(final):
        return "unverified", "blocked_page"
    if _is_login_host(final):
        return "unverified", "login_redirect"
    if _looks_login(final):
        return "unverified", "login"
    return "opened", ""


def _blank(item, idx=None):
    url = item.get("url") if isinstance(item, dict) else None
    url = url if isinstance(url, str) else ""
    try:
        ident = norm_id(url) if url else None
    except Exception:
        ident = None
    return {"idx": idx, "url": url, "id": ident, "state": "", "reason": "", "status_code": None, "final_url": url,
            "title": "", "channel": "", "check_method": "", "evidence_found": None,
            "evidence_status": "not_checked", "evidence_scope": "", "truncated": False, "decode_issue": False,
            "account_match": "not_compared", "title_match": "not_compared", "conflict": False,
            "conflict_reasons": []}


def _evidence_empty(item):
    """입력 근거가 있는데 정규화하면 빈칸이면 True (분기 전에 기록)."""
    ev = item.get("evidence")
    return ev is not None and not _norm(str(ev))


def _evidence(res, item, hay):
    if "evidence" not in item or item.get("evidence") is None or res["evidence_status"] == "empty":
        return
    ne = _norm(str(item["evidence"]))
    res["evidence_found"] = ne in hay
    res["evidence_status"] = "found" if res["evidence_found"] else "not_found"


def check_one(item, fetch_fn, gap, robots):
    url = item["url"]
    res = _blank(item)
    yt = bool(res["id"] and res["id"].startswith("yt:"))
    res["check_method"] = "oembed" if yt else "page"
    if _evidence_empty(item):
        res["evidence_status"] = "empty"  # 열리지 않은 항목도 «빈 근거»를 기록한다
    if not yt:
        if _is_login_host(url):
            res.update(state="unverified", reason="login_host_skipped")
            return res
        ok = robots(url)
        if ok is None:
            res.update(state="unverified", reason="robots_unknown")
            return res
        if not ok:
            res.update(state="unverified", reason="robots_denied")
            return res
    gap()
    r = fetch_fn(oembed_url(url) if yt else url)
    res["status_code"] = r.get("status")
    res["final_url"] = url if yt else (r.get("final_url") or url)
    res["truncated"] = bool(r.get("truncated"))
    res["decode_issue"] = bool(r.get("decode_issue"))
    state, reason = _classify(r)
    res["state"], res["reason"] = state, reason
    if state != "opened":
        return res
    observed = set()
    if yt:
        res["evidence_scope"] = "metadata"
        try:
            d = json.loads(r.get("text") or "")
        except ValueError:
            d = None
        if not isinstance(d, dict) or not isinstance(d.get("title"), str) or not d["title"].strip():
            res.update(state="unverified", reason="oembed_invalid")
            return res
        res["title"] = d["title"]
        res["channel"] = d.get("author_name") if isinstance(d.get("author_name"), str) else ""
        hay = _norm(res["title"] + " " + res["channel"])
        if res["channel"]:
            observed.add(_acct_norm(res["channel"]))
        h = _handle_from_url(d.get("author_url") if isinstance(d.get("author_url"), str) else "")
        if h:
            observed.add(h)
    else:
        res["evidence_scope"] = "page"
        text = r.get("text") or ""
        res["title"] = _page_title(text)
        hay = _page_text(text)
        low_title = res["title"].lower()
        if any(m in low_title for m in BLOCK_MARKERS) or any(m in hay[:5000] for m in BLOCK_MARKERS):
            res.update(state="unverified", reason="blocked_page")
            return res
        if SOFT404.search(res["title"]):
            res.update(state="unverified", reason="soft404_suspect")
            return res
        observed = _page_accounts(text, res["final_url"])
    _evidence(res, item, hay)
    if _norm(item.get("title") or "") and res["title"]:
        res["title_match"] = "match" if _similar(item["title"], res["title"]) else "conflict"
    want = _acct_norm(item.get("account") or "")
    if want and observed:
        res["account_match"] = "match" if want in observed else "conflict"
    if res["title_match"] == "conflict":
        res["conflict_reasons"].append("title")
    if res["account_match"] == "conflict":
        res["conflict_reasons"].append("account")
    res["conflict"] = bool(res["conflict_reasons"])
    return res


def _line(r):
    """결과 한 줄(JSON). UTF-8 로 쓸 수 없으면 UnicodeError."""
    line = json.dumps(r, ensure_ascii=False)
    line.encode("utf-8")
    return line


def _escaped_result(item, idx, reason):
    url = item.get("url") if isinstance(item, dict) else None
    safe = url.encode("ascii", "backslashreplace").decode("ascii") if isinstance(url, str) else ""
    r = _blank({"url": safe}, idx)
    r.update(state="unverified", reason=reason)
    return r


def check_items(items, fetch=fetch, sleep=time.sleep, out_path="link_check.json", robots=None):
    made = {"n": 0}

    def gap():
        if made["n"]:
            sleep(GAP)
        made["n"] += 1

    if robots is None:
        robots = make_robots(fetch, gap)
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    partial = os.path.splitext(out_path)[0] + ".partial.jsonl"
    results = []
    with io.open(partial, "w", encoding="utf-8", newline="\n") as pf:
        for i, it in enumerate(items):
            try:
                r = check_one(it, fetch, gap, robots)
                r["idx"] = i
                line = _line(r)
            except UnicodeError:  # 결과를 UTF-8 로 쓸 수 없는 문자열 — 주소를 ascii 이스케이프로 남긴다
                r = _escaped_result(it, i, "encode_error")
                line = _line(r)
            except Exception as e:  # 항목 하나의 실패가 전체를 멈추지 않는다
                r = _blank(it, i)
                r.update(state="unverified", reason="error:" + type(e).__name__)
                try:
                    line = _line(r)
                except UnicodeError:
                    r = _escaped_result(it, i, "encode_error")
                    line = _line(r)
            results.append(r)
            pf.write(line + "\n")
            pf.flush()
    n = lambda s: sum(1 for r in results if r["state"] == s)
    ev = lambda s: sum(1 for r in results if r["evidence_status"] == s)
    summary = {"total": len(results), "opened": n("opened"), "unverified": n("unverified"),
               "dead": n("dead"), "evidence_found": ev("found"),
               "conflicts": sum(1 for r in results if r["conflict"]),
               "evidence_status": {s: ev(s) for s in ("found", "not_found", "not_checked", "empty")},
               "truncated": sum(1 for r in results if r["truncated"])}
    line = "링크 %d 중 열림 %d · 막힘 %d · 없음 %d · 근거 원문 확인 %d" % (
        summary["total"], summary["opened"], summary["unverified"], summary["dead"], summary["evidence_found"])
    out = {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": summary, "summary_line": line,
           "results": results,
           "conflicts": [{"url": r["url"], "reasons": r["conflict_reasons"], "title": r["title"],
                          "channel": r["channel"]} for r in results if r["conflict"]]}
    tmp = out_path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)
    return out


def main(argv):
    if len(argv) < 2:
        print("사용: python link_check.py 항목.json [link_check.json]")
        return 2
    with io.open(argv[1], encoding="utf-8-sig") as f:
        data = json.load(f)
    items = data["cards"] if isinstance(data, dict) else data
    out = check_items(items, out_path=argv[2] if len(argv) > 2 else "link_check.json")
    sys.stdout.buffer.write((out["summary_line"] + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
