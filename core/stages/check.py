#!/usr/bin/env python3
"""check(吸收 runtime/stages/check.mjs)。

程序化路径:调 core/platform/factor_check.py run。
评估分层(failureLayer)+ Airflow 通用失败分诊 + daily_ic 抓取。

分层原则:按根因 task 的 locus + 信号分层,不凭 dag_state 猜:
  compile locus + 编译错 → compile_failed(因子代码,重写)
  runtime locus + 崩溃(134/139/abort/assert)→ factor_runtime_crash(因子代码,重写)
  runtime locus + exit≠0 无崩溃 → factor_runtime_error(因子代码,重写)
  setup locus failed → platform_transient(infra,重 check 不重写)
  dag success + daily_ic 空/过小 → check_output_missing / check_output_too_small(因子质量,重写)
  dag running / 无分诊 / factor_check 超时 → platform_transient(真 transient,有界重 check)
"""
from __future__ import annotations

import re
from pathlib import Path

from core.db import db
from core.infra.airflow_log import triage_failure
from core.infra.run_py import run_py
from core.metrics import extract_metrics_from_check_output, max_zero_ratio_from_screening

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACTOR_CHECK_PY = str(_PROJECT_ROOT / "core" / "platform" / "factor_check.py")


def feature_stem_from_db(xname: str) -> str | None:
    """从 factors 表 file_path 兜底 featureKey(平台用 .h stem 注册)。"""
    try:
        with db.get_conn() as conn:
            row = conn.execute("SELECT file_path FROM factors WHERE xname = ?", (xname,)).fetchone()
            if row and row["file_path"]:
                return Path(row["file_path"]).stem
    except Exception:
        pass
    return None


def find_daily_ic(check_output: str | Path, feature_key: str) -> str:
    """老产物结构:<checkOutput>/<featureKey>/dailyX/<featureKey>_deep/daily_ic_results.txt。"""
    return str(Path(check_output) / feature_key / "dailyX" / f"{feature_key}_deep" / "daily_ic_results.txt")


def find_csv_ic_summary(check_output: str | Path, feature_key: str) -> str:
    """default_test 产物:<checkOutput>/<featureKey>/csv_ic/csv_ic_summary.csv。"""
    return str(Path(check_output) / feature_key / "csv_ic" / "csv_ic_summary.csv")


def list_dir(dir_path: str | Path, max_depth: int = 3, max_entries: int = 30) -> str:
    """递归列目录(诊断用,截断)。"""
    lines = []
    count = 0

    def walk(d: Path, depth: int = 0):
        nonlocal count
        if depth > max_depth or count >= max_entries:
            return
        try:
            entries = sorted(d.iterdir())
        except OSError:
            return
        for e in entries:
            if count >= max_entries:
                lines.append("... (more)")
                return
            prefix = "  " * depth
            lines.append(f"{prefix}{'/' if e.is_dir() else ''}{e.name}")
            count += 1
            if e.is_dir():
                walk(e, depth + 1)

    walk(Path(dir_path))
    return "\n".join(lines)


# ---------- 诊断构建 ----------

def _build_compile_diagnosis(cause_text):
    return {"diagnosis": {
        "nature": "编译失败(因子代码):build_model 阶段 g++ 编译因子 .h 失败",
        "root_cause": cause_text or "见 stderr_tail / cause_text 的 file:line: error",
        "fix_hint": "按 cause_text 每条 file:line: error 精确改对应行;常见:std::pair 无 clear()、std::vector 无 pop_front()(用 erase(begin()))、缺 #include",
    }}


def _build_runtime_crash_diagnosis(cause_text, exit_code):
    return {"diagnosis": {
        "nature": f"运行期崩溃(因子代码):generate_xy 执行因子时 {f'exit {exit_code}(SIGABRT/SIGSEGV)' if exit_code else '崩溃'} core dump。编译通过但跑数据时崩 → 未定义行为",
        "root_cause_candidates": [
            "容器(vector/deque/array)未按 _numFeeds / 档位数 resize 即用 operator[] 访问 → 越界(最常见!)",
            "未初始化的成员(指针/迭代器/计数器)首帧使用",
            "整数除零 / NaN 传播到后续计算(加 std::isfinite 守卫 + eps 保底)",
            "模板参数越界(MaxLevels/窗口为0或超范围)→ 检查 static_assert",
            "feed().bidSize/askSize 在档位不足时越界 → 用 availableLevels 约束",
        ],
        "signal": cause_text or "Aborted (core dumped) / Segmentation fault",
        "fix_hint": "逐个核查 per-feed 容器是否在 initialize/onStarted resize 到 _numFeeds;onEndBook 里所有 operator[] 下标先校验 <size();冷启动未就绪时输出 0 不访问空容器",
    }}


