#!/usr/bin/env python3
"""因子标签的连带检查（规则化，不靠 LLM）。

变换产出新标签后，跑 check_coupling 检查自洽性：
- 条件连带（R1-R8）：A 取某值 → B 必须非 null
- 一致连带（R9）：A 变 → B 同步（自动修正或拒绝）

基于结构化标签（26 维度当前取值），程序化执行。
"""
from typing import Any


# ============ AddOiLiftBidAsk 标签（测试用）============
ADD_OI_LIFT_BIDASK = {
    "字段": [
        {"name": "bid_size", "type": "向量"},
        {"name": "ask_size", "type": "向量"},
        {"name": "oi", "type": "标量"},
    ],
    "档位选择": "L0最优档",
    "聚合运算": None,
    "加权": None,
    "数据源": "单合约",
    "差分": "一阶差分",
    "标准化方法": "z-score",
    "标准化估计": "滚动窗固定N",
    "平滑": None,
    "触发类型": "spike阈值",
    "spike方向": "单侧正≥θ",
    "阈值类型": "z-score",
    "关系类型": "条件概率lift",
    "共现条件": {"bid侧": "同向", "ask侧": "反向"},
    "lead-lag τ方式": None,
    "相关类型": None,
    "lift统计": "概率比",
    "组合运算": "差",
    "加权权重": None,
    "输出变换": "tanh",
    "输出门控": "事件门控",
    "对齐粒度": None,
    "stale策略": None,
    "对齐方向": None,
    "参数": {"Win": 200, "Theta": 2.0, "Gain": 5},
    "DAG拓扑": {
        "分支数": 2,
        "对称性": "对称",
        "各路角色": ["bid路", "ask路"],
        "辅助输入": ["oi（共现伙伴）"],
        "合并点": "末期（lift_bid - lift_ask）",
    },
}


# CrossMonthImbRelDiff 标签（跨合约，测试用）
CROSS_MONTH_IMB = {
    "字段": [
        {"name": "bid_size", "type": "向量"},
        {"name": "ask_size", "type": "向量"},
    ],
    "档位选择": "L0最优档",
    "聚合运算": None,
    "加权": None,
    "数据源": "跨合约main↔sub",
    "差分": None,
    "标准化方法": None,
    "标准化估计": None,
    "平滑": "EMA",
    "触发类型": None,
    "spike方向": None,
    "阈值类型": None,
    "关系类型": "代数差",
    "共现条件": None,
    "lead-lag τ方式": None,
    "相关类型": None,
    "lift统计": None,
    "组合运算": None,
    "加权权重": None,
    "输出变换": "tanh",
    "输出门控": None,
    "对齐粒度": "tick级",
    "stale策略": "接受stale peer",
    "对齐方向": "main等peer",
    "参数": {"Decay": 0.9, "Gain": 5},
    "DAG拓扑": {
        "分支数": 2,
        "对称性": "对称",
        "各路角色": ["main路", "sub路"],
        "辅助输入": [],
        "合并点": "中期（imbalance差）",
    },
}


# CounterpartyFillingAsymmetry 标签（单路 size 差分, dead_end ICIR-3.5）
COUNTERPARTY_FILLING = {
    "字段": [
        {"name": "bid_size", "type": "向量"},
        {"name": "ask_size", "type": "向量"},
    ],
    "档位选择": "L0最优档",
    "聚合运算": None,
    "加权": None,
    "数据源": "单合约",
    "差分": "一阶差分",
    "标准化方法": None,
    "标准化估计": None,
    "平滑": "EMA",
    "触发类型": None,
    "spike方向": None,
    "阈值类型": None,
    "关系类型": "代数差",
    "共现条件": None,
    "lead-lag τ方式": None,
    "相关类型": None,
    "lift统计": None,
    "组合运算": None,
    "加权权重": None,
    "输出变换": "tanh",
    "输出门控": None,
    "对齐粒度": None,
    "stale策略": None,
    "对齐方向": None,
    "参数": {"Decay": 0.9},
    "DAG拓扑": {
        "分支数": 1, "对称性": "对称", "各路角色": ["单路"], "辅助输入": [], "合并点": "无（单路）",
    },
}


