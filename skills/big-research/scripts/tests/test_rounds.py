# -*- coding: utf-8 -*-
import datetime
import io
import json
import os

from rounds import save_round, load_seen

NOW = datetime.datetime(2026, 11, 7, 15, 30)


def rows():
    return [
        {"url": "https://youtu.be/AAAAAAAAAAA", "title": "한글 제목 ✓"},
        {"url": "https://www.youtube.com/watch?v=BBBBBBBBBBB"},
        {"url": "https://www.youtube.com/@chan"},  # id None
    ]


def test_writes_utf8_json_with_stamp(tmp_path):
    p = save_round(str(tmp_path), "1차", rows(), now=NOW)
    assert os.path.basename(p) == "1차_20261107-1530.json"
    assert os.path.dirname(p) == str(tmp_path / "research")
    with io.open(p, encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["title"] == "한글 제목 ✓"
    assert data[2]["id"] is None  # kept, not dropped


def test_never_overwrites(tmp_path):
    p1 = save_round(str(tmp_path), "r", rows(), now=NOW)
    p2 = save_round(str(tmp_path), "r", [{"url": "https://youtu.be/CCCCCCCCCCC"}], now=NOW)
    p3 = save_round(str(tmp_path), "r", [], now=NOW)
    assert len({p1, p2, p3}) == 3
    assert p2.endswith("_2.json") and p3.endswith("_3.json")
    with io.open(p1, encoding="utf-8") as f:
        assert len(json.load(f)) == 3


def test_seen_ids_updated_and_deduped(tmp_path):
    save_round(str(tmp_path), "r", rows(), now=NOW)
    save_round(str(tmp_path), "r", rows()[:1], now=NOW)
    seen = load_seen(str(tmp_path))
    assert seen == {"yt:AAAAAAAAAAA", "yt:BBBBBBBBBBB"}
    with io.open(str(tmp_path / "seen_ids.txt"), encoding="utf-8") as f:
        lines = f.read().split("\n")
    assert [x for x in lines if x] == sorted(seen)


def test_explicit_id_wins(tmp_path):
    save_round(str(tmp_path), "r", [{"id": "custom:1", "url": "https://youtu.be/AAAAAAAAAAA"}], now=NOW)
    assert load_seen(str(tmp_path)) == {"custom:1"}


def test_load_seen_missing_file(tmp_path):
    assert load_seen(str(tmp_path)) == set()


# ---- 정정1 (반증 1회차 #5·#16) ----
def test_rebuild_seen_from_round_files(tmp_path):
    import rounds
    save_round(str(tmp_path), "r", rows(), now=NOW)
    os.remove(str(tmp_path / "seen_ids.txt"))
    got = rounds.rebuild_seen(str(tmp_path))
    assert got == {"yt:AAAAAAAAAAA", "yt:BBBBBBBBBBB"}
    assert load_seen(str(tmp_path)) == got


def test_lock_file_removed_after_save(tmp_path):
    save_round(str(tmp_path), "r", rows(), now=NOW)
    assert not (tmp_path / "seen_ids.lock").exists()
    assert not [x for x in os.listdir(str(tmp_path)) if x.endswith(".tmp")]


def test_lock_timeout_raises(tmp_path, monkeypatch):
    import rounds
    monkeypatch.setattr(rounds, "LOCK_WAIT", 0.3)
    (tmp_path / "seen_ids.lock").write_text("x")
    import pytest
    with pytest.raises(TimeoutError):
        save_round(str(tmp_path), "r", rows(), now=NOW)


def test_round_name_validated(tmp_path):
    import pytest
    for bad in ["../x", "a/b", "a\b", "..", "", "a b", "x:y"]:
        with pytest.raises(ValueError):
            save_round(str(tmp_path), bad, rows(), now=NOW)
    save_round(str(tmp_path), "1차-탐색_v1.2", rows(), now=NOW)
