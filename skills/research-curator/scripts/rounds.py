# -*- coding: utf-8 -*-
"""회차 저장 (v1.2). 호출 1회마다 저장 · 덮어쓰지 않음 · seen_ids.txt 갱신.

- 모든 쓰기(회차 파일 공개 + seen_ids 갱신, rebuild_seen 의 읽기~교체)는 잠금 파일(`seen_ids.lock`,
  `os.open(O_CREAT|O_EXCL)`, 최대 LOCK_WAIT 초 대기) 안에서 한다. 시간 안에 못 잡으면 TimeoutError — 이때 회차 파일은
  만들지 않는다(남은 잠금 파일은 사람이 확인하고 지운다).
- 회차 JSON 은 임시 파일(`*.tmp`)에 다 쓴 뒤 `os.link` 로 최종 이름에 «없을 때만» 공개한다(덮어쓰지 않음 ·
  읽는 쪽은 반쯤 쓴 파일을 보지 못한다). 같은 이름이 있으면 _2, _3 … 을 붙인다.
- `rebuild_seen(folder)` 는 잠금 안에서 research 폴더의 *.json 의 id 로 seen_ids.txt 를 다시 만든다.
- 회차 이름은 `[\\w가-힣.-]+` 만 허용한다(아니면 ValueError).
"""
import datetime
import glob
import io
import json
import os
import re
import time

from norm_id import norm_id

LOCK_WAIT = 10.0
_NAME = re.compile(r"[\w가-힣.-]+\Z")


def _publish_new(tmp, path):
    """tmp(완성된 파일)를 path 에 «없을 때만» 공개한다. 이미 있으면 FileExistsError. tmp 는 지운다."""
    try:
        os.link(tmp, path)
    except FileExistsError:
        raise
    except OSError:  # 하드링크를 못 쓰는 파일시스템 — 존재 검사 뒤 rename (잠금 안이라 경쟁 없음)
        if os.path.exists(path):
            raise FileExistsError(path)
        os.rename(tmp, path)
        return
    os.remove(tmp)


class _SeenLock(object):
    def __init__(self, folder):
        self.path = os.path.join(folder, "seen_ids.lock")

    def __enter__(self):
        end = time.time() + LOCK_WAIT
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() >= end:
                    raise TimeoutError("seen_ids.lock 을 %s초 안에 잡지 못함: %s" % (LOCK_WAIT, self.path))
                time.sleep(0.02)

    def __exit__(self, *a):
        try:
            os.remove(self.path)
        except OSError:
            pass


def _write_seen(folder, seen):
    tmp = os.path.join(folder, "seen_ids.%d.tmp" % os.getpid())
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(i + "\n" for i in sorted(seen)))
    os.replace(tmp, os.path.join(folder, "seen_ids.txt"))


def save_round(folder, name, rows, now=None):
    """rows 를 folder/research/<name>_<YYYYMMDD-HHMM>.json 으로 저장하고 경로를 돌려준다.

    같은 이름이 있으면 _2, _3 ... 을 붙인다. id 가 없는 행은 url 로 norm_id 를 채우고,
    ID 를 못 뽑으면 id=None 으로 남긴다(버리지 않는다). seen_ids.txt 에 ID 를 합친다.
    """
    if not isinstance(name, str) or not _NAME.match(name) or not name.strip("."):
        raise ValueError("회차 이름은 [\\w가-힣.-]+ 만 허용: %r" % (name,))
    now = now or datetime.datetime.now()
    rdir = os.path.join(folder, "research")
    out = []
    for r in rows:
        r = dict(r)
        if r.get("id") is None:
            r["id"] = norm_id(r["url"]) if r.get("url") else None
        out.append(r)
    text = json.dumps(out, ensure_ascii=False, indent=2)
    base = "%s_%s" % (name, now.strftime("%Y%m%d-%H%M"))
    os.makedirs(folder, exist_ok=True)
    with _SeenLock(folder):  # 잠금을 못 잡으면 아무것도 쓰지 않는다
        os.makedirs(rdir, exist_ok=True)
        tmp = os.path.join(rdir, "%s.%d.tmp" % (base, os.getpid()))
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n = 1
        while True:
            fn = base + (".json" if n == 1 else "_%d.json" % n)
            path = os.path.join(rdir, fn)
            try:
                _publish_new(tmp, path)
                break
            except FileExistsError:
                n += 1
        seen = load_seen(folder) | {r["id"] for r in out if r["id"]}
        _write_seen(folder, seen)
    return path


def load_seen(folder):
    p = os.path.join(folder, "seen_ids.txt")
    if not os.path.exists(p):
        return set()
    with io.open(p, encoding="utf-8-sig") as f:
        return {x.strip() for x in f if x.strip()}


def rebuild_seen(folder):
    """research 폴더의 *.json 의 id 로 seen_ids.txt 를 처음부터 다시 만든다(읽기~교체 모두 잠금 안). 만든 집합을 돌려준다."""
    os.makedirs(folder, exist_ok=True)
    with _SeenLock(folder):
        seen = set()
        for p in sorted(glob.glob(os.path.join(folder, "research", "*.json"))):
            with io.open(p, encoding="utf-8-sig") as f:
                for r in json.load(f):
                    if isinstance(r, dict) and r.get("id"):
                        seen.add(r["id"])
        _write_seen(folder, seen)
    return seen
