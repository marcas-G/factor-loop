"""平台调用工具(吸收 runtime/mcp/tools/platform.mjs)。submit/check + evidence 外存 + DAG 换名自愈。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from core.mcp import run_store
from core.metrics import is_all_zero_from_screening
from core.stages.check import check_factor_programmatic
from core.stages.rename_factor import rename_factor_h
from core.stages.submit import submit_factor_programmatic

LARGE_EVIDENCE_KEYS = ["daily_ic_preview"]
LARGE_EVAL_KEYS = ["daily_ts", "xcorr_md"]


def platform_submit_factor(xname: str, factorFile: str, categories: list = None, params: dict = None) -> dict:
    """把因子推送到量化平台(调 featuretool.py submit)。返回 {ok, features, error}。"""
    factor = {"name": xname, "categories": categories or [], "params": params or {}}
    return submit_factor_programmatic(factor, factorFile)


def _offload_large_evidence(evidence, run_dir: str, xname: str) -> tuple:
    """P6:evidence 大字段外存,防 state 膨胀。返回 (slimmed_evidence, evidence_file)。"""
    if not isinstance(evidence, dict):
        return evidence, None
    slimmed = {**evidence}

    offloaded_top = {}
    for k in LARGE_EVIDENCE_KEYS:
        if slimmed.get(k) is not None:
            offloaded_top[k] = slimmed.pop(k)

    offloaded_eval = {}
    em = slimmed.get("eval_metrics")
    if isinstance(em, dict) and isinstance(em.get("csv_ic"), dict):
        csv_ic = {**em["csv_ic"]}
        for k in LARGE_EVAL_KEYS:
            if csv_ic.get(k) is not None:
                offloaded_eval[k] = csv_ic.pop(k)
        em["csv_ic"] = {**csv_ic, "_offloaded": list(offloaded_eval.keys())}
        slimmed["eval_metrics"] = em

    full_offload = {**offloaded_top, **offloaded_eval}
    if not full_offload:
        return slimmed, None

    evidence_file = str(Path(run_dir) / f"{xname}_evidence.json")
    try:
        Path(evidence_file).write_text(json.dumps(full_offload, ensure_ascii=False, indent=2), encoding="utf-8")
        slimmed["evidence_file"] = evidence_file
        slimmed["evidence_offloaded_keys"] = list(full_offload.keys())
    except Exception as e:
        return evidence, None  # 外存失败 → 保留原 evidence
    return slimmed, evidence_file


def _retry_with_rename(xname, factor, check_output, submit_fn, check_fn):
    """DAG 缓存陷阱自愈:换名 + 重 submit + 重 check。成功返回 {result},失败 None。"""
    factors_dir = Path(factor.get("factor_file")).parent if factor.get("factor_file") else Path("factors")

    def exists_in_db(x):
        from core.db import db
        with db.get_conn() as conn:
            return db.factor_exists(conn, x)

    try:
        rename = rename_factor_h(xname, factor["factor_file"], factors_dir, exists_in_db)
    except Exception as e:
        return None

    new_submit = submit_fn({"name": rename["newXname"], "categories": factor.get("categories") or [],
                            "params": factor.get("params") or {}}, rename["newFile"])
    if not new_submit or not new_submit.get("ok"):
        return None

    new_check_output = str(Path(check_output).parent / f"{rename['newXname']}_check")
    new_result = check_fn({"name": rename["newXname"], "factor_file": rename["newFile"]}, new_submit, new_check_output)
    if new_result.get("failureLayer") == "check_output_missing":
        return None  # 仍 missing → 真代码问题,不自愈
    new_result["_renameInfo"] = {"oldXname": xname, "newXname": rename["newXname"], "newFile": rename["newFile"]}
    return {"result": new_result}


def platform_check_factor(xname: str, submitRef: dict, checkOutput: str, run_id: str, factor_index: int) -> dict:
    """检查因子评估结果(调 factor_check.py run + 抓 evidence + 诊断)。工具内部直接把完整 evidence + failure_layer 落到 state(不经 agent 手,避免 LLM 二次加工丢字段)。返回给调用方的只有路由信息 {failureLayer, summary},不含 evidence。check_output_missing + 因子值全零时自动换名重试一次(DAG 缓存陷阱自愈)。"""
    factor = {"name": xname}
    if run_id and factor_index is not None:
        try:
            state = run_store.run_load(run_id)
            factor = (state.get("factors") or [])[factor_index] if 0 <= factor_index < len(state.get("factors") or []) else factor
        except Exception:
            pass

    result = check_factor_programmatic(factor, submitRef, checkOutput)

    # DAG 缓存陷阱自愈:check_output_missing + 全零 → 换名重试
    if result.get("failureLayer") == "check_output_missing" and factor.get("factor_file"):
        feature_key = Path(factor["factor_file"]).stem
        if is_all_zero_from_screening(checkOutput, feature_key):
            retried = _retry_with_rename(xname, factor, checkOutput,
                                         submit_factor_programmatic, check_factor_programmatic)
            if retried:
                result = retried["result"]

    # evidence 落 state 前 offload 大字段(P6)
    if run_id and factor_index is not None:
        slim_evidence = result.get("evidence")
        evidence_file = None
        try:
            state = run_store.run_load(run_id)
            run_dir = state.get("run_dir")
            if run_dir:
                slim_evidence, evidence_file = _offload_large_evidence(result.get("evidence"), run_dir, xname)
        except Exception:
            pass
        patch = {
            f"factors.{factor_index}.failure_layer": result.get("failureLayer"),
            f"factors.{factor_index}.evidence": slim_evidence,
        }
        if evidence_file:
            patch[f"factors.{factor_index}.evidence_file"] = evidence_file
        if result.get("_renameInfo"):
            ri = result["_renameInfo"]
            prev_trace = factor.get("retry_trace") if isinstance(factor.get("retry_trace"), list) else []
            patch[f"factors.{factor_index}.name"] = ri["newXname"]
            patch[f"factors.{factor_index}.xname"] = ri["newXname"]
            patch[f"factors.{factor_index}.factor_file"] = ri["newFile"]
            patch[f"factors.{factor_index}.retry_trace"] = prev_trace + [{
                "attempt": len(prev_trace) + 1, "failure_layer": "check_output_missing",
                "fix": "dag_cache_rename",
                "summary": f"全零 check_output_missing 疑似 DAG 缓存命中 → 换名 {ri['oldXname']}→{ri['newXname']} 强制重跑",
            }]
        run_store.run_save(run_id, patch)

    return {"failureLayer": result.get("failureLayer"), "summary": result.get("summary")}


TOOLS = [
    ("platform_submit_factor", platform_submit_factor),
    ("platform_check_factor", platform_check_factor),
]
