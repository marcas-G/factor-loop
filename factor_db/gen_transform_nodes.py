#!/usr/bin/env python3
"""生成变换节点库 JSON（模板版）。

每维度一个模板节点（含取值域 + 操作类型），不展开 A→B 对。
LLM 读因子描述，按模板填参（当前值→新值），生成变换指令。

比具体节点版轻量：866 具体节点 → ~26 模板节点（每维度一个）。
取值域完备性不变（取值域完整列出，LLM 从中选）。
"""
import json
from pathlib import Path

# 维度定义：每维度 = 取值域 + 操作类型 + 连带提示
# 操作类型：
#   swap       - 换值（当前值 → 取值域中另一个）
#   add_remove - 启用/禁用（有"无"状态：无 ↔ 取值域中某值）
#   both       - 既能换值也能启用/禁用
#   special    - 特殊（参数/拓扑/对齐，单独定义操作）
DIMENSIONS = [
    # ============ 1. 输入层 ============
    {
        "dimension": "字段",
        "type": "swap",
        "values": ["add", "cancel", "oi", "volume", "bid_size", "ask_size", "mid_price", "spread", "depth", "turnover"],
        "coupling_hint": "若该字段是多字段操作的一方，关系/对齐可能需相应调整",
    },
    {
        "dimension": "档位选择",
        "type": "swap",
        "values": ["L0最优档", "L1", "L2", "Lk深层档", "浅档[0..K]", "深档[K..]", "全档[0..N]", "自适应边界K"],
        "coupling_hint": "单档↔多档聚合切换时，聚合运算维度需相应启用/禁用",
    },
    {
        "dimension": "聚合运算",
        "type": "swap",
        "values": ["sum", "mean", "max", "min", "median", "percentile", "std", "skew", "kurtosis", "HHI集中度", "熵"],
    },
    {
        "dimension": "加权",
        "type": "swap",
        "values": ["线性衰减", "指数衰减", "等权", "HHI集中度", "熵", "自定义"],
    },
    {
        "dimension": "数据源",
        "type": "swap",
        "values": ["单合约", "跨合约main↔sub", "跨合约main↔prev", "跨品种同板块", "跨品种异板块", "指定品种对"],
        "coupling_hint": "单→跨feed时，时间对齐维度需启用（stale策略等）",
    },
    # ============ 2. 预处理层 ============
    {
        "dimension": "差分",
        "type": "both",
        "values": ["一阶差分", "二阶差分", "n阶差分", "比值", "对数比值", "log变换", "符号sign", "绝对值"],
    },
    {
        "dimension": "标准化方法",
        "type": "both",
        "values": ["z-score", "robust z(中位数+MAD)", "rank", "分位变换", "box-cox", "min-max", "winsorize"],
        "coupling_hint": "切到z-score类时，估计方式维度需启用",
    },
    {
        "dimension": "标准化估计",
        "type": "swap",
        "values": ["滚动窗固定N", "扩展窗", "EMA指数加权", "全样本"],
        "applicability": "只在标准化方法=z-score类时适用",
    },
    {
        "dimension": "平滑",
        "type": "both",
        "values": ["SMA简单移动平均", "WMA加权移动平均", "EMA", "Hold累积", "中值滤波"],
    },
    # ============ 3. 触发层 ============
    {
        "dimension": "触发类型",
        "type": "both",
        "values": ["spike阈值", "符号切换", "零穿越", "分位极端", "regime波动", "regime流动性", "regime时段", "序列pattern连续N次"],
        "coupling_hint": "触发类型切到spike时，spike方向+阈值类型维度需启用",
    },
    {
        "dimension": "spike方向",
        "type": "swap",
        "values": ["单侧正≥θ", "单侧负≤-θ", "双侧|x|≥θ", "符号切换"],
        "applicability": "只在触发类型=spike时适用",
    },
    {
        "dimension": "阈值类型",
        "type": "swap",
        "values": ["绝对值", "z-score", "分位", "滚动quantile"],
    },
    # ============ 4. 关系层（多字段） ============
    {
        "dimension": "关系类型",
        "type": "both",
        "values": ["共现", "lead-lag", "相关", "条件概率lift", "代数比值", "代数差", "代数积"],
        "coupling_hint": "关系类型变化时，对应子方式维度需相应调整",
    },
    {
        "dimension": "共现条件",
        "type": "swap",
        "values": ["同号", "异号", "同向", "阈值共现"],
        "applicability": "只在关系类型=共现时适用",
    },
    {
        "dimension": "lead-lag τ方式",
        "type": "swap",
        "values": ["固定τ", "扫描最优argmax", "互相关谱", "多τ加权"],
        "applicability": "只在关系类型=lead-lag时适用",
    },
    {
        "dimension": "相关类型",
        "type": "swap",
        "values": ["Pearson", "Spearman", "Kendall", "符号相关"],
        "applicability": "只在关系类型=相关时适用",
    },
    {
        "dimension": "lift统计",
        "type": "swap",
        "values": ["count", "概率比", "PMI", "条件概率"],
        "applicability": "只在关系类型=lift时适用",
    },
    # ============ 5. 组合层（多信号） ============
    {
        "dimension": "组合运算",
        "type": "swap",
        "values": ["差", "和", "积", "比", "加权", "max", "min", "AND逻辑", "OR逻辑"],
        "coupling_hint": "组合运算切到加权时，加权权重维度需启用",
    },
    {
        "dimension": "加权权重",
        "type": "swap",
        "values": ["固定", "自适应", "softmax"],
        "applicability": "只在组合运算=加权时适用",
    },
    # ============ 6. 输出层 ============
    {
        "dimension": "输出变换",
        "type": "both",
        "values": ["tanh", "sigmoid", "rank", "percentile_rank", "z-score", "clip截断", "winsorize截尾", "二值化", "分桶"],
    },
    {
        "dimension": "输出门控",
        "type": "both",
        "values": ["事件门控", "regime门控"],
        "coupling_hint": "事件门控需要有触发定义（触发类型维度）",
    },
    # ============ 7. 时间对齐（跨 feed） ============
    {
        "dimension": "对齐粒度",
        "type": "swap",
        "values": ["tick级同tick", "时间窗内Nms最近", "插值"],
        "applicability": "只在跨feed时适用",
    },
    {
        "dimension": "stale策略",
        "type": "both",
        "values": ["接受stale peer", "拒绝出0", "降权"],
        "applicability": "只在跨feed时适用",
    },
    {
        "dimension": "对齐方向",
        "type": "swap",
        "values": ["main等peer", "peer等main", "双向"],
        "applicability": "只在跨feed时适用",
    },
]