def _build_runtime_error_diagnosis(cause_text, exit_code):
    return {"diagnosis": {
        "nature": f"运行期错误(因子代码):generate_xy exit={exit_code if exit_code is not None else '?'} 非崩溃类失败",
        "root_cause": cause_text or "见 raw_tail / cause_text",
        "fix_hint": "读 raw_tail 定位具体错误行;常见数值/边界问题",
    }}


def _build_too_small_diagnosis(zero_ratio=None):
    zr_str = (f"(实测 zero_ratio={zero_ratio:.3f},非零率仅 {((1 - zero_ratio) * 100):.1f}%)"
              if zero_ratio is not None else "")
    return {"diagnosis": {
        "nature": f"结构性失败(因子质量):DAG 成功但 IC 产物空 → 因子值近全0/NaN/非零率过低{zr_str},平台跳过 IC 计算",
        "root_cause_candidates": [
            "硬门控(如 volHigh ? x : 0)把因子压成近全0 → 降门控分位或软化成 sigmoid 权重",
            "冷启动期全0(需积累 N 样本才输出)→ 缩短冷启动阈值或冷启动期输出 baseline",
            "底事件罕见导致信号稀疏(触发率<5%)→ 放宽触发阈值/降分位/换更活跃品种",
            "log/除法产生 NaN/极值 → std::log(std::max(v,1e-20)) 保底 + 最终 isfinite+clamp",
        ],
        "fix_hint": "定位 onEndBook 里把结果归0的门控/冷启动分支,放宽或软化;确认输出在正常行情下非零率>20%",
    }}


def _build_check_failed_diagnosis():
    return {"diagnosis": {
        "nature": "factor_check.py 执行异常(pipeline python 侧)",
        "root_cause_candidates": [
            "查 stderr_tail/stdout_tail 的 traceback 定位",
            "若 traceback 指向因子值解析(如非有限值/类型不符)→ 因子输出格式问题",
            "若指向平台/下载/cookie → 平台侧,标 platform_transient 重试",
        ],
        "fix_hint": "读 traceback;因子侧改代码,平台侧重 check",
    }}


def decide_failure_layer(tg: dict) -> dict:
    """纯函数:triage 结果 → {layer, diagnosis, summary}。locus + 信号决定分层。"""
    has_crash = bool((tg.get("signals") or {}).get("crash")) or tg.get("exitCode") in [134, 139, 136, 138]
    signals = tg.get("signals") or {}
    has_any_signal = bool(signals.get("crash") or signals.get("compile") or signals.get("traceback") or tg.get("exitCode"))
    if tg.get("locus") == "compile":
        return {"layer": "compile_failed", "diagnosis": _build_compile_diagnosis(tg.get("causeText"))["diagnosis"],
                "summary": f"compile_failed (root={tg.get('rootTask')})"}
    if tg.get("locus") == "runtime" and has_crash:
        return {"layer": "factor_runtime_crash",
                "diagnosis": _build_runtime_crash_diagnosis(tg.get("causeText"), tg.get("exitCode"))["diagnosis"],
                "summary": f"factor_runtime_crash (root={tg.get('rootTask')}, exit={tg.get('exitCode') if tg.get('exitCode') is not None else '?'})"}
    if tg.get("locus") == "runtime":
        return {"layer": "factor_runtime_error",
                "diagnosis": _build_runtime_error_diagnosis(tg.get("causeText"), tg.get("exitCode"))["diagnosis"],
                "summary": f"factor_runtime_error (root={tg.get('rootTask')})"}
    if not has_any_signal:
        return {"layer": "check_failed", "diagnosis": None,
                "summary": f"check_failed (root={tg.get('rootTask')}, locus={tg.get('locus')}, 分诊信号缺失, 真因未明)"}
    return {"layer": "platform_transient", "diagnosis": None,
            "summary": f"platform_transient (root={tg.get('rootTask')}, locus={tg.get('locus')})"}


