# research-curator scripts 안내

파이썬 3.8 이상 · 외부 패키지 0(표준 `sqlite3`·`multiprocessing`·`http.server` 는 장부/시험에만) · 네트워크는 `link_check.py` 만.
원칙은 **보존 쪽**: 애매하면 합치지 않고(중복이 남는다), 애매하면 `opened` 로 확정하지 않는다(미확인이 늘어난다).
시험: `scripts/` 에서 `python -m pytest -q`(136건 · `-m perf` 1건). 콘솔 한글이 깨지면 `PYTHONIOENCODING=utf-8`.

## 쓰는 법 (5줄)
1. 새 조사 폴더에서 `sys.path` 에 이 폴더를 넣고 `from rounds import save_round` — 검색·호출 **1회마다** `save_round(폴더, "1차", rows)` (덮어쓰지 않음 · `seen_ids.txt` 자동 갱신 · ID 못 뽑은 행은 `id=None` 으로 남음).
2. 중복은 `norm_id(url)` 로 거른다 (`load_seen(폴더)` 에 있으면 건너뜀). 주소 문자열 비교 금지. `seen_ids.txt` 가 깨지면 `rebuild_seen(폴더)`.
3. 합친 뒤 `python link_check.py 항목.json link_check.json` — 열림/막힘/없음 · 근거 원문 대조 · 충돌 목록. 로그인 필요한 사이트는 열지 않고 `unverified` 로 모은다.
4. 유료 호출은 `Ledger("비용장부_<주제>.jsonl", cap=상한).record("도구", 단가)` 를 호출 직전에 — 상한을 넘기면 `BudgetExceeded`(기록도 호출도 하지 않음).
5. 고르는 화면: `python cards_html.py --link-check 항목.json link_check.json 화면.html "제목"` (링크 확인 결과를 카드로 합쳐 만든다) 또는 `python cards_html.py 카드데이터.json 화면.html "제목"`. 데이터를 바꾸면 화면도 다시 만든다.

