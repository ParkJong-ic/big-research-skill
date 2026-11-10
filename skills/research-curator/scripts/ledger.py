# -*- coding: utf-8 -*-
"""비용장부 (v1.2). 호출 1건 = 1줄.

- 정본은 sqlite3 한 파일(`<이름>.db`)이다. «상한 검사 + 기록»을 `BEGIN IMMEDIATE` 트랜잭션 하나로 묶어
  여러 프로세스가 동시에 불러도 상한을 넘지 않는다.
- 금액은 **소수 6자리까지만** 허용하고 정수 «백만분의 1 단위»(micro)로 저장·합산한다(부동소수·Decimal 문맥 정밀도 문제 없음).
  6자리를 넘는 값·음수·NaN·무한대는 ValueError. 환불(음수 기록)은 지원하지 않는다.
- 순서는 `INSERT → COMMIT → JSONL 덧붙임`. `<이름>.jsonl` 은 DB 에서 다시 만들 수 있는 **사본**이다(`export_jsonl()`).
  JSONL 쓰기가 실패해도 커밋된 기록은 유효하다(반환 행에 `jsonl_ok: False`) — 사본은 `export_jsonl()` 로 복구한다.
- 옛 jsonl 장부 이관은 `meta.legacy_imported` 표시로 한 번만 한다. 이관 행도 같은 검사를 거치며, 하나라도 실패하면
  이관 전체를 취소하고 예외를 낸다. 옛 스키마 db(정수 단위 열 없음)는 RuntimeError.
"""
import datetime
import io
import json
import os
import sqlite3
from decimal import Decimal, InvalidOperation

MICRO = 1000000
MAX_MICRO = 10 ** 15  # 단일 금액·상한의 한계(sqlite 64비트 정수 안전)


class BudgetExceeded(Exception):
    pass


def _micro(v, what):
    """값 → 정수 micro 단위. 유한한 0 이상, 소수 6자리 이하만."""
    if isinstance(v, bool) or v is None:
        raise ValueError("%s: 숫자가 아님 (%r)" % (what, v))
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError("%s: 숫자가 아님 (%r)" % (what, v))
    if not d.is_finite() or d < 0:
        raise ValueError("%s: 유한한 0 이상이어야 함 (%r)" % (what, v))
    scaled = d * MICRO
    if scaled != scaled.to_integral_value():
        raise ValueError("%s: 소수 6자리까지만 허용 (%r)" % (what, v))
    n = int(scaled)
    if n > MAX_MICRO:
        raise ValueError("%s: 너무 큰 값 (%r)" % (what, v))
    return n


def _dec(micro):
    return Decimal(micro) / MICRO


class Ledger(object):
    def __init__(self, path, cap):
        self.cap_micro = _micro(cap, "상한")
        self.cap = _dec(self.cap_micro)
        base = os.path.splitext(path)[0]
        self.db_path = base + ".db"
        self.path = base + ".jsonl"
        d = os.path.dirname(self.db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=30, isolation_level=None)

    def _init_db(self):
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                cols = [r[1] for r in con.execute("PRAGMA table_info(calls)")]
                if cols and "unit_micro" not in cols:
                    raise RuntimeError("옛 스키마의 장부 db 입니다 (%s) — 이전 판은 이관하지 않습니다." % self.db_path)
                con.execute("CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, "
                            "tool TEXT, unit_micro INTEGER, cum_micro INTEGER, note TEXT)")
                con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
                done = con.execute("SELECT value FROM meta WHERE key='legacy_imported'").fetchone()
                if not done:
                    self._import_legacy(con)
                    con.execute("INSERT INTO meta (key, value) VALUES ('legacy_imported', '1')")
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()

    def _import_legacy(self, con):
        """db 가 비어 있고 옛 jsonl 이 있으면 단가를 옮겨 온다. 한 행이라도 검사에 실패하면 전부 취소."""
        if not os.path.exists(self.path):
            return
        if con.execute("SELECT COUNT(*) FROM calls").fetchone()[0]:
            return
        total = 0
        with io.open(self.path, encoding="utf-8-sig") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                r = json.loads(line)
                u = _micro(r.get("unit_cost"), "옛 장부 %d째 줄 단가" % n)
                total += u
                if total > MAX_MICRO:
                    raise ValueError("옛 장부 누적이 한계를 넘음")
                con.execute("INSERT INTO calls (ts, tool, unit_micro, cum_micro, note) VALUES (?,?,?,?,?)",
                            (r.get("ts", ""), r.get("tool", ""), u, total, r.get("note", "")))

    @staticmethod
    def _sum(con):
        return con.execute("SELECT COALESCE(SUM(unit_micro), 0) FROM calls").fetchone()[0]

    def cumulative(self):
        con = self._connect()
        try:
            return _dec(self._sum(con))
        finally:
            con.close()

    def record(self, tool, unit_cost, note="", now=None):
        """한 줄 기록. 누적이 상한을 넘으면 BudgetExceeded(기록하지 않음 — 호출도 하지 말 것)."""
        cost = _micro(unit_cost, "단가")
        now = now or datetime.datetime.now()
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                cur = self._sum(con)
                new = cur + cost
                if new > self.cap_micro:
                    raise BudgetExceeded("누적 %s + %s > 상한 %s" % (_dec(cur), _dec(cost), self.cap))
                ts = now.strftime("%Y-%m-%d %H:%M:%S")
                con.execute("INSERT INTO calls (ts, tool, unit_micro, cum_micro, note) VALUES (?,?,?,?,?)",
                            (ts, tool, cost, new, note))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
        row = {"ts": ts, "tool": tool, "unit_cost": float(_dec(cost)), "cumulative": float(_dec(new)),
               "note": note}
        try:  # 커밋 뒤에 사본을 덧붙인다 — 실패해도 기록은 유효
            with io.open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            row["jsonl_ok"] = True
        except (OSError, ValueError):
            row["jsonl_ok"] = False
        return row

    def export_jsonl(self):
        """DB 정본에서 jsonl 사본을 처음부터 다시 만든다(임시 파일 → 교체). 만든 행 수를 돌려준다."""
        con = self._connect()
        try:
            rows = con.execute("SELECT ts, tool, unit_micro, cum_micro, note FROM calls ORDER BY id").fetchall()
        finally:
            con.close()
        tmp = self.path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for ts, tool, u, c, note in rows:
                f.write(json.dumps({"ts": ts, "tool": tool, "unit_cost": float(_dec(u)),
                                    "cumulative": float(_dec(c)), "note": note}, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)
        return len(rows)