def _classify_failed(check_output, daily_ic_path, daily_ic_exists, daily_ic_size, result, triage_evidence, tg) -> dict:
    layer_info = decide_failure_layer(tg)
    layer = layer_info["layer"]
    if layer == "platform_transient":
        return _transient(check_output, daily_ic_path, daily_ic_exists, daily_ic_size, result,
                          f"根因任务 {tg.get('rootTask')} (locus={tg.get('locus')}) failed", triage_evidence)
    return {
        "ok": False, "failureLayer": layer, "checkOutput": check_output,
        "dailyIcPath": daily_ic_path if daily_ic_exists else None, "dailyIcSize": daily_ic_size,
        "summary": f"[检查失败] {layer_info['summary']}",
        "evidence": {
            "reason": layer, "dag_state": "failed",
            "stdout_tail": result["stdout"][-500:],
            **(triage_evidence or {}),
            **({"diagnosis": layer_info["diagnosis"]} if layer_info.get("diagnosis") else {}),
        },
    }


def _transient(check_output, daily_ic_path, daily_ic_exists, daily_ic_size, result, note, triage_evidence=None) -> dict:
    return {
        "ok": False, "failureLayer": "platform_transient", "checkOutput": check_output,
        "dailyIcPath": daily_ic_path if daily_ic_exists else None, "dailyIcSize": daily_ic_size,
        "summary": f"[检查失败] platform_transient — {note}",
        "evidence": {
            "reason": "platform_transient",
            "stdout_tail": result["stdout"][-500:],
            "stderr_tail": result["stderr"][-500:],
            "note": note,
            **(triage_evidence or {}),
        },
    }


def _success(check_output, daily_ic_path, daily_ic_size, result, feature_key) -> dict:
    ic_content = Path(daily_ic_path).read_text(encoding="utf-8", errors="replace")
    ic_preview = "\n".join(ic_content.split("\n")[:30])
    eval_metrics = extract_metrics_from_check_output(check_output, feature_key)
    return {
        "ok": True, "failureLayer": "check_done", "checkOutput": check_output,
        "dailyIcPath": daily_ic_path, "dailyIcSize": daily_ic_size,
        "summary": f"[检查完成] IC 文件 {daily_ic_size}B(详见 evidence.daily_ic_preview)",
        "evidence": {
            "reason": "check_done",
            "daily_ic_preview": ic_preview,
            "eval_metrics": eval_metrics,
            **({"platform": "default_test", "eval_metrics_coverage": ["ic_only"]} if eval_metrics.get("csv_ic") else {}),
            "stdout_tail": result["stdout"][-500:],
        },
    }


def _maybe_diagnosis(result) -> dict:
    tail = (result["stderr"] or "") + "\n" + (result["stdout"] or "")
    if re.search(r"Traceback|Error|Exception", tail, re.I):
        return _build_check_failed_diagnosis()
    return {}


