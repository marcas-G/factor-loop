#!/usr/bin/env python3
"""DB 写入:verdict 决定写哪些表(吸收 runtime/stages/persist.mjs)。

策略:
  verdict=pass → factors(status=evaluated)+ factor_evals + success_pattern lesson + 支持度
  verdict=fail → factors(status=dead_end)+ factor_evals + dead_end lesson + 支持度
失败因子(submit_failed/platform_*/check_failed)→ 不调本函数,靠 state.json 留痕。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from core.db import db
from core.tools import parse_frontmatter as pf

# 通过判据阈值(新>优:指标低可过,冗余必严)。
NOISE_ICIR_FLOOR = 0.05  # |screening.icir|<此值(纯噪声)且无救场 → fail

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
GEN_EMBEDDINGS = str(_PROJECT_ROOT / "core" / "tools" / "gen_embeddings.py")
GEN_ANCHOR = str(_PROJECT_ROOT / "core" / "tools" / "ai_generate_anchor.py")


def add_factor_from_h_file(h_file: str, idea_id: int | None = None, status: str = "draft",
                           intuition: str | None = None) -> str | None:
    """从 .h frontmatter 提取 meta → INSERT factors。返回 xname 或 None。"""
    text = Path(h_file).read_text(encoding="utf-8", errors="replace")
    meta = pf.parse_frontmatter(text) or {}
    if "class_name" not in meta:
        meta["class_name"] = pf.extract_class_name(text) or ""
    if "params" not in meta:
        meta["params"] = pf.extract_template_default_param(text) or None
    for k, v in list(meta.items()):
        if hasattr(v, "isoformat"):
            meta[k] = v.isoformat()

    if not meta.get("xname") and not meta.get("class_name"):
        return None
    xname = meta.get("xname") or meta.get("class_name")

    with db.get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM factors WHERE xname = ?", (xname,)).fetchone()
        if exists:
            if meta.get("formula"):
                conn.execute(
                    "UPDATE factors SET formula_text = ?, last_updated_ts = CURRENT_TIMESTAMP WHERE xname = ?",
                    (meta.get("formula"), xname),
                )
            return xname
        conn.execute(
            """INSERT INTO factors
               (xname, class_name, file_path, formula_text, params, status, created_ts, intuition)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                xname,
                meta.get("class_name") or None,
                f"factors/{Path(h_file).name}",  # 统一相对项目根格式(与 backfill 一致)
                meta.get("formula") or None,
                json.dumps(meta["params"], ensure_ascii=False) if meta.get("params") else None,
                status,
                meta.get("created_ts") or datetime.now().isoformat()[:10],
                meta.get("intuition") or intuition,
            ),
        )
        # 建 idea_factor_links(update_idea_support_score 依赖此关联查因子)
        if idea_id is not None:
            conn.execute(
                "INSERT OR IGNORE INTO idea_factor_links (idea_id, factor_xname) VALUES (?, ?)",
                (idea_id, xname),
            )
    return xname


def _extract_metrics(eval_metrics) -> dict:
    """从 eval_metrics 提取 metrics(适配 3 种历史结构)。"""
    if not eval_metrics:
        return {"ic_mean": None, "icir": None, "sharpe": None, "rank_ic": None}
    from_screening = (eval_metrics.get("core_metrics") or {}).get("screening") or {}
    from_deep = eval_metrics.get("deep_best") or {}
    return {
        "ic_mean": from_screening.get("ic_mean") if from_screening.get("ic_mean") is not None
                   else eval_metrics.get("ic_mean", eval_metrics.get("1_ic")),
        "icir": from_screening.get("icir") if from_screening.get("icir") is not None
                else eval_metrics.get("icir", eval_metrics.get("2_icir")),
        "sharpe": from_deep.get("conditional_sharpe") if from_deep.get("conditional_sharpe") is not None
                  else (eval_metrics.get("bucket_annualized_sharpe") or {}).get("@1s"),
        "rank_ic": from_screening.get("spearman") if from_screening.get("spearman") is not None
                   else from_deep.get("rank_ic_max"),
    }


