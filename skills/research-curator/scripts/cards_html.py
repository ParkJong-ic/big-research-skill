# -*- coding: utf-8 -*-
"""카드데이터.json → 고르는 화면 HTML (v1.2 · 외부 패키지 0).

사용: python cards_html.py 카드데이터.json 화면.html [제목]
      python cards_html.py --link-check 항목.json link_check.json 화면.html [제목]   (링크 확인 결과를 카드로 합쳐서)
카드 키(없으면 건너뜀): no · title · url · score(추정) · measured_score(실측) · measured(bool) ·
  status(opened/unverified/dead) · evidence_strength(강/중/약) · source(claude = 1차 조사 · 그 밖의 값(gpt·person 등) = 2차 독립 조사) · summary ·
  (link_check 합침) state_reason · evidence_status · evidence_found · account_match · title_match · conflict · check_method
규칙: `no` 는 정수·중복 없음(없으면 1부터 자동) — 아니면 만들기 전에 ValueError. 점수는 유한한 숫자만, `measured` 는 bool 만.
  알 수 없는/빠진 status 는 요약에 «상태 미상 N». 삽입 JSON 의 < > & 는 유니코드 이스케이프(백슬래시 u003c 등)로 바꾼다.
요약 상자 숫자는 JSON 에서 계산한다. 평균은 소수 첫째 자리 «반올림(0.5 올림)», 실측 점수가 있으면 실측 우선.
같은 입력 → 같은 출력(시각 등 넣지 않음).
"""
import html
import io
import json
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP

KNOWN_STATUS = ("opened", "unverified", "dead")


def effective_score(c):
    s = c.get("measured_score")
    return s if s is not None else c.get("score")


