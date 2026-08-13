#!/usr/bin/env python3
"""subprocess 调 python 脚本(吸收 runtime/infra/run-py.mjs)。

换 python 后,MCP server 本身就是 quant-venv python 跑的,sys.executable 即 venv python。
shell=False + argv 数组:规避 shell 引号 bug(如 features="ClassA<>" 被 shell 当重定向)。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

# quant-venv python(有 sqlite_vec/pandas/sentence_transformers)。fallback 当前解释器。
VENV_PY = "/home/lgao/quant-venv/bin/python"
PY = VENV_PY if Path(VENV_PY).exists() else sys.executable


def run_py(script_path: str, args: list[str] | None = None, timeout_sec: int = 600, cwd: str | None = None) -> dict:
    """spawn python 脚本,返回 {exit_code, stdout, stderr, duration_ms, timed_out}。"""
    start = time.time()
    cmd = [PY, script_path, *(args or [])]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_sec, cwd=cwd,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "duration_ms": int((time.time() - start) * 1000),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": None,
            "stdout": "",
            "stderr": f"timeout after {timeout_sec}s",
            "duration_ms": timeout_sec * 1000,
            "timed_out": True,
        }
    except FileNotFoundError as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "duration_ms": int((time.time() - start) * 1000),
            "timed_out": False,
        }


def parse_json_output(stdout: str) -> dict | None:
    """python --json 输出末尾 JSON,可能混入日志,容错提取最大的 {...}。"""
    if not stdout or not stdout.strip():
        return None
    s = stdout.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"(\{[\s\S]*\})", s)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                return None
        return None
