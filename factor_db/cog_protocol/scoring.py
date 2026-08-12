"""人工评分表渲染(5 维 × 0-2)。

critic 能机械判定的维度自动填,其余留 "?" 人工填。
Gate:总分 <8 → NOT_INVENT_READY(v0 不接 INVENT,仅标记)。
第一次试跑**不以总分定成败**,以核心人工判据(删 Operator Question 看前三层)为首要。
"""

SCORE_DIMS = ["等价关系+压缩来源", "假设冲突", "hypothesis竞争", "抽象程度", "可调查性"]
DIM_HINT = {
    "等价关系+压缩来源": "0=无 1=模糊 2=明确:谁相同/为什么相同/丢掉什么差异",
    "假设冲突": "0=无 1=弱 2=强 failure_context",
    "hypothesis竞争": "0=无 1=有但弱 2=可区分(unique prediction)",
    "抽象程度": "0=因子 1=半抽象 2=算子级",
    "可调查性": "0=无 1=模糊 2=明确 measurement_question",
}


def _has(d: dict, *keys) -> bool:
    """嵌套判断 keys 路径存在且非空。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur or cur[k] in (None, "", []):
            return False
        cur = cur[k]
    return True


def auto_fill_scores(case: dict) -> dict:
    """从 case 的 critic verdicts + 产出机械填分。填不了留 '?'。

    保守:只有明确信号才给分,模糊一律 '?'(交人工)。
    """
    scores = {d: "?" for d in SCORE_DIMS}
    assumpt_crit = (case.get("assumption_critic") or {}).get("verdict")
    chall_crit = (case.get("challenge_critic") or {}).get("verdict")
    hypo_crit = (case.get("hypothesis_critic") or {}).get("verdict")
    opq_crit = (case.get("operator_q_critic") or {}).get("verdict")

    # 维度1:等价关系+压缩来源 —— 看 assumption 是否 PASS 且 equivalence_witness 完整
    sa = case.get("selected_assumption") or {}
    ew_ok = _has(sa, "equivalence_witness", "collapsed_difference") and \
        _has(sa, "equivalence_witness", "why_current_repr_merges")
    if assumpt_crit == "PASS" and ew_ok:
        scores["等价关系+压缩来源"] = 2
    elif ew_ok:
        scores["等价关系+压缩来源"] = 1

    # 维度2:假设冲突 —— challenge PASS 且 failure_context 完整
    sc = case.get("selected_challenge") or {}
    fc_ok = _has(sc, "failure_context", "prediction_task") and \
        _has(sc, "failure_context", "target_variable")
    if chall_crit == "PASS" and fc_ok:
        scores["假设冲突"] = 2
    elif fc_ok:
        scores["假设冲突"] = 1

    # 维度3:hypothesis 竞争 —— ≥3 个 + 都有 unique prediction + critic PASS
    hypos = case.get("hypotheses") or []
    non_null = [h for h in hypos if h.get("id") != "H0"]
    all_unique = len(non_null) >= 3 and all(h.get("what_it_predicts_uniquely") for h in non_null)
    if hypo_crit == "PASS" and all_unique:
        scores["hypothesis竞争"] = 2
    elif all_unique:
        scores["hypothesis竞争"] = 1

    # 维度4:抽象程度 —— operator_generality.abstraction_level + factor_disguise verdict
    oq = case.get("operator_question") or {}
    og = oq.get("operator_generality") or {}
    level = og.get("abstraction_level")
    fd = (case.get("post_checks") or {}).get("factor_disguise") or {}
    fd_verdict = fd.get("verdict")
    level_map = {"operator_level": 2, "semi_abstract": 1, "factor": 0}
    base = level_map.get(level, "?")
    if fd_verdict == "PASS" and isinstance(base, int):
        scores["抽象程度"] = base
    elif isinstance(base, int):
        scores["抽象程度"] = max(0, base - 1)  # 未过 disguise 降一档

    # 维度5:可调查性 —— measurement_question 非空 + 领域中性(critic PASS)
    mq = oq.get("measurement_question")
    if opq_crit == "PASS" and mq:
        scores["可调查性"] = 2
    elif mq:
        scores["可调查性"] = 1

    return scores


def _score_total(scores: dict) -> int:
    return sum(v for v in scores.values() if isinstance(v, int))


def render_case_score(case: dict) -> str:
    """单 case 评分表 markdown。"""
    scores = auto_fill_scores(case)
    total = _score_total(scores)
    gate = "INVENT_READY?" if total >= 8 else "NOT_INVENT_READY"
    lines = [
        "| 维度 | 分 | 标准 |",
        "|---|---|---|",
    ]
    for d in SCORE_DIMS:
        lines.append(f"| {d} | `{scores[d]}` | {DIM_HINT[d]} |")
    lines.append(f"| **总分** | **{total}/10** | {gate}(自动填,人工复核) |")
    return "\n".join(lines)


def render_total(cases: list) -> str:
    """所有 case 汇总评分。"""
    lines = ["## 评分汇总(自动填,需人工复核)", "", "| dead_end | " + " | ".join(SCORE_DIMS) + " | 总分 |", "|" + "---|" * (len(SCORE_DIMS) + 2)]
    for c in cases:
        de = (c.get("deadend") or {})
        scores = auto_fill_scores(c)
        total = _score_total(scores)
        xname = de.get("xname", "?")[:28]
        row = [xname] + [f"{scores[d]}" for d in SCORE_DIMS] + [f"**{total}**"]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