def _build_success_lesson_text(factor, verdict, eval_metrics) -> str:
    f = (eval_metrics or {}).get("factor_level") or {}
    deep = (eval_metrics or {}).get("deep_best") or {}
    strengths = "; ".join(verdict.get("key_strengths") or [])
    return "\n".join([
        f"[success_pattern] {factor.get('name')}",
        f"假设: {(factor.get('hypothesis') or '(无)')[:200]}",
        f"X-Y 对: {f.get('n_pairs') or '?'} 个 (keep={f.get('keep') or 0}, watch={f.get('watch') or 0}, reject={f.get('reject') or 0})",
        f"最佳 score={f.get('best_score') or '?'} pair={f.get('best_pair') or '?'}",
        f"deep: conditional_sharpe={deep.get('conditional_sharpe') if deep.get('conditional_sharpe') is not None else '?'} "
        f"cum_ret={deep.get('cum_ret_pct') if deep.get('cum_ret_pct') is not None else '?'}% "
        f"monthly_icir={deep.get('monthly_icir') if deep.get('monthly_icir') is not None else '?'}",
        f"强项: {strengths}",
    ])


def _build_dead_end_lesson_text(factor, verdict, eval_metrics) -> str:
    f = (eval_metrics or {}).get("factor_level") or {}
    deep = (eval_metrics or {}).get("deep_best") or {}
    reasons = (eval_metrics or {}).get("failure_reasons") or {}
    top_reasons = ", ".join(f"{k}({v})" for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:3])
    weaknesses = "; ".join(verdict.get("key_weaknesses") or [])
    return "\n".join([
        f"[dead_end] {factor.get('name')}",
        f"假设: {(factor.get('hypothesis') or '(无)')[:200]}",
        f"X-Y 对: {f.get('n_pairs') or '?'} 个 (keep={f.get('keep') or 0}, watch={f.get('watch') or 0}, reject={f.get('reject') or 0})",
        f"deep: conditional_sharpe={deep.get('conditional_sharpe') if deep.get('conditional_sharpe') is not None else '?'} "
        f"monthly_icir={deep.get('monthly_icir') if deep.get('monthly_icir') is not None else '?'}",
        f"主要失败原因: {top_reasons or '(无)'}",
        f"弱项: {weaknesses}",
        f"建议迭代: {verdict.get('suggested_iteration') or '(无)'}",
    ])


def _gen_anchor_and_embedding(xname: str) -> None:
    """subprocess 生成 anchor_text + embedding(降级不阻塞)。"""
    from core.infra.run_py import run_py
    run_py(GEN_ANCHOR, ["--xname", xname], timeout_sec=120)
    run_py(GEN_EMBEDDINGS, ["--xname", xname], timeout_sec=120)


