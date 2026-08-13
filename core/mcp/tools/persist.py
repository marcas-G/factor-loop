"""写库工具(吸收 runtime/mcp/tools/persist.mjs)。复用 stages.persist 的 persist_verdict。"""
import re

from core.db import db
from core.mcp import run_store
from core.stages.persist import persist_verdict


def persist_idea(text: str) -> dict:
    """把一条研究 idea 写入 ideas 表。"""
    with db.get_conn() as conn:
        return {"id": db.add_idea(conn, text)}


def persist_factor(run_id: str, factor_index: int, mode: str = "commit", verdict: dict = None) -> dict:
    """因子入库。mode=prepare: 只入 factors 表占位(status=draft, 解锁 assess 路径B ingest 的 FK, 不写 eval/lesson/不定 verdict); mode=commit(默认): 按 verdict 写 eval/lesson/定 status。工具内部从 state.json 读 factor/factorFile/checkResult/retryInfo/ideaId。"""
    state = run_store.run_load(run_id)
    if factor_index < 0 or factor_index >= len(state["factors"]):
        return {"ok": False, "error": f"factor_index 越界: {factor_index} (factors.length={len(state['factors'])})"}
    f = state["factors"][factor_index]
    if f.get("failure_layer") != "check_done":
        return {"ok": False, "error": f"factor[{factor_index}] failure_layer={f.get('failure_layer')} 非 check_done,不入库"}
    if not f.get("factor_file"):
        return {"ok": False, "error": f"factor[{factor_index}].factor_file 为空(run-factor-agent 未写入)"}

    factor = {
        "name": f.get("name"), "formula": f.get("formula"), "hypothesis": f.get("hypothesis"),
        "intuition": f.get("intuition"), "categories": f.get("categories") or [], "tags": f.get("tags") or [],
    }
    check_result = {
        "failureLayer": f.get("failure_layer"), "features": f.get("name"),
        "evidence": f.get("evidence") or {}, "checkOutput": None,
    }
    retry_info = f.get("last_rewrite")
    idea_id = state.get("idea_id")

    return persist_verdict(factor, f["factor_file"], check_result, retry_info, verdict, idea_id, mode)


def _validate_candidates(factors) -> dict:
    """P5 防御:校验每个 factor 必填字段。任一不合规 → 整批拒绝。"""
    if not isinstance(factors, list):
        return {"ok": False, "error": f"factors 必须是数组, 得到 {type(factors).__name__}"}
    if not factors:
        return {"ok": False, "error": "factors 为空数组(至少 1 个候选)"}
    required = ["name", "formula", "intuition", "tags"]
    errors = []
    for i, f in enumerate(factors):
        if not isinstance(f, dict):
            errors.append(f"factor[{i}]: 不是对象(得到 {type(f).__name__})")
            continue
        has_hypothesis = f.get("hypothesis") or f.get("diff_check") or f.get("coord_usage")
        missing = []
        for k in required:
            v = f.get(k)
            if k == "intuition":
                if not v and not has_hypothesis:
                    missing.append(k)
            elif k == "tags":
                if not isinstance(v, list) or not v:
                    missing.append(k)
            elif not v or (isinstance(v, str) and not v.strip()):
                missing.append(k)
        if missing:
            errors.append(f"factor[{i}]({f.get('name') or '无name'}): 缺 {'/'.join(missing)}")
        if f.get("name") and not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", f["name"]):
            errors.append(f"factor[{i}] name=\"{f['name']}\" 非合法类名(须字母开头+字母数字下划线)")
    if errors:
        return {"ok": False, "error": f"候选校验失败({len(errors)} 处, 整批拒绝防止半残 state):\n  - " + "\n  - ".join(errors)}
    return {"ok": True}


def persist_candidates(run_id: str, idea_text: str, factors: list) -> dict:
    """brainstorm 一次性持久化:存 idea + 完整候选 factors。把 brainstorm 输出的候选 JSON 整体传入,工具内部 persist_idea + run_save factors(补全 status/factor_file 等 schema 字段,保留 intuition/diff_check/coord_usage/params/db_research)。只调一次,替代逐候选 run_save。"""
    validation = _validate_candidates(factors)
    if not validation["ok"]:
        return {"ok": False, "error": validation["error"], "n_factors": 0}

    with db.get_conn() as conn:
        idea_id = db.add_idea(conn, idea_text)

    full_factors = []
    for f in factors:
        full_factors.append({
            "name": f.get("name"),
            "formula": f.get("formula"),
            "hypothesis": f.get("hypothesis") or "\n\n".join(x for x in [f.get("intuition"), f.get("diff_check"), f.get("coord_usage")] if x) or None,
            "categories": f.get("categories") or [],
            "tags": f.get("tags") or [],
            "coordinates": f.get("coordinates"),
            "intuition": f.get("intuition"),
            "diff_check": f.get("diff_check"),
            "coord_usage": f.get("coord_usage"),
            "params": f.get("params") or {},
            "db_research": f.get("db_research"),
            "suggestion_id": f.get("suggestion_id"),
            "iterates_from": f.get("iterates_from"),
            "factor_file": None, "status": "pending", "failure_layer": None,
            "retry_trace": [], "evidence": None, "verdict": None, "persisted": None,
        })

    # 迭代接续:候选带 suggestion_id 时 claim(open→in_progress)
    claimed = []
    for f in full_factors:
        if f.get("suggestion_id") is not None:
            try:
                with db.get_conn() as conn:
                    r = db.claim_iteration(conn, f["suggestion_id"])
                claimed.append({"suggestion_id": f["suggestion_id"], "iterates_from": f.get("iterates_from"), **r})
            except Exception as e:
                claimed.append({"suggestion_id": f["suggestion_id"], "error": str(e)})

    def apply(state):
        state["idea"] = idea_text
        state["idea_id"] = idea_id
        state["factors"] = full_factors

    run_store.run_apply(run_id, apply)
    return {"idea_id": idea_id, "n_factors": len(full_factors), "claimed": claimed}


TOOLS = [
    ("persist_idea", persist_idea),
    ("persist_factor", persist_factor),
    ("persist_candidates", persist_candidates),
]