## 규칙
### 고유 ID (`norm_id.py` · `norm_id_reason(url)` 는 (ID, 사유) 반환)
- 호스트는 소문자 + **끝 `.` 제거**(`instagram.com.` 도 인스타) 뒤 모든 분기에서 쓴다. 플랫폼은 **호스트 정확 일치**만. `music.youtube.com` 은 유튜브.
- 플랫폼 ID 는 **경로 세그먼트 전체**가 패턴과 일치할 때만: 유튜브 11자(`[A-Za-z0-9_-]`) · X/틱톡 숫자 · 인스타/스레드 `[A-Za-z0-9_-]+`. 뒤에 `Ä`·`!` 등이 붙으면 `None` + 사유(`invalid_id_segment`/`youtube_no_video_id`). 틱톡 단축(`vm.`·`vt.`)은 `None` + `tiktok_short_link_unresolved`(해석 단계 없음).
- 일반 웹: `www.` 만 제거(`m.` 유지) · **경로 대소문자 보존** · 쿼리에서 지우는 키는 **`utm_*`·`fbclid`·`gclid`·`igsh`·`igshid` 5종만**(`ref`·`ref_src`·`si`·`spm`·`mc_*` 는 일반 웹에서 보존 — 문서 버전을 고르는 값일 수 있다) · 남은 쿼리는 **원래 순서·원문 그대로**(재정렬 안 함 — `?a=1&b=2` ≠ `?b=2&a=1`, 반복 키 순서 보존) · 포트는 **스킴 기본값만** 제거(http:80 · https:443; `http://a:443` 은 보존) · 조각은 `#/`·`#!` 로 시작할 때만 · 끝 `/` 제거.
- 한계: 같은 자료를 다른 쿼리 순서·추적 키로 가리키는 주소는 **합쳐지지 않는다**(중복이 남음) — 일반 웹 주소의 중복은 사람이 표본으로 본다.
### 링크 확인 (`link_check.py`)
- 상태 `opened`/`unverified`/`dead` + 사유(reason): `login_host_skipped` · `login_redirect` · `login` · `blocked_page` · `soft404_suspect` · `oembed_invalid` · `robots_denied`(401·403·Disallow) · `robots_unknown`(429·5xx·시간초과 — 본문 요청 안 함; 404 는 허용) · **`redirect_unfollowed_<코드>`**(3xx 를 따라가지 못함: Location 없음·루프·미지원 — 열림으로 확정하지 않음) · `http_<코드>` · `dns_noname`(**`EAI_NONAME` 만** → dead) · `dns_nodata`(주소 데이터 없음 → unverified) · `dns_temp` · `timeout` · `encode_error`(UTF-8 로 쓸 수 없는 문자 — 주소는 ascii 이스케이프로 남김) · `error:<예외 이름>`.
- 리다이렉트: 로그인 사이트(호스트 끝 `.` 제거 뒤 비교)·동의 호스트(`consent.`)로 가는 것은 따라가지 않는다. **308 은 3.8.6 표준 처리기에 없어 직접 처리**(307 과 같게). 각 요청에 간격 1초.
- `check_method` = `page`/`oembed`(유튜브 404 `dead` 는 «oEmbed 기준»). **evidence**: `evidence_status` = `found`/`not_found`/`not_checked`/`empty`(**빈 근거는 열리지 않은 항목에서도 `empty`**) · `evidence_scope` = `page`/`metadata` · `truncated`(1MB 넘어 잘림) · `decode_issue`.
- **충돌**: `account_match`·`title_match` = `match`/`conflict`/`not_compared` (계정은 부분 문자열 허용 없음 · 빈 계정 `@` = `not_compared` · 제목 유사도 0.6 은 참고 신호).
- 결과마다 **`idx`**(원 항목 순번)가 붙는다 — 카드 변환의 연결 키. 항목 하나의 예외·직렬화 실패는 그 항목만 `unverified` 로 남기고 계속한다. 항목마다 `link_check.partial.jsonl` 에 덧붙이고 끝에 `link_check.json`(임시 파일 → 교체).
- 재시도 1회(간격 1초) · 429 는 `Retry-After`(초 또는 HTTP 날짜; **최소 1초·최대 10초**, NaN·무한대는 1초) 뒤 1회 · `TIMEOUT`(10초)은 **요청 한 번 기준**(항목 전체 기한 없음).
- **한계:** 소프트 404(200 으로 «없음» 화면)는 제목 단서로 의심만 · JS 로 그려지는 본문·로그인 뒤 내용은 못 본다 · 유튜브 근거 대조는 제목·채널뿐 · 1MB 넘는 페이지의 뒤쪽은 못 본다 → 사람이 브라우저 등으로 표본 재확인.
### 비용장부 (`ledger.py`)
- 정본은 sqlite `비용장부_<주제>.db`(`BEGIN IMMEDIATE` 한 트랜잭션에서 «상한 검사 + 기록»). 금액은 **소수 6자리까지만**(`1e-28`·`0.0000001` 은 `ValueError`) — **정수 «백만분의 1 단위»로 저장·합산**한다. 음수·NaN·무한대 거부, **환불 미지원**.
- 순서 **`INSERT → COMMIT → JSONL`**. `.jsonl` 은 DB 에서 다시 만들 수 있는 **사본**(`export_jsonl()`); 사본 쓰기가 실패해도 기록은 유효(`jsonl_ok: False`). 옛 `.jsonl` 장부는 `meta.legacy_imported` 표시로 **한 번만** 이관하고, 이관 행도 같은 검사를 거친다(실패하면 이관 전체 취소 + 예외). 
### 회차 저장 (`rounds.py`)
- 회차 JSON 은 **임시 파일에 다 쓴 뒤 `os.link` 로 «없을 때만» 공개**(덮어쓰기 0 · 반쯤 쓴 파일이 보이지 않음). `seen_ids.txt` 갱신과 `rebuild_seen` 의 읽기~교체는 모두 `seen_ids.lock` 안에서 — 못 잡으면(`LOCK_WAIT` 10초) `TimeoutError` 이고 **회차 파일도 만들지 않는다**. 죽은 프로세스가 남긴 `seen_ids.lock`·`*.tmp` 는 사람이 확인하고 지운다.
- 회차 이름은 `[\w가-힣.-]+` 만. 입력 JSON 은 `utf-8-sig`(BOM 허용).
### 고르는 화면 (`cards_html.py`)
- `cards_from_link_check(항목들, link_check결과)` 는 **`idx` 로 연결**(URL 비교 안 함)하고 격리된 오류 항목·객체가 아닌 항목도 «미확인» 카드로 남긴다. `evidence_scope`·`truncated`·`decode_issue`·`check_method` 를 카드에 보존하고 화면 메타 줄에 «메타데이터만 대조/잘림/인코딩 의심» 으로 표시. 알 수 없는/빠진 status 는 요약에 «상태 미상 N».
- `no` 는 정수·중복 없음(없으면 1부터 자동) · `measured` 는 bool · 점수는 유한한 숫자(**Decimal 은 float 로 바꿔 받음**) — 아니면 만들기 전에 `ValueError`. 삽입 JSON 의 `<` `>` `&` 는 유니코드 이스케이프. 선택은 내부 키로, 표시는 `no` 로 분리. 복사는 «복사됨/복사 실패» 를 글자로 보이고 실패하면 번호 줄을 선택.
- **CLI 는 HTML 을 먼저 끝까지 만든 뒤 임시 파일 → 교체** — 검증에 실패(종료코드 1)해도 기존 화면 파일은 그대로다.

## 파일
| 파일 | 역할 |
|---|---|
| `norm_id.py` | 고유 ID (yt·x·tt·ig·th·web) |
| `rounds.py` | 회차 저장 · seen_ids(잠금) · rebuild_seen |
| `link_check.py` | 링크 실재·근거 대조 |
| `ledger.py` | 비용장부(sqlite, micro 단위) + 상한 |
| `cards_html.py` | 링크 결과→카드 · 카드 JSON → 고르는 화면 |
| `tests\` | pytest 136건(`perf` 1건 포함) · `test_contracts.py`(동일성 계약 · 다중 프로세스 **worker 4 · 작업 8 · 40회** 장부 / worker 4 · 작업 4 · 24회 저장 · 로컬 서버 파이프라인) · `test_fix2.py`(경계 반례) | |
| `samples\` | 링크 확인 실측 예 · `cards_sample.html` |

카드 키: `no` `title` `url` `score`(추정) `measured_score`(실측) `measured`(bool) `status` `evidence_strength`(강/중/약) `source`(claude/gpt) `summary` + 합친 필드(`state_reason` `evidence_status` `evidence_scope` `truncated` `decode_issue` `account_match` `title_match` `conflict` `check_method`). 항목 키: `url` `title` `account` `evidence`.