def persist_verdict(factor: dict, factor_file: str, check_result: dict, retry_info, verdict: dict | None,
                    idea_id: int | None, mode: str = "commit") -> dict:
    """按 verdict 写库。返回 {xname, status, ...} 或 {ok: False, error}。"""
    try:
        if check_result.get("failureLayer") != "check_done":
            return {"ok": False, "error": f"failureLayer={check_result.get('failureLayer')} 非 check_done,不入库"}

        # prepare 模式:占位入库(status=draft),解锁 assess 路径B FK
        if mode == "prepare":
            written = add_factor_from_h_file(factor_file, idea_id, status="draft", intuition=factor.get("intuition"))
            if not written:
                return {"ok": False, "error": f"addFactorFromHFile 返回 None(frontmatter 解析失败),factorFile={factor_file}"}
            with db.get_conn() as conn:
                db.ensure_formula_tags(conn, written, factor.get("formula"), factor.get("tags"))
            _gen_anchor_and_embedding(written)
            return {"xname": written, "mode": "prepare", "status": "draft"}

        if not verdict:
            return {"ok": False, "error": "verdict 为空(commit 模式必填;占位入库用 mode=prepare)"}

        # featureKey = .h stem(去掉模板参数 <...>)
        feature_key = re.sub(r"<.*>$", "", (check_result.get("features") or factor.get("name") or "")).strip()
        if not feature_key:
            return {"ok": False, "error": "无法确定 xname(checkResult.features 和 factor.name 都为空)"}
        ts = datetime.now().isoformat()
        eval_metrics = (check_result.get("evidence") or {}).get("eval_metrics") or None
        metrics = _extract_metrics(eval_metrics)

        # === 早期否决(不依赖入库数据) ===
        if verdict.get("verdict") == "pass" and abs(metrics["icir"] or 0) < NOISE_ICIR_FLOOR:
            tf = (eval_metrics or {}).get("transform_family") or {}
            has_rescue = any(v is not None and abs(float(v)) >= 0.05 for v in tf.values())
            if not has_rescue:
                verdict["verdict"] = "fail"
                (verdict.setdefault("key_weaknesses", []).append(
                    f"代码兜底:|screening.icir|<{NOISE_ICIR_FLOOR}(纯噪声)且无变换族救场,第4红线否决"))
        if verdict.get("verdict") == "pass" and not (eval_metrics or {}).get("csv_ic"):
            dbm = (eval_metrics or {}).get("deep_best") or {}
            deep_ok = any(v is not None for v in dbm.values())
            if not deep_ok and abs(metrics["icir"] or 0) < 3:
                verdict["verdict"] = "fail"
                (verdict.setdefault("key_weaknesses", []).append(
                    "代码兜底:deepbest 全 None(第二/三维数据缺)+ ICIR<3,评估不全硬否决"))

        full_metrics = {**metrics, "eval_metrics": eval_metrics,
                        "conditional_returns": (eval_metrics or {}).get("deep_best"),
                        "significant": verdict.get("verdict") == "pass"}

        if verdict.get("verdict") == "pass":
            written = add_factor_from_h_file(factor_file, idea_id, status="evaluated", intuition=factor.get("intuition"))
            if not written:
                return {"ok": False, "error": f"addFactorFromHFile 返回 None,factorFile={factor_file}"}
            with db.get_conn() as conn:
                db.ensure_formula_tags(conn, written, factor.get("formula"), factor.get("tags"))
            _gen_anchor_and_embedding(written)
            with db.get_conn() as conn:
                db.add_eval(conn, written, ts, full_metrics, idea_id=idea_id, mode="full",
                            raw_path=check_result.get("checkOutput"), status="evaluated")
                lesson_id = db.add_lesson(conn, "success_pattern", "factor",
                                          _build_success_lesson_text(factor, verdict, eval_metrics),
                                          idea_id=idea_id, factor_xname=written,
                                          evidence={"xname": written, "icir": metrics["icir"], "ic_mean": metrics["ic_mean"],
                                                    "sharpe": metrics["sharpe"], "decision_breakdown": (eval_metrics or {}).get("factor_level"),
                                                    "deep_best": (eval_metrics or {}).get("deep_best"),
                                                    "strengths": verdict.get("key_strengths") or []})
                if idea_id is not None:
                    db.update_idea_support_score(conn, idea_id)
            if retry_info and retry_info.get("fixed") and retry_info.get("changed_code"):
                if factor.get("name") != written:
                    with db.get_conn() as conn:
                        db.add_iteration(conn, factor.get("name"), written, idea_id,
                                         retry_info.get("changes"), "improved", None)
            return {"xname": written, "status": "evaluated", "metrics": metrics, "lessonId": lesson_id}

        else:
            # fail/dead_end:lesson FK 依赖 factors → 先写 factors(dead_end)
            written = add_factor_from_h_file(factor_file, idea_id, status="dead_end", intuition=factor.get("intuition"))
            if not written:
                return {"ok": False, "error": f"addFactorFromHFile 返回 None,factorFile={factor_file}"}
            with db.get_conn() as conn:
                db.ensure_formula_tags(conn, written, factor.get("formula"), factor.get("tags"))
            _gen_anchor_and_embedding(written)
            with db.get_conn() as conn:
                db.add_eval(conn, written, ts, full_metrics, idea_id=idea_id, mode="full",
                            raw_path=check_result.get("checkOutput"), status="dead_end")
                lesson_id = db.add_lesson(conn, "dead_end", "factor",
                                          _build_dead_end_lesson_text(factor, verdict, eval_metrics),
                                          idea_id=idea_id, factor_xname=written,
                                          evidence={"xname": written, "icir": metrics["icir"], "ic_mean": metrics["ic_mean"],
                                                    "decision_breakdown": (eval_metrics or {}).get("factor_level"),
                                                    "weaknesses": verdict.get("key_weaknesses") or [],
                                                    "suggested_iteration": verdict.get("suggested_iteration") or None})
                if idea_id is not None:
                    db.update_idea_support_score(conn, idea_id)
            return {"xname": written, "status": "dead_end", "metrics": metrics, "lessonId": lesson_id}

    except Exception as e:
        return {"ok": False, "error": f"persistVerdict 异常: {e}"}