# OIPersistPriceConfirm 标签（oi×price 耦合, dead_end ICIR1.64）
OI_PERSIST_PRICE = {
    "字段": [
        {"name": "oi", "type": "标量"},
        {"name": "mid_price", "type": "标量"},
    ],
    "档位选择": None,
    "聚合运算": None,
    "加权": None,
    "数据源": "单合约",
    "差分": "一阶差分",
    "标准化方法": None,
    "标准化估计": None,
    "平滑": "Hold累积",
    "触发类型": None,
    "spike方向": None,
    "阈值类型": None,
    "关系类型": "代数积",
    "共现条件": None,
    "lead-lag τ方式": None,
    "相关类型": None,
    "lift统计": None,
    "组合运算": None,
    "加权权重": None,
    "输出变换": "percentile_rank",
    "输出门控": None,
    "对齐粒度": None,
    "stale策略": None,
    "对齐方向": None,
    "参数": {"OIWin": 20, "RetWin": 20, "RankWin": 500},
    "DAG拓扑": {
        "分支数": 2, "对称性": "不对称",
        "各路角色": ["oi路(持续性)", "price路(方向)"],
        "辅助输入": [],
        "合并点": "中期（consistency × price_dir）",
    },
}


# 父因子池: 变换引擎从这里随机选父因子（保证多样性）
# 4 种不同类型: 双路共现lift / 跨合约差 / 单路size差分 / oi×price耦合
PARENT_POOL = {
    "AddOiLiftBidAsk": {**ADD_OI_LIFT_BIDASK, "_dead_end_reason": None},            # evaluated pass
    "CrossMonthImbRelDiff": {**CROSS_MONTH_IMB, "_dead_end_reason": None},          # evaluated pass
    "CounterpartyFillingAsymmetry": {**COUNTERPARTY_FILLING, "_dead_end_reason": "饱和族冗余"},  # lesson260 pearson0.74-0.97 vs RawBookImbalanceRatio
    "OIPersistPriceConfirm": {**OI_PERSIST_PRICE, "_dead_end_reason": "IC弱/冗余"},  # IC0.043弱 + oi族saturated
}


def check_coupling(label: dict) -> list[tuple[str, str]]:
    """检查标签的连带自洽性。返回违反的规则列表 [(规则id, 描述)]。"""
    violations = []

    def is_null(v):
        return v is None or v == "" or v == []

    # R1: 字段数≥2 → 关系类型非 null
    if len(label.get("字段", [])) >= 2 and is_null(label.get("关系类型")):
        violations.append(("R1", "字段≥2 但关系类型 null（多字段需关系定义）"))

    # R2: 字段含向量 → 档位选择非 null
    fields = label.get("字段", [])
    if isinstance(fields, list) and fields:
        has_vector = any(
            (f.get("type") == "向量") if isinstance(f, dict) else False
            for f in fields
        )
        if has_vector and is_null(label.get("档位选择")):
            violations.append(("R2", "字段含向量 但档位选择 null（向量字段需选档位）"))

    # R3: 数据源跨feed → 对齐维度非 null
    source = label.get("数据源", "") or ""
    if "跨" in source:
        for dim in ["对齐粒度", "stale策略", "对齐方向"]:
            if is_null(label.get(dim)):
                violations.append((f"R3", f"数据源跨feed({source}) 但 {dim} null"))

    # R4: 标准化 z-score → 估计方式非 null
    norm = label.get("标准化方法") or ""
    if "z-score" in norm and is_null(label.get("标准化估计")):
        violations.append(("R4", "标准化z-score 但估计方式 null"))

    # R5: 触发 spike → spike方向 + 阈值类型非 null
    trig = label.get("触发类型") or ""
    if "spike" in trig:
        if is_null(label.get("spike方向")):
            violations.append(("R5", "触发spike 但spike方向 null"))
        if is_null(label.get("阈值类型")):
            violations.append(("R5", "触发spike 但阈值类型 null"))

    # R6: 关系类型 → 对应子方式非 null（lift 是共现类, 含共现条件+lift统计）
    rel = label.get("关系类型") or ""
    rel_sub_map = {
        "共现": ["共现条件"],
        "lift": ["共现条件", "lift统计"],
        "lead-lag": ["lead-lag τ方式"],
        "相关": ["相关类型"],
    }
    for rel_key, subs in rel_sub_map.items():
        if rel_key in rel:
            for sub in subs:
                if is_null(label.get(sub)):
                    violations.append(("R6", f"关系含'{rel_key}' 但 {sub} null"))

    # R7: 组合加权 → 加权权重非 null
    comb = label.get("组合运算") or ""
    if comb == "加权" and is_null(label.get("加权权重")):
        violations.append(("R7", "组合运算=加权 但加权权重 null"))

    # R8: 输出事件门控 → 触发类型非 null
    gate = label.get("输出门控") or ""
    if "事件" in gate and is_null(label.get("触发类型")):
        violations.append(("R8", "输出门控=事件门控 但触发类型 null"))

    return violations


