#!/usr/bin/env python3
"""概念评估器：实现评估结果 → 四闭包结论 + 五级状态。

四闭包（各独立结论，不合并成一个分数）：
  1. 问题闭包   — 概念问题是否已在注册表（发明前已查，此处复核）
  2. 结构闭包   — 实现是否只是现有表达式/结构组合变体
  3. IC行为闭包 — 日 IC 向量能否被库内基底解释（滚动 OOS 残差）
  4. 方向行为闭包— swap 变体 IC 行为是否与声明的方向性质一致

五级状态：
  IMPLEMENTATION_NOVEL → REPRESENTATION_CANDIDATE → BEHAVIOR_OUTSIDE_CLOSURE
  → SIGNAL_OUTSIDE_CLOSURE → FULL_NON_TYPICAL_PASS

输入：候选契约 + 实现评估结果（IC/ICIR + 残差 + swap 对比）。
复用：residual_ic_strength（行为闭包）、factor_ic_correlate（最高相关）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 闭包判定阈值（与 assess 范式一致）
BEHAVIOR_RESIDUAL_MIN = 0.5      # 滚动 OOS 残差 ≥ 0.5 = 行为闭包外
RHO_MAX_REDLINE = 0.7            # 最高 |pearson| ≥ 0.7 = 冗余
ICIR_MIN = 0.3                   # IC 门槛
IC_MIN = 0.005


def check_question_closure(candidate: dict, registry_path=None) -> str:
    """问题闭包：复核问题是否已注册。"""
    from concept_critic import check_question_novel
    r = check_question_novel(candidate, registry_path)
    return "QUESTION_NOVEL" if r["novel"] else f"QUESTION_DUPLICATE({r.get('dup_with')})"


def check_structure_closure(contract: dict) -> str:
    """结构闭包：实现描述是否只是已有变换词组合。"""
    from concept_critic import check_irreducible
    r = check_irreducible(contract)
    return "IMPLEMENTATION_NOVEL" if r["irreducible"] else "IMPLEMENTATION_VARIANT"


def check_behavior_closure(eval_result: dict) -> str:
    """IC 行为闭包：rho_max 冗余线 + 滚动残差/OOS 残差相关。

    判定（与用户框架一致）：
      - rho_max ≥ 0.7（输出冗余线）→ INSIDE
      - 滚动 OOS 残差强度 ≥ 0.5 或 OOS 残差相关 ≥ 0.5 → OUTSIDE
        （OOS 残差相关高 = 残差保有主体行为，即使 top-6 基底残差强度 0.35）
    """
    resid = eval_result.get("behavior_residual_rolling")
    rho_max = eval_result.get("rho_max_ic")
    oos_corr = eval_result.get("oos_resid_corr")
    if rho_max is not None and rho_max >= RHO_MAX_REDLINE:
        return "BEHAVIOR_INSIDE_CLOSURE"
    if resid is None and rho_max is None and oos_corr is None:
        return "BEHAVIOR_CLOSURE_UNAVAILABLE"
    if (resid is not None and resid >= BEHAVIOR_RESIDUAL_MIN) or \
       (oos_corr is not None and oos_corr >= 0.5):
        return "BEHAVIOR_OUTSIDE_CLOSURE"
    return "BEHAVIOR_INSIDE_CLOSURE"


def check_direction_behavior(eval_result: dict, direction_property: str) -> str:
    """方向行为闭包：swap 变体 IC 与主实现 IC 的关系。"""
    ic_main = eval_result.get("ic_main")
    ic_swap = eval_result.get("ic_swap")
    if ic_main is None or ic_swap is None:
        return "DIRECTION_BEHAVIOR_UNAVAILABLE"
    corr = eval_result.get("swap_ic_corr")  # swap 与 main 的日 IC 相关
    if corr is None:
        # 无逐日相关：用符号关系近似
        if direction_property == "INVARIANT" and abs(ic_swap - ic_main) < 0.3 * abs(ic_main + 1e-9):
            return "DIRECTION_BEHAVIOR_SUPPORTED"
        if direction_property == "EQUIVARIANT" and ic_swap * ic_main < 0:
            return "DIRECTION_BEHAVIOR_SUPPORTED"
        return "DIRECTION_BEHAVIOR_UNVERIFIED"
    if direction_property == "INVARIANT" and corr > 0.5:
        return "DIRECTION_BEHAVIOR_SUPPORTED"
    if direction_property == "EQUIVARIANT" and corr < -0.5:
        return "DIRECTION_BEHAVIOR_SUPPORTED"
    return "DIRECTION_BEHAVIOR_UNVERIFIED"


def final_state(question: str, structure: str, behavior: str, direction: str,
                signal: str = "SIGNAL_CLOSURE_UNAVAILABLE") -> str:
    """五级状态。"""
    levels = []
    if question == "QUESTION_NOVEL" and structure == "IMPLEMENTATION_NOVEL":
        levels.append("REPRESENTATION_CANDIDATE")
    if behavior == "BEHAVIOR_OUTSIDE_CLOSURE":
        levels.append("BEHAVIOR_OUTSIDE_CLOSURE")
    if signal == "SIGNAL_OUTSIDE_CLOSURE":
        levels.append("SIGNAL_OUTSIDE_CLOSURE")
    if not levels:
        return "IMPLEMENTATION_NOVEL" if structure == "IMPLEMENTATION_NOVEL" else "IMPLEMENTATION_VARIANT"
    if "SIGNAL_OUTSIDE_CLOSURE" in levels and "BEHAVIOR_OUTSIDE_CLOSURE" in levels:
        return "FULL_NON_TYPICAL_PASS"
    return levels[-1]


def assess(candidate: dict, eval_result: dict, registry_path=None) -> dict:
    """主入口：四闭包 → 五级状态。"""
    q = check_question_closure(candidate, registry_path)
    s = check_structure_closure(candidate)
    b = check_behavior_closure(eval_result)
    d = check_direction_behavior(eval_result, candidate.get("direction_property"))
    sig = eval_result.get("signal_closure", "SIGNAL_CLOSURE_UNAVAILABLE")
    return {
        "question_closure": q,
        "structure_closure": s,
        "behavior_closure": b,
        "direction_behavior": d,
        "signal_closure": sig,
        "final": final_state(q, s, b, d, sig),
        "ic_gate": {
            "pass": (eval_result.get("icir", 0) or 0) >= ICIR_MIN
                    and abs(eval_result.get("ic", 0) or 0) >= IC_MIN,
            "ic": eval_result.get("ic"),
            "icir": eval_result.get("icir"),
        },
    }


if __name__ == "__main__":
    # 干跑：ShockAbsorption 回放（应得 NON_TYPICAL_CANDIDATE 级）
    cand = {
        "measurement_question": "重复冲击下盘口的响应函数是否变化?",
        "latent_construct": "shock_response_resilience",
        "direction_property": "EQUIVARIANT",
    }
    eval_res = {
        "ic": 0.0117, "icir": 0.446,
        "behavior_residual_rolling": 0.35,
        "oos_resid_corr": 0.93,
        "rho_max_ic": 0.61,
        "ic_main": 0.0117, "ic_swap": -0.0110, "swap_ic_corr": None,
    }
    print(json.dumps(assess(cand, eval_res), ensure_ascii=False, indent=1))
