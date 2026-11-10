# -*- coding: utf-8 -*-
import io
import json

import pytest

from ledger import Ledger, BudgetExceeded


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def test_one_call_one_line_with_cumulative(tmp_path):
    p = str(tmp_path / "비용장부_주제.jsonl")
    lg = Ledger(p, cap=1.0)
    lg.record("gemini", 0.25)
    lg.record("gemini", 0.25, note="두번째")
    rows = read(p)
    assert len(rows) == 2
    assert [r["cumulative"] for r in rows] == [0.25, 0.5]
    assert rows[1]["tool"] == "gemini" and rows[1]["unit_cost"] == 0.25 and "ts" in rows[1]


def test_cap_exceeded_raises_and_not_written(tmp_path):
    p = str(tmp_path / "l.jsonl")
    lg = Ledger(p, cap=0.5)
    lg.record("t", 0.3)
    with pytest.raises(BudgetExceeded):
        lg.record("t", 0.3)
    assert len(read(p)) == 1
    lg.record("t", 0.2)  # exactly at cap is allowed
    assert read(p)[-1]["cumulative"] == 0.5


def test_cumulative_persists_across_instances(tmp_path):
    p = str(tmp_path / "l.jsonl")
    Ledger(p, cap=1.0).record("t", 0.6)
    with pytest.raises(BudgetExceeded):
        Ledger(p, cap=1.0).record("t", 0.5)


def test_float_noise_not_false_exceed(tmp_path):
    p = str(tmp_path / "l.jsonl")
    lg = Ledger(p, cap=0.3)
    lg.record("t", 0.1)
    lg.record("t", 0.1)
    lg.record("t", 0.1)
    assert read(p)[-1]["cumulative"] == 0.3


# ---- 정정1 (반증 1회차 #3·#4) ----
def test_db_is_source_and_jsonl_is_copy(tmp_path):
    p = str(tmp_path / "비용장부_주제.jsonl")
    lg = Ledger(p, cap=1.0)
    lg.record("t", 0.25)
    assert (tmp_path / "비용장부_주제.db").exists()
    assert len(read(p)) == 1
    assert Ledger(p, cap=1.0).cumulative() == __import__("decimal").Decimal("0.25")


@pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf"), "abc", None])
def test_bad_cost_rejected(tmp_path, bad):
    lg = Ledger(str(tmp_path / "l.jsonl"), cap=1.0)
    with pytest.raises(ValueError):
        lg.record("t", bad)
    assert not (tmp_path / "l.jsonl").exists() or read(str(tmp_path / "l.jsonl")) == []


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_bad_cap_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        Ledger(str(tmp_path / "l.jsonl"), cap=bad)


def test_decimal_precision_and_no_refund(tmp_path):
    from decimal import Decimal
    lg = Ledger(str(tmp_path / "l.jsonl"), cap="0.3")
    for _ in range(3):
        lg.record("t", "0.1")
    assert lg.cumulative() == Decimal("0.3")
    assert not hasattr(lg, "refund")