def auto_fix_coupling(label: dict) -> tuple[dict, list[str]]:
    """一致连带（R9）：A 变 → B 同步自动修正。返回(修正后标签, 修正记录)。"""
    fixed = dict(label)
    fixes = []

    def is_null(v):
        return v is None or v == "" or v == []

    # R9c: 字段全标量 → 档位选择 null（向量才需档位）
    fields = fixed.get("字段", [])
    if isinstance(fields, list) and fields:
        has_vector = any(
            (f.get("type") == "向量") if isinstance(f, dict) else False
            for f in fields
        )
        if not has_vector and not is_null(fixed.get("档位选择")):
            fixed["档位选择"] = None
            fixes.append("R9c: 字段全标量 → 档位选择 null")

        if has_vector and is_null(fixed.get("档位选择")):
            fixed["档位选择"] = "L0最优档"
            fixes.append("R9c: 字段含向量 → 档位选择 L0（默认）")

    # R9d: 数据源单→跨 → 对齐默认；跨→单 → 对齐 null
    source = fixed.get("数据源", "") or ""
    if "跨" in source:
        defaults = {"对齐粒度": "tick级", "stale策略": "接受stale peer", "对齐方向": "main等peer"}
        for dim, default in defaults.items():
            if is_null(fixed.get(dim)):
                fixed[dim] = default
                fixes.append(f"R9d: 数据源跨feed → {dim}={default}（默认）")
    else:
        for dim in ["对齐粒度", "stale策略", "对齐方向"]:
            if not is_null(fixed.get(dim)):
                fixed[dim] = None
                fixes.append(f"R9d: 数据源单合约 → {dim} null")

    # R9e: 触发非spike → spike方向/阈值类型 null
    trig = fixed.get("触发类型") or ""
    if "spike" not in trig and not is_null(trig):
        for dim in ["spike方向", "阈值类型"]:
            if not is_null(fixed.get(dim)):
                fixed[dim] = None
                fixes.append(f"R9e: 触发非spike → {dim} null")

    # R6: 关系类型 → 子方式（清非当前子方式 + 当前子方式设默认）
    # 注意: lift 是共现类, 子方式含 共现条件 + lift统计
    rel = fixed.get("关系类型") or ""
    rel_sub_map = {
        "共现": ["共现条件"],
        "lift": ["共现条件", "lift统计"],
        "lead-lag": ["lead-lag τ方式"],
        "相关": ["相关类型"],
    }
    sub_defaults = {
        "共现条件": "同号", "lift统计": "概率比",
        "lead-lag τ方式": "固定τ", "相关类型": "Pearson",
    }
    # 找当前关系类型对应的子方式集
    current_subs = []
    for rel_key, subs in rel_sub_map.items():
        if rel_key in rel:
            current_subs = subs
            break
    all_subs = ["共现条件", "lead-lag τ方式", "相关类型", "lift统计"]
    # 清非当前子方式（关系类型变了，旧子方式 null）
    for sub in all_subs:
        if sub not in current_subs and not is_null(fixed.get(sub)):
            fixed[sub] = None
            fixes.append(f"R6: 关系类型变化 → {sub} null（清旧子方式）")
    # 当前子方式设默认
    for sub in current_subs:
        if is_null(fixed.get(sub)):
            fixed[sub] = sub_defaults.get(sub)
            fixes.append(f"R6: 关系类型 → {sub}={sub_defaults.get(sub)}（默认）")

    # R7: 组合运算=加权 → 加权权重设默认; 非加权 → 加权权重 null
    comb = fixed.get("组合运算") or ""
    if comb == "加权" and is_null(fixed.get("加权权重")):
        fixed["加权权重"] = "固定"
        fixes.append("R7: 组合运算=加权 → 加权权重=固定（默认）")
    elif comb != "加权" and not is_null(fixed.get("加权权重")):
        fixed["加权权重"] = None
        fixes.append("R7: 组合运算非加权 → 加权权重 null")

    return fixed, fixes