def _score(v, what="score"):
    """None 은 None. 숫자(int·float·Decimal, bool 제외)가 유한하면 Decimal, 아니면 ValueError."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        raise ValueError("%s: 숫자가 아님 (%r)" % (what, v))
    d = Decimal(str(v))
    if not d.is_finite():
        raise ValueError("%s: 유한한 숫자가 아님 (%r)" % (what, v))
    return d


def compute_stats(cards):
    scores = []
    for c in cards:
        _score(c.get("score"), "score")
        e = _score(c.get("measured_score"), "measured_score")
        s = e if e is not None else _score(c.get("score"))
        if s is not None:
            scores.append(s)
    if scores:
        avg = str((sum(scores) / len(scores)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    else:
        avg = "-"
    known = sum(1 for c in cards if c.get("status") in KNOWN_STATUS)
    return {
        "total": len(cards),
        "opened": sum(1 for c in cards if c.get("status") == "opened"),
        "unverified": sum(1 for c in cards if c.get("status") == "unverified"),
        "dead": sum(1 for c in cards if c.get("status") == "dead"),
        "unknown": len(cards) - known,
        "strong": sum(1 for c in cards if c.get("evidence_strength") == "강"),
        "measured": sum(1 for c in cards if c.get("measured") or c.get("measured_score") is not None),
        "gpt": sum(1 for c in cards if c.get("source") not in (None, "", "claude")),
        "score_avg": avg,
    }


def prepare_cards(cards):
    """복사본을 만들며 검증한다: no 자동 채움 → 정수·중복 검사, measured 는 bool, 점수는 유한 숫자."""
    out, seen = [], set()
    for i, c in enumerate(cards):
        if not isinstance(c, dict):
            raise ValueError("카드 %d: 객체가 아님" % (i + 1))
        c = dict(c)
        if c.get("no") is None:
            c["no"] = i + 1
        n = c["no"]
        if isinstance(n, bool) or not isinstance(n, int):
            raise ValueError("카드 %d: no 는 정수여야 함 (%r)" % (i + 1, n))
        if n in seen:
            raise ValueError("카드 %d: no 중복 (%r)" % (i + 1, n))
        seen.add(n)
        if c.get("measured") is not None and not isinstance(c["measured"], bool):
            raise ValueError("카드 %d: measured 는 bool 이어야 함 (%r)" % (i + 1, c["measured"]))
        for k in ("score", "measured_score"):
            v = _score(c.get(k), k)
            if isinstance(c.get(k), Decimal):  # JSON 으로 쓸 수 있게 float 로 
                c[k] = float(v)
        out.append(c)
    return out


def cards_from_link_check(items, link_check):
    """항목(원 카드 필드)과 link_check 결과(dict 또는 JSON 경로)를 합친다. 원본은 바꾸지 않는다.

    연결 키는 결과의 `idx`(원 항목 순번) — URL 은 비교하지 않는다. `idx` 가 없는 옛 결과는 순서대로 맞춘다.
    격리된 오류 항목(url 없음·객체가 아님)도 «미확인» 카드로 남는다."""
    if isinstance(link_check, str):
        with io.open(link_check, encoding="utf-8-sig") as f:
            link_check = json.load(f)
    results = link_check["results"]
    if len(results) != len(items):
        raise ValueError("항목 %d건 ≠ 링크 확인 결과 %d건" % (len(items), len(results)))
    by_idx = {}
    for pos, r in enumerate(results):
        k = r.get("idx")
        k = pos if not isinstance(k, int) or isinstance(k, bool) else k
        if k in by_idx:
            raise ValueError("링크 확인 결과 idx 중복: %r" % (k,))
        by_idx[k] = r
    cards = []
    for i, it in enumerate(items):
        if i not in by_idx:
            raise ValueError("%d번째 항목의 링크 확인 결과(idx)가 없음" % (i + 1))
        r = by_idx[i]
        c = dict(it) if isinstance(it, dict) else {"title": "(항목 형식 오류)", "raw": repr(it)[:200]}
        if c.get("no") is None:
            c["no"] = i + 1
        state = r.get("state")
        if state in KNOWN_STATUS:
            c["status"] = state
        else:
            c.pop("status", None)
        c["state_reason"] = r.get("reason", "")
        for k in ("evidence_status", "evidence_found", "evidence_scope", "truncated", "decode_issue",
                  "account_match", "title_match", "conflict", "check_method"):
            if k in r:
                c[k] = r[k]
        cards.append(c)
    return cards


def _json_for_script(obj):
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                    (chr(0x2028), "\\u2028"), (chr(0x2029), "\\u2029")):
        s = s.replace(ch, esc)
    return s


PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fafaf8;--fg:#1c1c1a;--mut:#6b6b66;--card:#fff;--line:#dcdcd4;--acc:#2a5db0;--ok:#2e7d32;--warn:#b26a00;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--fg:#ececE6;--mut:#a0a09a;--card:#212120;--line:#3a3a37;--acc:#7aa7e8;--ok:#7bc47f;--warn:#e0a040;--bad:#f2867f}}
:root[data-theme="dark"]{--bg:#161615;--fg:#ececE6;--mut:#a0a09a;--card:#212120;--line:#3a3a37;--acc:#7aa7e8;--ok:#7bc47f;--warn:#e0a040;--bad:#f2867f}
*{box-sizing:border-box}body{margin:0;padding:16px 16px 96px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,"Malgun Gothic",sans-serif}
h1{font-size:20px;margin:0 0 4px}.how{color:var(--mut);margin:0 0 12px}
.box{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--card);margin-bottom:12px}
.box b{font-variant-numeric:tabular-nums}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.chip{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:4px 12px;cursor:pointer;font:inherit}
.chip[aria-pressed="true"]{background:var(--acc);color:#fff;border-color:var(--acc)}
.card{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--card);margin-bottom:8px}
.card.like{border-color:var(--ok)}.card.dislike{border-color:var(--bad)}
.card h2{font-size:16px;margin:0 0 4px}.meta{color:var(--mut);font-size:13px}
.st-opened{color:var(--ok)}.st-unverified{color:var(--warn)}.st-dead{color:var(--bad)}
.act{margin-top:6px;display:flex;gap:6px}.act button{border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;padding:4px 10px;cursor:pointer;font:inherit}
.bar{position:fixed;left:0;right:0;bottom:0;padding:10px 16px;background:var(--card);border-top:1px solid var(--line);display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.bar code{flex:1;min-width:160px}.bar button{border:1px solid var(--acc);background:var(--acc);color:#fff;border-radius:6px;padding:6px 14px;cursor:pointer;font:inherit}
a{color:var(--acc);word-break:break-all}
</style>
</head>
<body>
<h1>__TITLE__</h1>
<p class="how">고르는 법: 카드의 «마음에 듦» / «별로» 를 누르고, 아래 «복사» 로 번호를 복사해 붙여 주세요. 예: 좋음 1 3 17 · 싫음 18 21</p>
<div class="box" id="summary">총 __TOTAL__건 · 열림 <b>__OPENED__</b> · 막힘 <b>__UNVERIFIED__</b> · 없음 <b>__DEAD__</b> · 상태 미상 <b>__UNKNOWN__</b> · 근거 강 <b>__STRONG__</b> · 실측 <b>__MEASURED__</b> · 2차 조사분 <b>__GPT__</b> · 평균 점수 <b>__AVG__</b> <span class="meta">(실측 우선 · 소수 첫째 자리 반올림)</span></div>
<div class="chips" id="chips">
<button class="chip" data-f="score" aria-pressed="false">점수 4 이상</button>
<button class="chip" data-f="opened" aria-pressed="false">열어 본 것만</button>
<button class="chip" data-f="strong" aria-pressed="false">근거 강</button>
<button class="chip" data-f="measured" aria-pressed="false">실측한 것</button>
<button class="chip" data-f="gpt" aria-pressed="false">2차 조사분</button>
</div>
<div id="list"></div>
<div class="bar"><code id="out">좋음 · 싫음</code><button id="copy" type="button">복사</button><span id="copystat" class="meta" role="status"></span></div>
<script>
const CARDS = __CARDS__;
const picks = {};
const flt = {};
const ST = {opened:"열어 봄", unverified:"막힘(미확인)", dead:"없음(링크 죽음)"};
const EV = {found:"확인", not_found:"없음", not_checked:"안 함", empty:"근거 빈칸"};
function eff(c){return c.measured_score!=null?c.measured_score:c.score}
function pass(c){
  if(flt.score && !(eff(c)>=4)) return false;
  if(flt.opened && c.status!=="opened") return false;
  if(flt.strong && c.evidence_strength!=="강") return false;
  if(flt.measured && !(c.measured||c.measured_score!=null)) return false;
  if(flt.gpt && (!c.source || c.source==="claude")) return false;
  return true;
}
function el(t,cls,txt){const e=document.createElement(t); if(cls) e.className=cls; if(txt!=null) e.textContent=txt; return e}
function render(){
  const list=document.getElementById("list"); list.textContent="";
  CARDS.forEach(function(c,i){
    if(!pass(c)) return;
    const d=el("div","card"+(picks[i]==="like"?" like":picks[i]==="dislike"?" dislike":""));
    d.appendChild(el("h2",null,c.no+". "+(c.title||"(제목 없음)")));
    const m=el("div","meta");
    const s=el("span","st-"+(c.status||""),ST[c.status]||"상태 미상"); m.appendChild(s);
    m.appendChild(document.createTextNode((c.state_reason?"("+c.state_reason+")":"")+" · 점수 "+(eff(c)!=null?eff(c):"-")+(c.measured_score!=null?"(실측)":"(추정)")+" · 근거 "+(c.evidence_strength||"-")+(c.evidence_status?" · 원문대조 "+(EV[c.evidence_status]||c.evidence_status):"")+(c.evidence_scope==="metadata"?" · 메타데이터만 대조":"")+(c.truncated?" · 잘림(뒤쪽 못 봄)":"")+(c.decode_issue?" · 인코딩 의심":"")+(c.conflict?" · 충돌":"")+(c.source&&c.source!=="claude"?" · 2차 조사("+c.source+")":"")));
    d.appendChild(m);
    if(c.summary) d.appendChild(el("div",null,c.summary));
    if(c.url && /^https?:\\/\\//i.test(c.url)){const a=el("a",null,c.url); a.href=c.url; a.target="_blank"; a.rel="noopener noreferrer"; d.appendChild(a)}
    const act=el("div","act");
    [["like","마음에 듦"],["dislike","별로"]].forEach(function(p){
      const b=el("button",null,p[1]); b.type="button";
      b.onclick=function(){picks[i]=picks[i]===p[0]?undefined:p[0]; render()};
      act.appendChild(b)});
    d.appendChild(act); list.appendChild(d);
  });
  const nums=function(k){return CARDS.filter(function(c,i){return picks[i]===k}).map(function(c){return c.no}).sort(function(a,b){return a-b}).join(" ")};
  document.getElementById("out").textContent="좋음 "+nums("like")+" · 싫음 "+nums("dislike");
}
document.getElementById("chips").addEventListener("click",function(e){
  const b=e.target.closest(".chip"); if(!b) return;
  const on=b.getAttribute("aria-pressed")!=="true"; b.setAttribute("aria-pressed",on); flt[b.dataset.f]=on; render();
});
function selectOut(){
  const r=document.createRange(); r.selectNodeContents(document.getElementById("out"));
  const sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
}
document.getElementById("copy").onclick=function(){
  const t=document.getElementById("out").textContent;
  const stat=document.getElementById("copystat");
  function done(){stat.textContent="복사됨"}
  function fail(){selectOut(); stat.textContent="복사 실패 — 선택된 번호 줄을 직접 복사(Ctrl+C)하세요"}
  function legacy(){
    selectOut(); let ok=false;
    try{ok=document.execCommand("copy")}catch(e){ok=false}
    if(ok) done(); else fail();
  }
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(done, legacy);
  } else { legacy(); }
};
render();
</script>
</body>
</html>
"""


