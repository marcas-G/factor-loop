#!/usr/bin/env python3
"""Assumption → Evidence Query Compiler (Factor-centric, P003.1)。

把 Factor 的 construction assumption 翻译成可执行的 evidence_query:
  assumption{held_equal_coordinates, collapsed_difference}
    → contract(v1 schema) + bindings{坐标: 缓存代理因子}

这是 Research Instrument(临时调查), 不是 Measurement Operator。
evidence_card / probe 结果绝不进 operator registry。

四类 Evidence Query primitive(用户设计), 映射到 v1 probe_dsl:
  - CONDITIONAL_SLICE     固定 F, 变 collapsed dim, 比 Y    → MATCH+STRATIFY+COMPARE
  - MATCHED_PAIR          找 F(A)≈F(B), z_A≠z_B, 比 B       → MATCH+COMPARE
  - CONDITIONAL_TRAJECTORY 固定 F(t)=c, 变 history, 比后续    → LAG+MATCH+COMPARE
  - CONTROLLED_SIBLING    单变量变体因子对比                  → load_multi+COMPARE

dry-run 程序版: 规则映射(collapsed_dim → 代理因子注册表)。
后续可换 LLM agent (cog-evidence-query-designer) 选 primitive。
"""
try:
    from .investigation import probe_compiler, evidence_card, xycache
except ImportError:
    import sys
    sys.path.insert(0, __file__.rsplit("/cog_protocol/", 1)[0])
    from cog_protocol.investigation import probe_compiler, evidence_card, xycache

# collapsed_dim → 缓存代理因子(Explore 分类结果)
# None = 当前缓存无合适代理(scale/size/sign 需另写 raw 因子)
PROXY_REGISTRY = {
    "depth":  "BsiDepthWeightedImbalanceRank",   # 显式深档 (K-i 递减权重)
    "path":   "AddCancelPhaseCouplingAsym",       # add/cancel Lag 滞后相关
    "tempo":  "InventoryRebalanceDecaySpectrumRank",  # 双 EMA 衰减谱
    "regime": "FlickerSpikeThinBookRank",         # thin/thick book regime
    "feed":   None,   # feed 用 F 自身的 @1 列(xycache 已含 main/sub)
    "size":   None,   # 无 raw size 代理(20 因子全 log-ratio/rank 加工品)
    "sign":   None,
    "ratio":  None,
    "horizon": None,  # horizon 是 Y 列变化, 不需代理
}


def compile_query(assumption: dict, factor_xname: str, y_horizon: str = "1"):
    """assumption → (contract, bindings, missing_proxies)。

    assumption: {id, held_equal_coordinates:[...], collapsed_difference:[...], ...}
    factor_xname: F 的缓存名(有 .xy)
    返回: (contract dict, bindings {坐标:缓存因子}, missing [无代理的 collapsed dim])
    """
    collapsed = list(assumption.get("collapsed_difference", []))
    held = list(assumption.get("held_equal_coordinates", []))
    aid = assumption.get("id", "?")

    bindings = {factor_xname: factor_xname}  # F 自身 = match 坐标
    missing = []
    primitive = "CONDITIONAL_SLICE"
    for dim in collapsed:
        proxy = PROXY_REGISTRY.get(dim)
        if proxy:
            bindings[dim] = proxy
        elif dim == "horizon":
            continue  # horizon 走 Y 列, 不需代理
        else:
            missing.append(dim)

    # primitive 选取(规则版): path/tempo → TRAJECTORY, 其余 → SLICE
    if any(d in ("path", "tempo") for d in collapsed):
        primitive = "CONDITIONAL_TRAJECTORY"

    contract = {
        "test_id": f"EQ-{factor_xname}-{aid}",
        "research_object": factor_xname,
        "assumption_id": aid,
        "primitive": primitive,
        "challenged_equivalence": {
            "representation_equal_on": [factor_xname],  # 实现层:实际 match 的 df 列
            "collapsed_difference": collapsed,
            "held_equal_declared": held,  # 声明层:受控词汇(供 bridge_validator, 不进 probe)
        },
        "task_context": {
            "symbol": "SHFE-AG",
            "horizon": y_horizon,
            "target_behavior": f"future_return@{y_horizon}",
        },
        # 声明层:用受控词汇(bridge_validator 字面匹配 held_equal_coordinates)
        # match on factor_xname 是实现手段(F 编码 ratio → F 相同 ⇔ ratio 相同)
        "controls": {"must_hold_similar": held},
        "variation": {"dimensions_allowed_to_change": collapsed},
        "competing_predictions": {
            "H_collapse": {"unique_prediction": "若 F 的等价失效, Y 应随 collapsed 维度分位单调变化"},
            "H_partial": {"unique_prediction": "placeholder"},
            "H_confound": {"unique_prediction": "placeholder"},
            "H0": {"unique_prediction": "Y 不随 collapsed 维度变化(等价成立, F 压缩无害)"},
        },
        "required_observations": [f"Y by {d} quantile, F matched" for d in collapsed],
        "success_pattern": "Y 在 collapsed 分位间单调/显著差异 → 等价失效(CONTRADICTS 候选)",
        "failure_pattern": "Y 在 collapsed 分位间无差异 → 等价成立(CONSISTENT)",
        "confounders": [],
        "data_requirements": {"proxy_factors": bindings, "missing_proxies": missing},
    }
    return contract, bindings, missing


def execute_query(contract: dict, bindings: dict, days=None, y_horizon: str = "1"):
    """加载 .xy + probe_compiler 执行 + evidence_card。

    返回 {evidence_card, probe_result, n_days, factors_used}
    """
    factors_needed = sorted(set(bindings.values()))
    dfs = {f: xycache.load_days(f, days) for f in factors_needed}
    probe_result = probe_compiler.compile_and_run(contract, bindings, dfs, y_horizon=y_horizon)
    ev = evidence_card.build_evidence(probe_result, contract, observed_incompat_strength="DIRECT")
    return {
        "evidence_card": ev,
        "probe_result": probe_result,
        "n_total": probe_result.get("n_total"),
        "factors_used": factors_needed,
    }


if __name__ == "__main__":
    # 自检: F1 depth collapse assumption → query
    a = {
        "id": "depth_collapse",
        "held_equal_coordinates": ["ratio"],
        "collapsed_difference": ["depth"],
    }
    contract, bindings, missing = compile_query(a, "BsiSizeLevelBareRank")
    print("=== F1 depth collapse query ===")
    print(f"primitive: {contract['primitive']}")
    print(f"bindings: {bindings}")
    print(f"missing_proxies: {missing}")
    print(f"match_on: {contract['challenged_equivalence']['representation_equal_on']}")
    print(f"stratify: {contract['variation']['dimensions_allowed_to_change']}")

    print("\n=== F2 path collapse query ===")
    a2 = {"id": "path_collapse", "held_equal_coordinates": ["ratio"], "collapsed_difference": ["path"]}
    c2, b2, m2 = compile_query(a2, "BsiFirstDiffPrecursorRank")
    print(f"primitive: {c2['primitive']}")
    print(f"bindings: {b2}, missing: {m2}")

    print("\n=== scale assumption (无代理, 应 missing) ===")
    a3 = {"id": "scale", "held_equal_coordinates": ["ratio"], "collapsed_difference": ["size"]}
    c3, b3, m3 = compile_query(a3, "BsiSizeLevelBareRank")
    print(f"missing: {m3} (size 无 raw 代理)")