# 参数敏感维度: 这些维度变化时, 参数（Theta/窗口/衰减）的语义/取值需重定
# 不是结构自洽问题（标签可标任何值）, 是语义不一致——参数依赖信号性质, 信号性质变参数要重定
PARAM_SENSITIVE = {
    "阈值类型": "Theta 阈值参数语义变（z-score 值 vs 绝对值 vs 分位, 量级完全不同）",
    "标准化方法": "标准化相关参数（窗口等）可能需重定",
    "标准化估计": "窗口/衰减参数语义变（滚动窗大小 vs EMA 衰减系数）",
    "触发类型": "Theta 阈值参数适用性变（spike 用阈值, 其他触发可能不用）",
    "差分": "信号量级变（差分/比值/log 量级不同）, 阈值参数需重定",
    "档位选择": "聚合后量级变（单档 vs 多档聚合量级不同）, 阈值参数需重定",
    "聚合运算": "聚合后量级变（sum/mean/max 量级不同）, 阈值参数需重定",
    "字段": "字段量级变（bid_size vs oi vs volume 量级不同）, 阈值参数需重定",
}


def param_coupling_hints(old_label: dict, new_label: dict) -> list[str]:
    """变换后, 检查哪些参数因维度变化需重定。返回提示列表。

    这些维度变化时, 参数（Theta/窗口/衰减）的语义/取值依赖信号性质,
    信号性质变了参数要重定。不是结构自洽检查（R1-R8）, 是语义提示。
    """
    hints = []
    for dim, desc in PARAM_SENSITIVE.items():
        old_v = old_label.get(dim)
        new_v = new_label.get(dim)
        if old_v != new_v:
            hints.append(f"参数连带[{dim}]: {old_v} → {new_v}; {desc}")
    return hints


if __name__ == "__main__":
    # 测试 AddOiLiftBidAsk
    print("=" * 60)
    print("测试 AddOiLiftBidAsk")
    print("=" * 60)
    v = check_coupling(ADD_OI_LIFT_BIDASK)
    if not v:
        print("✓ 通过所有连带检查（标签自洽）")
    else:
        print(f"✗ {len(v)} 处违反:")
        for rid, desc in v:
            print(f"  [{rid}] {desc}")

    print()
    print("=" * 60)
    print("测试 CrossMonthImbRelDiff")
    print("=" * 60)
    v = check_coupling(CROSS_MONTH_IMB)
    if not v:
        print("✓ 通过所有连带检查（标签自洽）")
    else:
        print(f"✗ {len(v)} 处违反:")
        for rid, desc in v:
            print(f"  [{rid}] {desc}")

    # 测试变换后的连带违反 + 自动修正
    print()
    print("=" * 60)
    print("测试变换后连带违反 + 自动修正")
    print("=" * 60)
    # 模拟变换：AddOiLiftBidAsk 数据源 单合约→跨合约，但不加对齐
    broken = dict(ADD_OI_LIFT_BIDASK)
    broken["数据源"] = "跨合约main↔sub"
    # 故意不加对齐维度（模拟变换漏了连带）
    print("变换: 数据源 单合约→跨合约（漏加对齐）")
    v = check_coupling(broken)
    print(f"检查发现 {len(v)} 处违反:")
    for rid, desc in v:
        print(f"  [{rid}] {desc}")
    print()
    fixed, fixes = auto_fix_coupling(broken)
    print(f"自动修正 {len(fixes)} 处:")
    for f in fixes:
        print(f"  {f}")
    print()
    v2 = check_coupling(fixed)
    print(f"修正后检查: {'✓ 通过' if not v2 else f'✗ 仍有 {len(v2)} 处违反'}")