# ============ 8. 特殊维度（参数/DAG拓扑）============
SPECIAL = [
    {
        "dimension": "参数",
        "type": "special",
        "operations": [
            "把窗口调大（如200→500）",
            "把窗口调小（如500→200）",
            "把阈值调低（如2.0→1.5）",
            "把阈值调高（如1.5→2.0）",
            "把衰减调慢（如0.9→0.95）",
            "把衰减调快（如0.95→0.9）",
            "把增益调大",
            "把增益调小",
            "把分位调极端（如0.9→0.95）",
            "把分位调中性（如0.95→0.9）",
        ],
        "applicability": "当前有对应参数",
    },
    {
        "dimension": "DAG拓扑",
        "type": "special",
        "operations": [
            "把单路改成双路bid/ask分路",
            "把单路改成双路main/sub分路",
            "把双路改成多路三路以上",
            "把双路改回单路",
            "把多路改回双路",
            "把对称双路改成不对称两路不同操作",
            "把不对称改成对称两路相同操作",
            "把合并点从末期改到中期信号匹配处",
            "把合并点从中期改到早期字段对齐处",
            "把合并点从早期改到末期输出组合处",
            "调换两步操作的顺序（如平滑与标准化互换）",
            "在预处理加一步操作",
            "去掉某步预处理操作",
        ],
        "coupling_hint": "结构变换需保证DAG完整性（新分支有操作、合并点合法）",
    },
]


