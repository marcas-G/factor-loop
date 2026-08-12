#!/usr/bin/env python3
"""P003.3 A3 验证: 形成相位(突发 vs 累积)假设的 matched evidence。

A3: F(BsiSizeLevelBareRank, 浅档 ratio)压掉"形成相位" —— 同 F 值,
bid0 是突发到达(知情突袭/级联)vs 渐进累积(趋势),形成过程不同则预测含义不同。

代理: BsiFirstDiffPrecursorRank 的 d_bp rank = 当前 bp 变化的突发度。
match on F, stratify by tempo(d_bp 突发度), compare Y@1。
"""
import sys, json
sys.path.insert(0, "factor_db")
from cog_protocol.investigation import probe_compiler, evidence_card, xycache
from cog_protocol.bridge_validator import validate_bridge

F = "BsiSizeLevelBareRank"             # 载体(浅档 ratio, 有 .xy)
TEMPO_PROXY = "BsiFirstDiffPrecursorRank"  # d_bp 突发度代理(有 .xy, 118 天)

assumption = {
    "id": "A3_formation_phase",
    "claim": "F(浅档 ratio)把'bid0 突发到达'与'渐进累积'视为等价(只取当前快照,压掉形成相位)",
    "held_equal_coordinates": ["ratio"],
    "collapsed_difference": ["tempo"],   # 形成相位 → tempo 受控词汇
}

evidence_test = {
    "held_fixed": ["ratio"],
    "varied_dimension": ["tempo"],
    "behavioral_target": "future_return@1",
}

print("=== A3 形成相位假设 ===")
print(f"F = {F} (载体)")
print(f"tempo proxy = {TEMPO_PROXY} (d_bp 突发度)")
print(f"claim: {assumption['claim']}")
print()

# Gate C bridge
bridge = validate_bridge(assumption, evidence_test)
print(f"[Gate C] bridge_valid = {bridge['bridge_valid']}")
print(f"  {bridge['reason'][:130]}")
if not bridge["bridge_valid"]:
    print("  bridge 断,不跑 probe"); sys.exit()

# contract + bindings
bindings = {F: F, "tempo": TEMPO_PROXY}
contract = {
    "test_id": "A3_formation_phase",
    "research_object": F,
    "primitive": "CONDITIONAL_SLICE",
    "challenged_equivalence": {
        "representation_equal_on": [F],
        "collapsed_difference": ["tempo"],
        "mechanism": "F 压掉形成相位(突发 vs 累积)",
    },
    "task_context": {"symbol": "SHFE-AG", "horizon": "1", "target_behavior": "future_return@1"},
    "controls": {"must_hold_similar": ["ratio"]},
    "variation": {"dimensions_allowed_to_change": ["tempo"]},
    "competing_predictions": {
        "H_collapse": {"unique_prediction": "若 F 压掉形成相位有害, Y 应随 tempo 分位单调变化"},
        "H_partial": {"unique_prediction": "placeholder"},
        "H_confound": {"unique_prediction": "placeholder"},
        "H0": {"unique_prediction": "Y 不随 tempo 变化(形成相位无信息, F 压缩无害)"},
    },
    "required_observations": ["Y by tempo quantile, F matched"],
    "success_pattern": "Y 在 tempo 分位间单调/显著差异 → 形成相位有信息(CONTRADICTS 候选)",
    "failure_pattern": "Y 无差异 → 形成相位无信息(CONSISTENT)",
    "confounders": [],
    "data_requirements": {"proxy_factors": bindings},
}

# execute probe
print("\n[probe] 加载 .xy + stratify by tempo + compare Y@1 ...")
dfs = {f: xycache.load_days(f, days=None) for f in [F, TEMPO_PROXY]}
result = probe_compiler.compile_and_run(contract, bindings, dfs, y_horizon="1")
ev = evidence_card.build_evidence(result, contract, observed_incompat_strength="DIRECT")

print(f"  n_total = {result['n_total']}")
print(f"\n[Evidence Card]")
for dim, r in ev.get("result", {}).items():
    print(f"  dim={dim}:")
    print(f"    mean_y_by_quantile [low/mid/high tempo]: {r['mean_y_by_quantile']}")
    print(f"    hit_rate_by_quantile: {r['hit_rate_by_quantile']}")
    print(f"    monotonic_direction: {r['monotonic_direction']}")
    print(f"    max_effect: {r['max_effect']}  z_approx: {r['z_approx']}")
    print(f"    n_by_quantile: {r['n_by_quantile']}")
print(f"\n  hypothesis_implications: {ev.get('hypothesis_implications')}")
print(f"  evidence_strength: {ev.get('evidence_strength')}")

# 存 evidence_card 供 adjudicator/minimal-repair 引用
json.dump({"assumption": assumption, "evidence_test": evidence_test,
           "bridge": bridge, "evidence_card": ev, "contract": contract},
          open("/tmp/p0033_a3_evidence.json", "w"), ensure_ascii=False, indent=1)
print("\n  → /tmp/p0033_a3_evidence.json")
