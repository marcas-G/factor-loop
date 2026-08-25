"""平台调用工具(吸收 runtime/mcp/tools/platform.mjs)。submit/check + evidence 外存 + DAG 换名自愈。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from core.mcp import run_store
from core.metrics import is_all_zero_from_screening
from core.platform.gpu import submit_gpu_tasks
from core.platform.restest import run_submitted_restest, aggregate_ridge_svd
from core.retrieval.multiple_testing import build_multiple_testing_context
from core.stages.check import check_factor_programmatic
from core.stages.rename_factor import rename_factor_h
from core.stages.submit import submit_factor_programmatic

LARGE_EVIDENCE_KEYS = ["daily_ic_preview"]
LARGE_EVAL_KEYS = ["daily_ts", "xcorr_md"]


def platform_submit_factor(xname: str, factorFile: str, categories: list = None, params: dict = None) -> dict:
    """并发提交 CPU csv_ic 与 GPU ridge_svd。返回 {ok, features, tasks, error}。"""
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


def _retry_with_resubmit(xname, factor, check_output, submit_fn, check_fn):
    """平台任务图抖动自愈:check_output_missing 且非全零 → 原名 resubmit + recheck 一次。

    实证(2026-08-24/25 两案例): 配对提交后的首次 DAG run 偶发生成异常任务图
    (尾部任务缺失或走 cleanup_xy 分支), DAG 报 success 但无 IC 产物可下载;
    原名单重提交后任务图恢复正常, 产物即出。conf/代码均相同, 属平台侧竞态。
    成功返回 {result, submit}; 仍 missing/提交失败返回 None(交上层换名或 agent 兜底)。
    """
    factor_file = factor.get("factor_file")
    if not factor_file or not Path(factor_file).exists():
        return None

    new_submit = submit_fn(
        {"name": xname, "categories": factor.get("categories") or [],
         "params": factor.get("params") or {}},
        factor_file,
    )
    if not new_submit or not new_submit.get("ok"):
        return None

    new_result = check_fn(factor, new_submit, check_output)
    if new_result.get("failureLayer") == "check_output_missing":
        return None  # 仍 missing → 非任务图抖动, 不自愈
    return {"result": new_result, "submit": new_submit}


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
    return {"result": new_result, "submit": new_submit}


def _attach_research_context(result: dict, state: dict | None, factor_index: int | None) -> None:
    """Add multiplicity counts to the assess-facing eval metrics card."""
    if result.get("failureLayer") != "check_done":
        return
    evidence = result.get("evidence")
    eval_metrics = (evidence or {}).get("eval_metrics")
    if not isinstance(evidence, dict) or not isinstance(eval_metrics, dict):
        return

    factors = (state or {}).get("factors") or []
    factor = factors[factor_index] if factor_index is not None and 0 <= factor_index < len(factors) else {}
    try:
        from core.db import db
        with db.get_conn() as conn:
            context = build_multiple_testing_context(
                conn,
                factor or {},
                (state or {}).get("idea_id"),
                current_factors=factors,
                factor_index=factor_index,
            )
    except Exception as exc:
        context = {
            "available": False,
            "error": f"multiple_testing_context_query_failed: {type(exc).__name__}",
        }
    eval_metrics["research_context"] = context


def platform_check_factor(xname: str, submitRef: dict, checkOutput: str, run_id: str, factor_index: int) -> dict:
    """检查因子评估结果(调 factor_check.py run + 抓 evidence + 诊断)。工具内部直接把完整 evidence + failure_layer 落到 state(不经 agent 手,避免 LLM 二次加工丢字段)。返回给调用方的只有路由信息 {failureLayer, summary},不含 evidence。check_output_missing 时两级自愈:非全零先原名 resubmit(平台任务图抖动),全零换名重试(DAG 缓存陷阱)。"""
    factor = {"name": xname}
    state = None
    if run_id and factor_index is not None:
        try:
            state = run_store.run_load(run_id)
            factor = (state.get("factors") or [])[factor_index] if 0 <= factor_index < len(state.get("factors") or []) else factor
            submissions = submitRef.get("tasks") if isinstance(submitRef, dict) else None
            if isinstance(submissions, dict) and submissions:
                ridge = submissions.get("ridge_svd")
                run_store.run_save(run_id, {
                    f"factors.{factor_index}.evaluation_submissions": submissions,
                    **({f"factors.{factor_index}.gpu_submissions": {"ridge_svd": ridge}}
                       if ridge else {}),
                })
        except Exception:
            pass

    result = check_factor_programmatic(factor, submitRef, checkOutput)

    # 自愈 1(平台任务图抖动): check_output_missing 且非全零 → 原名 resubmit + recheck 一次
    # 自愈 2(DAG 缓存陷阱): check_output_missing + 全零 → 换名重试
    if result.get("failureLayer") == "check_output_missing" and factor.get("factor_file"):
        feature_key = Path(factor["factor_file"]).stem
        if is_all_zero_from_screening(checkOutput, feature_key):
            retried = _retry_with_rename(xname, factor, checkOutput,
                                         submit_factor_programmatic, check_factor_programmatic)
            if retried:
                result = retried["result"]
                new_submissions = (retried.get("submit") or {}).get("tasks")
                if run_id and isinstance(new_submissions, dict):
                    try:
                        run_store.run_save(run_id, {
                            f"factors.{factor_index}.evaluation_submissions": new_submissions,
                            f"factors.{factor_index}.gpu_submissions": {
                                "ridge_svd": new_submissions.get("ridge_svd")
                            },
                        })
                    except Exception:
                        pass
        else:
            retried = _retry_with_resubmit(xname, factor, checkOutput,
                                           submit_factor_programmatic, check_factor_programmatic)
            if retried:
                result = retried["result"]
                new_submissions = (retried.get("submit") or {}).get("tasks")
                if run_id and isinstance(new_submissions, dict):
                    try:
                        run_store.run_save(run_id, {
                            f"factors.{factor_index}.evaluation_submissions": new_submissions,
                            f"factors.{factor_index}.gpu_submissions": {
                                "ridge_svd": new_submissions.get("ridge_svd")
                            },
                        })
                    except Exception:
                        pass
                # 记 trace(非阻塞): resubmit 自愈成功
                try:
                    prev_trace = factor.get("retry_trace") if isinstance(factor.get("retry_trace"), list) else []
                    run_store.run_save(run_id, {
                        f"factors.{factor_index}.retry_trace": prev_trace + [{
                            "attempt": len(prev_trace) + 1, "failure_layer": "check_output_missing",
                            "fix": "platform_taskgraph_resubmit",
                            "summary": "missing(非全零) 疑似平台任务图抖动 → 原名 resubmit 自愈成功",
                        }],
                    })
                except Exception:
                    pass

    _attach_research_context(result, state if run_id else None, factor_index if run_id else None)

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


def platform_restest_factor(xname: str, factorFile: str, run_id: str, factor_index: int) -> dict:
    """等待/解析 GPU ridge_svd。工具内部把 ridge_svd 结果落 state, 返回路由信息。

    正常链路中任务已由 platform_submit_factor 与 csv_ic 同批提交;这里只轮询该任务、下载解析
    ridge_svd CSV 并聚合。平台只输出 R2_X + res_IC, 冗余判定只用这两个指标。
    """
    from core.stages.write_factor import extract_class_name_from_h, is_template_class
    class_name = extract_class_name_from_h(factorFile) or xname
    features = f"{class_name}<>" if is_template_class(factorFile) else class_name

    factor = {}
    try:
        state = run_store.run_load(run_id)
        factors = state.get("factors") or []
        factor = factors[factor_index] if 0 <= factor_index < len(factors) else {}
    except Exception:
        pass
    submitted = ((factor.get("gpu_submissions") or {}).get("ridge_svd") or {})
    if submitted.get("feature"):
        result = run_submitted_restest(submitted["feature"])
    else:
        # 兼容直接调用 MCP 工具的旧 state:只补交 GPU ridge_svd,不再走 CPU submit_restest。
        submission = submit_gpu_tasks(factorFile, features, ["ridge_svd"])
        if not submission.get("ok"):
            result = submission
        else:
            task = submission["tasks"]["ridge_svd"]
            try:
                run_store.run_save(run_id, {
                    f"factors.{factor_index}.gpu_submissions.ridge_svd": task,
                })
            except Exception:
                pass
            result = run_submitted_restest(task["feature"])

    if not result.get("ok"):
        # 失败也落 trace(追加, 不覆盖 agent 已写条目), restest 是 check_done 必做步骤
        from core.mcp.run_store import run_apply
        def _append_trace(state):
            fac = state["factors"][factor_index]
            fac.setdefault("retry_trace", [])
            if not isinstance(fac["retry_trace"], list):
                fac["retry_trace"] = [fac["retry_trace"]]
            fac["retry_trace"].append(f"restest 失败: {result.get('error')}")
        try:
            run_apply(run_id, _append_trace)
        except Exception:
            pass  # trace 落盘失败不掩盖原始 error
        return {"ok": False, "error": result.get("error")}

    metrics = result["metrics"]
    agg = aggregate_ridge_svd(metrics, engine="gpu")

    # 落 state(ridge_svd metrics 数组 + 聚合画像)
    run_store.run_save(run_id, {
        f"factors.{factor_index}.evidence.ridge_svd": metrics,
        f"factors.{factor_index}.evidence.ridge_svd_agg": agg,
        f"factors.{factor_index}.evidence.ridge_svd_engine": "gpu",
    })

    return {
        "ok": True,
        "r2_x": agg.get("R2_X"),
        "res_ic": agg.get("res_IC"),
    }


TOOLS = [
    ("platform_submit_factor", platform_submit_factor),
    ("platform_check_factor", platform_check_factor),
    ("platform_restest_factor", platform_restest_factor),
]