def check_factor_programmatic(factor: dict, submit_result: dict, check_output: str) -> dict:
    """程序化路径:调 factor_check.py run --skip-submit 一次完成 wait/download/analyze。"""
    # featureKey = .h stem(平台用 stem 注册,class 名可能 mismatch)
    class_fallback = re.sub(r"<.*>$", "", (submit_result.get("features") or factor.get("name"))).strip()
    stem_from_db = None if factor.get("factor_file") else feature_stem_from_db(factor.get("name"))
    if factor.get("factor_file"):
        feature_key = Path(factor["factor_file"]).stem
    else:
        feature_key = stem_from_db or class_fallback
    if not factor.get("factor_file") and not stem_from_db:
        pass  # 回退 class 名,平台若用 stem 注册将永久 pending(与 mjs 一致)

    csv_task = ((submit_result.get("tasks") or {}).get("csv_ic") or {})
    task_feature = csv_task.get("feature") or feature_key

    # 阻塞等待:factor_check.py 内部 60s 轮询 + max-wait 兜底。
    # agent 只调 1 次,平台没跑完就在 subprocess 里等(不占 agent token)。
    # max-wait=540s(9 分钟,留 60s 给下载分析),run_py timeout=600s 兜底。
    result = run_py(
        FACTOR_CHECK_PY,
        ["run", "--skip-submit", "--names", task_feature, "--dir", check_output,
         "--mode", "none", "--force", "--max-wait", "540"],
        timeout_sec=600,
    )

    daily_ic_path = find_csv_ic_summary(check_output, feature_key)
    daily_ic_exists = Path(daily_ic_path).exists()
    daily_ic_size = Path(daily_ic_path).stat().st_size if daily_ic_exists else 0

    # 通用失败分诊(失败容忍)
    tg = None
    try:
        tg = triage_failure(
            factor_name=task_feature,
            dag_id=(
                (re.search(r"/dags/([^/]+)/", csv_task.get("job_url") or "") or [None, "GenerateXYsTest"])[1]
            ),
        )
    except Exception:
        tg = None
    triage_evidence = None
    if tg and tg.get("ok") and tg.get("triaged"):
        triage_evidence = {
            "airflow_dag_run_id": tg.get("dagRunId"),
            "airflow_root_task": tg.get("rootTask"),
            "airflow_locus": tg.get("locus"),
            "airflow_mapped": tg.get("mapped"),
            "airflow_n_root_instances": tg.get("nRootInstances"),
            "airflow_exit_code": tg.get("exitCode"),
            "airflow_signals": tg.get("signals"),
            "cause_text": tg.get("causeText"),
            "stderr_tail": (tg.get("causeText") or tg.get("rawTail") or "")[-500:] or None,
            "airflow_task_state_summary": tg.get("taskStateSummary"),
            "raw_tail": (tg.get("rawTail") or "")[-800:] or None,
        }

    # 1. factor_check.py 超时
    if result["timed_out"]:
        if triage_evidence:
            return _classify_failed(check_output, daily_ic_path, daily_ic_exists, daily_ic_size, result, triage_evidence, tg)
        return {
            "ok": False, "failureLayer": "platform_transient", "checkOutput": check_output,
            "dailyIcPath": daily_ic_path if daily_ic_exists else None, "dailyIcSize": daily_ic_size,
            "summary": f"[检查失败] factor_check 超时 ({result['duration_ms']}ms),dag 未确认 failed",
            "evidence": {"reason": "platform_transient", "stdout_tail": result["stdout"][-500:],
                         "stderr_tail": result["stderr"][-500:],
                         "note": "factor_check.py 超时且未能确认 dag 失败;多为平台管道慢/资源紧,有界重 check,不重写因子"},
        }

    # 2. factor_check.py 非 0 退出
    if result["exit_code"] != 0:
        if triage_evidence:
            return _classify_failed(check_output, daily_ic_path, daily_ic_exists, daily_ic_size, result, triage_evidence, tg)
        dag_state = (tg or {}).get("dagState") if tg and tg.get("ok") else None
        if dag_state == "running":
            return _transient(check_output, daily_ic_path, daily_ic_exists, daily_ic_size, result, "dag 仍 running,因子未跑完")
        if daily_ic_exists and daily_ic_size >= 1024:
            return _success(check_output, daily_ic_path, daily_ic_size, result, feature_key)
        return {
            "ok": False, "failureLayer": "check_failed", "checkOutput": check_output,
            "dailyIcPath": daily_ic_path if daily_ic_exists else None, "dailyIcSize": daily_ic_size,
            "summary": f"[检查失败] factor_check exit={result['exit_code']},dag={dag_state or 'n/a'},真因未明",
            "evidence": {"reason": "check_failed", "exit_code": result["exit_code"], "dag_state": dag_state,
                         "stdout_tail": result["stdout"][-500:], "stderr_tail": result["stderr"][-500:],
                         **_maybe_diagnosis(result)},
        }

    # 3. factor_check.py 正常退出:看 daily_ic 产物
    if not daily_ic_exists or daily_ic_size < 100:
        SPARSE_ZERO_RATIO = 0.8
        FULL_ZERO = 0.999
        zero_ratio = max_zero_ratio_from_screening(check_output, feature_key)
        if daily_ic_exists:
            reason = "check_output_too_small"
        elif zero_ratio is not None and SPARSE_ZERO_RATIO <= zero_ratio < FULL_ZERO:
            reason = "check_output_too_small"
        else:
            reason = "check_output_missing"
        if triage_evidence:
            return _classify_failed(check_output, daily_ic_path, daily_ic_exists, daily_ic_size, result, triage_evidence, tg)
        diagnosis = _build_too_small_diagnosis(zero_ratio) if reason == "check_output_too_small" else None
        zr_note = (f",zero_ratio={zero_ratio:.3f}{(SPARSE_ZERO_RATIO <= zero_ratio < FULL_ZERO and '(稀疏→质量rewrite)') or ''}"
                   if zero_ratio is not None else "")
        return {
            "ok": False, "failureLayer": reason, "checkOutput": check_output,
            "dailyIcPath": daily_ic_path if daily_ic_exists else None, "dailyIcSize": daily_ic_size,
            "summary": f"[检查失败] daily_ic_results.txt {'缺失' if not daily_ic_exists else f'过小 ({daily_ic_size}B)'}{zr_note}",
            "evidence": {
                "reason": reason, "daily_ic_size": daily_ic_size, "zero_ratio": zero_ratio,
                "stdout_tail": result["stdout"][-500:],
                "dir_listing": list_dir(check_output, 3, 30),
                **(diagnosis or {}),
            },
        }

    return _success(check_output, daily_ic_path, daily_ic_size, result, feature_key)