def build_html(cards, title="고르는 화면"):
    cards = prepare_cards(cards)
    s = compute_stats(cards)
    vals = {"CARDS": _json_for_script(cards), "TITLE": html.escape(title), "TOTAL": s["total"],
            "OPENED": s["opened"], "UNVERIFIED": s["unverified"], "DEAD": s["dead"], "UNKNOWN": s["unknown"],
            "STRONG": s["strong"],
            "MEASURED": s["measured"], "GPT": s["gpt"], "AVG": s["score_avg"]}
    # 한 번에 치환 — 카드 내용 안의 __TOTAL__ 같은 글자가 다시 바뀌지 않게
    return re.sub(r"__([A-Z]+)__", lambda m: str(vals.get(m.group(1), m.group(0))), PAGE)


def _load(path):
    with io.open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data["cards"] if isinstance(data, dict) else data


def main(argv):
    usage = ("사용: python cards_html.py 카드데이터.json 화면.html [제목]\n"
             "      python cards_html.py --link-check 항목.json link_check.json 화면.html [제목]")
    if len(argv) > 1 and argv[1] == "--link-check":
        if len(argv) < 5:
            print(usage)
            return 2
        src = ("link", argv[2], argv[3])
        out, title = argv[4], (argv[5] if len(argv) > 5 else "고르는 화면")
    else:
        if len(argv) < 3:
            print(usage)
            return 2
        src = ("cards", argv[1], None)
        out, title = argv[2], (argv[3] if len(argv) > 3 else "고르는 화면")
    try:
        # 먼저 끝까지 만든다 — 검증에 실패하면 기존 출력 파일은 건드리지 않는다
        cards = _load(src[1]) if src[0] == "cards" else cards_from_link_check(_load(src[1]), src[2])
        text = build_html(cards, title)
    except ValueError as e:
        sys.stderr.write("오류(출력 파일은 그대로): %s\n" % e)
        return 1
    tmp = out + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
