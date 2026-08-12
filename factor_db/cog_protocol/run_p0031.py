#!/usr/bin/env python3
"""P003.1 dry-run: F1 depth collapse + F2 path collapse 完整闭环。

Factor → Assumption → EvidenceQuery → probe 执行 → EvidenceCard → BridgeValidator
(→ Adjudicator 由调用方单独派, 本脚本只到 evidence_card + bridge)
"""
import sys, json
sys.path.insert(0, "factor_db")
from cog_protocol.evidence_query_compiler import compile_query, execute_query
from cog_protocol.bridge_validator import validate_bridge

# ── F1: BsiSizeLevelBareRank depth collapse ──
# F1 construction: bp = log1p(bid_size[0]) - log1p(ask_size[0]), 只用 best 档(0), rank
# assumption: F 把"同 ratio 但深档分布不同"的盘口视为等价(只用 best 档 → depth>=1 被压)
F1 = {
    "factor": "BsiSizeLevelBareRank",
    "assumption": {
        "id": "F1_depth_collapse",
        "claim": "F 只取 bidSize(0)/askSize(0) best 档, 把深档(depth>=1)分布差异压掉",
        "held_equal_coordinates": ["ratio"],       # F 保持 best 档 ratio
        "collapsed_difference": ["depth"],          # 深档被压
    },
}

# ── F2: BsiFirstDiffPrecursorRank path collapse ──
# F2 construction: d_bp = bp - prev_bp; output = percentile_rank(d_bp, diff_ring[500])
# assumption: F 的 diff_ring[500] 窗口把 500 tick 之前的 path 压掉
F2 = {
    "factor": "BsiFirstDiffPrecursorRank",
    "assumption": {
        "id": "F2_path_collapse",
        "claim": "F 的 diff_ring[500] 环形窗口丢弃 500 tick 之前的 path",
        "held_equal_coordinates": ["ratio"],
        "collapsed_difference": ["path"],
    },
}


def run_case(case, y_horizon="1", days=None):
    print(f"\n{'='*70}")
    print(f"  Research Object = {case['factor']}")
    print(f"  Assumption: {case['assumption']['id']} (collapsed={case['assumption']['collapsed_difference']})")
    print(f"{'='*70}")

    # 1. compile assumption → evidence_query
    contract, bindings, missing = compile_query(case["assumption"], case["factor"], y_horizon)
    print(f"\n[1] Evidence Query compiled:")
    print(f"    primitive: {contract['primitive']}")
    print(f"    bindings:  {bindings}")
    if missing:
        print(f"    ⚠ missing proxies: {missing} (这些维度当前无法调查)")

    # 2. bridge_validator (Gate C): 验证 query 对应 assumption
    evidence_test = {
        "held_fixed": contract["controls"]["must_hold_similar"],
        "varied_dimension": contract["variation"]["dimensions_allowed_to_change"],
        "behavioral_target": contract["task_context"]["target_behavior"],
    }
    bridge = validate_bridge(case["assumption"], evidence_test)
    print(f"\n[2] Bridge Validator (Gate C): bridge_valid={bridge['bridge_valid']}")
    print(f"    {bridge['reason'][:120]}")
    if not bridge["bridge_valid"]:
        print(f"    → 不执行 probe (bridge 断)。end.")
        return case, contract, bridge, None

    # 3. execute query → evidence_card
    if missing:
        print(f"\n[3] ⚠ skipped probe (missing proxies for: {missing})")
        return case, contract, bridge, None
    print(f"\n[3] Executing probe (loading .xy, stratifying, comparing Y)...")
    try:
        result = execute_query(contract, bindings, days=days, y_horizon=y_horizon)
    except Exception as e:
        print(f"    probe 执行失败: {e}")
        return case, contract, bridge, None

    ev = result["evidence_card"]
    print(f"    n_total={result['n_total']}, factors_used={result['factors_used']}")
    print(f"\n[4] Evidence Card:")
    for dim, r in ev.get("result", {}).items():
        print(f"    dim={dim}:")
        print(f"      mean_y_by_quantile: {r['mean_y_by_quantile']}")
        print(f"      hit_rate_by_quantile: {r['hit_rate_by_quantile']}")
        print(f"      monotonic_direction: {r['monotonic_direction']}")
        print(f"      max_effect: {r['max_effect']}  z_approx: {r['z_approx']}")
        print(f"      n_by_quantile: {r['n_by_quantile']}")
    print(f"\n    hypothesis_implications: {ev.get('hypothesis_implications')}")
    print(f"    limitations: {ev.get('limitations')}")
    print(f"    evidence_strength: {ev.get('evidence_strength')}")

    return case, contract, bridge, ev


if __name__ == "__main__":
    print("###### P003.1 DRY-RUN: Assumption-driven Evidence Investigation ######")
    print("###### F1 = BsiSizeLevelBareRank (depth collapse, CONDITIONAL_SLICE) ######")
    c1, ct1, br1, ev1 = run_case(F1, y_horizon="1")
    print("\n\n###### F2 = BsiFirstDiffPrecursorRank (path collapse, CONDITIONAL_TRAJECTORY) ######")
    c2, ct2, br2, ev2 = run_case(F2, y_horizon="1")

    # 汇总
    print(f"\n{'='*70}\n  SUMMARY\n{'='*70}")
    for name, ct, br, ev in [("F1 depth", ct1, br1, ev1), ("F2 path", ct2, br2, ev2)]:
        status = "bridge断" if not br["bridge_valid"] else ("evidence产出" if ev else "missing proxy")
        print(f"  {name}: bridge={br['bridge_valid']}, status={status}")
