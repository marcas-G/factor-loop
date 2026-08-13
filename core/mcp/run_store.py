#!/usr/bin/env python3
"""run state 管理(吸收 runtime/mcp/lib/run-store.mjs)。

JSON 文件 <runsRoot>/<run_id>/state.json + 原子写(tmp+rename)+ 按 run_id 串行写链。
"""
from __future__ import annotations

import json
import os
import random
import string
import threading
from datetime import datetime
from pathlib import Path

_runs_root = Path(os.environ.get("QUANT_MCP_RUNS_ROOT") or (Path.home() / ".quant-runs"))

# 按 run_id 串行写锁(每个 run_id 一把,防并发 run_save 交叉写坏 state)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def set_runs_root(p) -> None:
    global _runs_root
    _runs_root = Path(p)


def get_runs_root() -> Path:
    return _runs_root


def _state_path(run_id: str) -> Path:
    return _runs_root / run_id / "state.json"


def _lock_for(run_id: str) -> threading.Lock:
    with _locks_guard:
        if run_id not in _locks:
            _locks[run_id] = threading.Lock()
        return _locks[run_id]


def _today_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _random_suffix() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


def _write_atomic(path: Path, obj) -> None:
    tmp = path.with_suffix(".json.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.rename(path)


def run_init(idea=None, factors=None, parent_session=None) -> dict:
    run_id = f"{_today_stamp()}-{_random_suffix()}"
    run_dir = _runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1, "run_id": run_id, "run_dir": str(run_dir),
        "status": "running", "idea": idea, "idea_id": None,
        "parent_session": parent_session,
        "started_at": datetime.now().isoformat(),
        "factors": [{
            "name": f.get("name"), "formula": f.get("formula"), "hypothesis": f.get("hypothesis"),
            "categories": f.get("categories") or [], "coordinates": f.get("coordinates"),
            "factor_file": None, "status": "pending", "failure_layer": None,
            "retry_trace": [], "evidence": None, "verdict": None, "persisted": None,
        } for f in (factors or [])],
        "finished_at": None,
    }
    _write_atomic(_state_path(run_id), state)
    return {"run_id": run_id}


def run_load(run_id: str) -> dict:
    p = _state_path(run_id)
    if not p.exists():
        raise FileNotFoundError(f"run_id 不存在: {run_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def _set_by_path(obj, dotted_path: str, value) -> None:
    parts = dotted_path.split(".")
    cur = obj
    for i in range(len(parts) - 1):
        k = parts[i]
        next_key = parts[i + 1]
        is_next_numeric = next_key.isdigit()
        if cur.get(k) is None:
            cur[k] = [] if is_next_numeric else {}
        if not isinstance(cur[k], (dict, list)):
            raise TypeError(f"路径 {'.'.join(parts[:i + 1])} 已是 {type(cur[k]).__name__},不能下钻")
        cur = cur[k]
    cur[parts[-1]] = value


def _do_run_save(run_id: str, patch: dict) -> dict:
    state = run_load(run_id)
    for key, value in patch.items():
        if "." in key:
            parts = key.split(".")
            if len(parts) == 2 and parts[0] == "factors" and parts[1].isdigit():
                return {"ok": False, "error": f'禁止整体覆盖 factor 对象: "{key}"。用点分 field(如 "factors.{parts[1]}.status")'}
            _set_by_path(state, key, value)
        else:
            if key == "factors":
                return {"ok": False, "error": '禁止整体覆盖 factors 数组: "factors"。用点分路径(如 "factors.0.status")'}
            state[key] = value
    _write_atomic(_state_path(run_id), state)
    return {"ok": True}


def run_save(run_id: str, patch: dict) -> dict:
    with _lock_for(run_id):
        return _do_run_save(run_id, patch)


def run_apply(run_id: str, fn) -> dict:
    with _lock_for(run_id):
        state = run_load(run_id)
        fn(state)
        _write_atomic(_state_path(run_id), state)
        return {"ok": True}


def run_list() -> list[dict]:
    if not _runs_root.exists():
        return []
    runs = []
    for ent in sorted(_runs_root.iterdir(), reverse=True):
        if not ent.is_dir():
            continue
        p = ent / "state.json"
        if not p.exists():
            continue
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
            runs.append({"run_id": s.get("run_id"), "idea": s.get("idea"), "status": s.get("status"),
                         "started_at": s.get("started_at"), "finished_at": s.get("finished_at")})
        except Exception:
            pass
    runs.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return runs
