#!/usr/bin/env python3
"""通用失败分诊(吸收 runtime/infra/airflow-log.mjs)。

从 Airflow(同账号)定位因子 dag 失败的根因 task + 真实信号。
输出结构化 {dagState, rootTask, locus, mapped, exitCode, signals, causeText, rawTail},
由 check.py 按 (locus, 信号) 分层。
任何 Airflow 异常都吞掉返回 ok=False(调用方继续用平台 state 判断,不依赖这个)。
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

DEFAULT_HOST = "airflow.dev.xyz.abc"
CREDS_FILE = Path.home() / "featuretool_creds.json"
DAG_ID = "GenerateXYs"

COMPILE_LOCUS = ["build_model", "generate_modelcpp", "generate_abstract_model", "generate_build_model_command"]
RUNTIME_LOCUS = ["generate_xy"]

COMPILE_ERROR_RE = re.compile(
    r"(?:INFO - )?([^:\s]+\.(?:h|hpp|cc|c|cpp)):(\d+):(?:\d+:)?\s*"
    r"(error|fatal error|no matching function for call to|undefined reference|cannot find|no member):?([^\n]+)"
)

EXIT_CODE_RE = re.compile(r"(?:Command exited with|returned a non-zero exit code|return code)\s*(\d{2,3})")

CRASH_PATTERNS = [
    re.compile(r"Aborted\s*\(core dumped\)"),
    re.compile(r"Segmentation fault", re.I),
    re.compile(r"SIGABRT"), re.compile(r"SIGSEGV"), re.compile(r"SIGFPE"), re.compile(r"SIGKILL"),
    re.compile(r"terminate called after throwing an instance of", re.I),
    re.compile(r"terminate called after throwing"),
    re.compile(r"Assertion .* failed", re.I),
    re.compile(r"Assertion failed:", re.I),
    re.compile(r"double free or corruption", re.I),
    re.compile(r"malloc\s*\)", re.I),
    re.compile(r"stack smashing detected", re.I),
]

EXIT_CODE_MEANING = {
    134: "SIGABRT (abort/assert/throw)",
    139: "SIGSEGV (segfault)",
    137: "SIGKILL (常为 OOM-killer)",
    136: "SIGFPE (整数除零)",
    138: "SIGBUS",
}


def _read_creds(creds_file=CREDS_FILE):
    if not creds_file.exists():
        return None
    try:
        d = json.loads(creds_file.read_text(encoding="utf-8"))
        return d if (d.get("username") and d.get("password")) else None
    except Exception:
        return None


def _curl_get(host: str, basic_auth: str, ep: str) -> str:
    r = subprocess.run(
        ["curl", "-s", "-k", "--max-time", "30", "-H", f"Authorization: Basic {basic_auth}",
         f"https://{host}{ep}"],
        capture_output=True, text=True, timeout=35,
    )
    return r.stdout or ""


def _locus_of(task_id: str) -> str:
    if any(t in task_id for t in COMPILE_LOCUS):
        return "compile"
    if any(t in task_id for t in RUNTIME_LOCUS):
        return "runtime"
    return "setup"


def _extract_compile_errors(log_text: str) -> list[str]:
    hits = []
    for m in COMPILE_ERROR_RE.finditer(log_text):
        basename = m.group(1).split("/")[-1]
        hits.append(f"{basename}:{m.group(2)}: {m.group(3)}: {(m.group(4) or '').strip()}")
    return list(dict.fromkeys(hits))


def _extract_exit_codes(log_text: str) -> list[int]:
    codes = [int(m.group(1)) for m in EXIT_CODE_RE.finditer(log_text)]
    return list(dict.fromkeys(codes))


def _extract_crash_signals(log_text: str) -> list[str]:
    hits = []
    for re_ in CRASH_PATTERNS:
        m = re_.search(log_text)
        if m:
            hits.append(m.group(0).strip())
    what = re.search(r"what\(\):\s*([^\n]+)", log_text)
    if what:
        hits.append(f"C++ exception: {what.group(1).strip()}")
    thrown = re.search(r"terminate called after throwing an instance of\s*['\"]?(\S+)", log_text)
    if thrown:
        hits.append(f"uncaught exception: {thrown.group(1).replace(chr(39), '').replace(chr(34), '')}")
    return list(dict.fromkeys(hits))


def _extract_py_traceback(log_text: str) -> list[str]:
    m = re.search(r"Traceback \(most recent call last\):[\s\S]{0,1200}?\n([A-Za-z_.]*Error|Exception):[^\n]*", log_text)
    return [m.group(0).split("\n")[-3].join(" | ")] if m else []


_RAW_TAIL_SKIP = re.compile(
    r"^Dependencies all met|^Starting attempt|^Executing <|^Started process|^Running:|"
    r"^Running command|^\[.airflow|^Exporting env vars|^Tmp dir|^Marking task as|"
    r"^Task exited|^0 downstream"
)


def _extract_raw_tail(log_text: str, max_lines: int = 30) -> str:
    keep = []
    for raw in log_text.split("\n"):
        line = re.sub(r"^\[?\d{4}-\d\d-\d\dT[\d:+-]+\]?\s*\{[^}]+\}\s*(INFO|DEBUG)\s*-\s*", "", raw)
        if not line.strip():
            continue
        if _RAW_TAIL_SKIP.match(line):
            continue
        keep.append(line)
        if len(keep) > max_lines * 3:
            break
    return "\n".join(keep[-max_lines:])


def triage_failure(factor_name: str, username: str | None = None, host: str = DEFAULT_HOST, max_map_probe: int = 3) -> dict:
    """通用失败分诊。失败/无 dag_run 时 ok=False。"""
    creds = _read_creds()
    user = username or (creds.get("username") if creds else None)
    if not user or not creds:
        return _fail("missing_credentials")
    basic = base64.b64encode(f"{creds['username']}:{creds['password']}".encode()).decode()

    # 1. 最新 dag run
    try:
        body = _curl_get(host, basic, f"/api/v1/dags/{DAG_ID}/dagRuns?limit=100&order_by=-start_date")
        runs = [r for r in (json.loads(body).get("dag_runs") or [])
                if r.get("dag_run_id", "").startswith(f"{user}-{factor_name}-")]
    except Exception as e:
        return _fail("dagruns_fetch_failed", str(e))
    if not runs:
        return _fail("no_dag_run")
    latest = runs[0]

    if latest.get("state") != "failed":
        return {"ok": True, "triaged": False, "dagRunId": latest.get("dag_run_id"), "dagState": latest.get("state"), "rootTask": None}

    # 2. 全部 task instance
    try:
        body = _curl_get(host, basic,
                         f"/api/v1/dags/{DAG_ID}/dagRuns/{latest['dag_run_id']}/taskInstances")
        tis = json.loads(body).get("task_instances") or []
    except Exception as e:
        return _fail("taskinstances_fetch_failed", str(e), latest.get("dag_run_id"))

    # 3. 根因 task = 有 failed 实例的 task(排除 upstream_failed 连坐)
    failed_by_id: dict[str, list] = {}
    task_state_summary: dict[str, dict[str, int]] = {}
    for t in tis:
        s = task_state_summary.setdefault(t.get("task_id"), {})
        s[t.get("state")] = s.get(t.get("state"), 0) + 1
        if t.get("state") == "failed":
            failed_by_id.setdefault(t.get("task_id"), []).append(t)
    failed_task_ids = list(failed_by_id.keys())

    # 4. 选根因 task:compile 优先(编译错连坐),次 runtime,次其它
    def pick(locus: str):
        return next((i for i in failed_task_ids if _locus_of(i) == locus), None)
    root_task_id = pick("compile") or pick("runtime") or (failed_task_ids[0] if failed_task_ids else None)
    root_instances = failed_by_id.get(root_task_id, [])
    mapped = len(root_instances) > 1 or any(t.get("map_index", -1) >= 0 for t in root_instances)

    # 5. 取根因 task 日志(mapped 按 map_index 探测)
    probes = root_instances[:max_map_probe] if mapped else root_instances[:1]
    log_blob = ""
    for inst in probes:
        max_try = max(inst.get("try_number") or 1, 2)
        mi_vals = ([inst["map_index"]] if inst.get("map_index") is not None and inst.get("map_index", -1) >= 0
                   else (list(range(max_map_probe)) if mapped else [None]))
        got = False
        for mi_val in mi_vals:
            for ty in range(1, max_try + 1):
                if got:
                    break
                mi = f"?map_index={mi_val}" if mi_val is not None else ""
                try:
                    log = _curl_get(host, basic,
                                    f"/api/v1/dags/{DAG_ID}/dagRuns/{latest['dag_run_id']}"
                                    f"/taskInstances/{root_task_id}/logs/{ty}{mi}")
                    if log and len(log) > 10 and '"status": 404' not in log:
                        log_blob += "\n" + log
                        got = True
                except Exception:
                    pass
            if got:
                break

    # 6. 通用信号抽取
    compile_errs = _extract_compile_errors(log_blob)
    exit_codes = _extract_exit_codes(log_blob)
    crashes = _extract_crash_signals(log_blob)
    tracebacks = _extract_py_traceback(log_blob)
    raw_tail = _extract_raw_tail(log_blob)

    exit_code = exit_codes[0] if exit_codes else None
    signals = {
        "compile": compile_errs,
        "crash": crashes,
        "traceback": tracebacks,
        "exit_codes": [f"{c}={EXIT_CODE_MEANING.get(c, 'non-zero')}" for c in exit_codes],
    }
    cause_parts = (compile_errs + crashes + tracebacks +
                   [f"exit {c} ({EXIT_CODE_MEANING.get(c, 'non-zero')})" for c in exit_codes])
    cause_text = "\n".join(list(dict.fromkeys(cause_parts))[:12])

    return {
        "ok": True, "triaged": True,
        "dagRunId": latest.get("dag_run_id"), "dagState": "failed",
        "rootTask": root_task_id, "locus": _locus_of(root_task_id),
        "mapped": mapped, "nRootInstances": len(root_instances),
        "taskStateSummary": task_state_summary,
        "exitCode": exit_code, "signals": signals, "causeText": cause_text, "rawTail": raw_tail,
    }


def _fail(reason: str, detail: str | None = None, dag_run_id: str | None = None) -> dict:
    out = {"ok": False, "triaged": False, "_reason": reason, "dagRunId": dag_run_id}
    if detail:
        out["_detail"] = detail
    return out