def build_template_node(dim_def, idx):
    """构建一个模板节点。"""
    node = {
        "id": f"tpl{idx:02d}",
        "dimension": dim_def["dimension"],
        "type": dim_def["type"],
    }
    if dim_def["type"] in ("swap", "both", "add_remove"):
        node["values"] = dim_def["values"]
    if dim_def["type"] == "special":
        node["operations"] = dim_def["operations"]
    # 操作模板（LLM 填参用）
    if dim_def["type"] == "swap":
        node["operation_templates"] = {
            "换值": "把{dimension}从 {当前值} 换成 {新值}",
        }
    elif dim_def["type"] == "add_remove":
        node["operation_templates"] = {
            "启用": "启用 {新值}（{dimension}）",
            "禁用": "去掉当前的{dimension}",
        }
    elif dim_def["type"] == "both":
        node["operation_templates"] = {
            "换值": "把{dimension}从 {当前值} 换成 {新值}",
            "启用": "启用 {新值}（{dimension}）",
            "禁用": "去掉当前的{dimension}",
        }
    elif dim_def["type"] == "special":
        node["operation_templates"] = {
            "执行": "{operation}",
        }
    if "coupling_hint" in dim_def:
        node["coupling_hint"] = dim_def["coupling_hint"]
    if "applicability" in dim_def:
        node["applicability"] = dim_def["applicability"]
    return node


# 构建所有模板节点
nodes = []
for i, dim_def in enumerate(DIMENSIONS, 1):
    nodes.append(build_template_node(dim_def, i))
for i, dim_def in enumerate(SPECIAL, len(DIMENSIONS) + 1):
    nodes.append(build_template_node(dim_def, i))

# 统计取值域总规模（参考）
total_values = sum(len(n.get("values", [])) for n in nodes if n["type"] in ("swap", "both", "add_remove"))
total_special_ops = sum(len(n.get("operations", [])) for n in nodes if n["type"] == "special")

out = {
    "version": "2.0-template",
    "description": "变换节点库（模板版）：每维度一个模板节点 + 取值域。LLM 读因子描述，按模板填参（当前值→新值）生成变换指令。比具体节点版轻量（866→模板数）。",
    "node_structure": {
        "id": "模板节点标识",
        "dimension": "所属维度",
        "type": "操作类型（swap换值 / add_remove启用禁用 / both两者皆可 / special特殊）",
        "values": "取值域（swap/add_remove/both 类型有，LLM 从中选新值）",
        "operations": "操作列表（special 类型有，参数/拓扑/对齐的具体操作）",
        "operation_templates": "变换指令模板（LLM 填参用）",
        "coupling_hint": "连带提示（可选）",
        "applicability": "适用前提（可选，如'只在跨feed时适用'）",
    },
    "usage": {
        "step1": "LLM 读因子描述，判断每个模板节点是否适用（看 applicability + 因子是否有该维度）",
        "step2": "对适用的节点，LLM 提取当前值（从因子描述），从 values 选新值",
        "step3": "填 operation_templates，生成变换指令",
        "step4": "随机选一组变换指令（路径），LLM 按指令改写因子描述",
    },
    "total_template_nodes": len(nodes),
    "total_values_across_dimensions": total_values,
    "total_special_operations": total_special_ops,
    "equivalent_concrete_nodes": "约 866（若展开所有 A→B 对）",
    "nodes": nodes,
}

out_path = Path(__file__).parent / "transform_nodes.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"生成 {len(nodes)} 个模板节点 → {out_path}")
print(f"覆盖取值域: {total_values} 个取值 + {total_special_ops} 个特殊操作")
print(f"等价具体节点: ~866（模板版不展开，按需填参）")
print()
print("模板节点列表:")
for n in nodes:
    vals = n.get("values", n.get("operations", []))
    print(f"  [{n['type']:11s}] {n['dimension']:18s} ({len(vals)} 取值/操作)")
