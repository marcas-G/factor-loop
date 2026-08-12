"""Investigation DSL —— 通用实验动作(非 Operator DSL)。

第一版动作: FILTER / MATCH / STRATIFY / HOLD_FIXED / VARY / COMPARE / LAG / REPORT
probe_compiler 把 Contract 编译成这些动作的序列。动作是确定性原语,不是 LLM。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProbeStep:
    action: str          # FILTER/MATCH/STRATIFY/HOLD_FIXED/VARY/COMPARE/LAG/REPORT
    params: dict = field(default_factory=dict)


# 动作语义(供 designer/compiler 对齐)
ACTIONS = {
    "FILTER": "选 symbol/horizon/时间范围(列级过滤)",
    "MATCH": "按某坐标匹配(如 product 在容差内),构造对照样本",
    "STRATIFY": "按某坐标分位分层(gate/signal/幅值),每层独立比较",
    "HOLD_FIXED": "控制混杂(波动率/价差/regime)——分位匹配或残差化",
    "VARY": "声明实验维度的变化范围(匹配后自然变异的坐标)",
    "COMPARE": "组间行为对比(条件均值/方向命中率/分位数)",
    "LAG": "引入滞后(未来收益 @h 已是内置 Y;LAG 用于时序路径变量)",
    "REPORT": "汇总证据(效应方向/大小/不确定性/稳定性)",
}

# 可用的 Y 行为指标(全来自 .xy 内置 Y 列)
Y_BEHAVIORS = ["future_return@h", "return_sign_hit_rate", "abs_future_return"]
