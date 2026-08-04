#!/usr/bin/env python3
"""问题注册表 builder：272 因子 → 规范化测量问题空间（问题族）。

用途：概念批评器的"问题级去重"前置。每个候选概念回答的问题必须与
注册表已有问题比较（measured_object + question_form + reference_frame
+ temporal_form + output_form 五元组），去重不受措辞影响。

结构：
  1. 程序化聚类：按因子名词根把 272 因子归入问题族（族 = 一个测量问题）
  2. LLM 批注：每族生成规范化问题记录（registry_annotate_prompt() 输出提示词）
  3. 输出：question_registry.json（待批注模板 + 已批注记录）

输出字段（每族一条）：
  question_id / family / measurement_question / measured_object /
  question_form / input_roles / reference_frame / temporal_form /
  output_form / known_factors / structural_tags
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "factor_db"))
from db import get_conn  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "concept_cards" / "question_registry.json"

# ---------------------------------------------------------------- 问题族词根映射
# 因子名词根 → 测量问题族。272 因子按此归族；未匹配进 "OTHER_<词根>" 待人工归。
FAMILY_PATTERNS = [
    (r"Imbalance|Imb", "盘口不平衡"),
    (r"Ofi|OFI|OrderFlow", "订单流失衡(OFI)"),
    (r"Cancel", "撤单行为"),
    (r"Spread", "价差/报价间隙"),
    (r"OiLift|OILift|AddOiLift|NdiffOi|DeltaRatioOi|AbsdiffOi|RankOI|OIBuildup|OIPersist|OISpike|OITail|OiShock|OiChange|OiSkew|Xndiff", "持仓增量(OI)行为"),
    (r"Kyle|BookBeta|Book_Beta", "价格冲击弹性(Kyle lambda)"),
    (r"Vpin|VPIN", "成交毒性(VPIN)"),
    (r"Opening|Auction|Fulfill", "开盘/集合竞价"),
    (r"NearFar", "远近档位结构"),
    (r"Turnover|TradeFlow|TradeImb|RankTradeFlow|TradeDensity|SectorTrade|TradeFreq", "成交流/换手"),
    (r"Depth|BookImbalance|RawBookImb|Bsi|BidAskSlope|BPI|BPSkew|BpSkew|BpKurt|BookShape|BookPressure|BookCrowd|DeepLevel|SectorOiCouple", "盘口深度/形状"),
    (r"PostImpact|LargeOrder|Breach|TickPressure|CloseMatch|MatchSpeed", "大单冲击/穿透"),
    (r"Flicker|Spoof|LiquidityThin|ThinBook", "闪撤/伪装/薄盘"),
    (r"CrossMonth|CrossPrev|CrossFeed|CrossLevel|CrossKyle|CrossProduct|CrossSymbol|CrossAsset|Xsector|SectorOi", "跨合约/跨feed/跨品种"),
    (r"MidReversal|MidAR|ExtremeSpread|ExtremeTrade|ExtremeCross|FreqBurst|FreqClimax|FreqBurst", "极端/反转"),
    (r"Volume|VolGate|VolRegime|VolPressure|CausalQuantile|QuantileVol", "波动率状态"),
    (r"AddOiLift|RegimeFlow|NightCross|NightRisk", "持仓/夜间联动"),
    (r"ShockAbsorption", "冲击-响应-恢复"),
]


def family_of(name):
    for pat, fam in FAMILY_PATTERNS:
        if re.search(pat, name):
            return fam
    return None


def cluster(rows):
    """rows: [(xname, formula_text, intuition)] → {family: [factors]}"""
    fams = defaultdict(list)
    for xname, formula, intuition in rows:
        fam = family_of(xname)
        if fam is None:
            # 未匹配：用首词根兜底
            m = re.match(r"[A-Za-z]+", xname)
            fam = f"OTHER_{m.group(0) if m else '?'}"
        fams[fam].append(xname)
    return fams


def build_template(conn):
    """生成批注模板：每族一条待批注记录（已知字段已填，六元组待 LLM 批注）。"""
    rows = conn.execute("""
        SELECT DISTINCT f.xname, f.formula_text, f.intuition FROM factors f
        WHERE EXISTS (SELECT 1 FROM factor_ic_daily d WHERE d.factor_xname=f.xname)
    """).fetchall()
    fams = cluster(rows)
    # 每族聚合 formula 片段供批注参考（拼接前 2 个因子的公式）
    fam_formula = defaultdict(list)
    fam_factors = defaultdict(list)
    for xname, formula, intuition in rows:
        fam = family_of(xname) or f"OTHER_{re.match(r'[A-Za-z]+', xname).group(0)}"
        fam_factors[fam].append(xname)
        if formula:
            fam_formula[fam].append(formula[:200])

    registry = []
    for i, (fam, factors) in enumerate(sorted(fams.items(), key=lambda kv: -len(kv[1]))):
        registry.append({
            "question_id": f"Q_{i:03d}",
            "family": fam,
            "known_factors": sorted(factors),
            "n_factors": len(factors),
            "formula_snippet": " || ".join(fam_formula.get(fam, []))[:400],
            "measurement_question": "",      # LLM 批注
            "measured_object": "",           # LLM 批注
            "question_form": "",             # LLM 批注
            "input_roles": [],               # LLM 批注
            "reference_frame": "",           # LLM 批注
            "temporal_form": "",             # LLM 批注
            "output_form": "",               # LLM 批注
            "structural_tags": [],           # LLM 批注
        })
    return registry


def annotate_prompt(registry, k=10):
    """批量批注提示词：一次处理 k 族。输出要求（JSON）。"""
    return f"""你是量化因子研究的问题空间标注器。把以下 {min(k, len(registry))} 个"测量问题族"规范化成六元组。

背景：问题注册表用于概念批评器去重——判断一个新提出的测量问题是否已被已有因子问过。
去重不比较文本，比较结构：measured_object + question_form + reference_frame + temporal_form + output_form。

六元组定义：
- measurement_question: 该族测量问题的一句话（动词开头，如"测量方向性订单流净输入有多强"）
- measured_object: 测量对象（如 directional_flow / book_imbalance / cancel_rate / price_impact_elasticity / depth_recovery_speed / oi_change ...）
- question_form: 问题形式（STATE_MAGNITUDE 当前大小 / DELTA_CHANGE 变化量 / TREND 趋势 / EXTREME 极值 / CROSS_DIFF 两侧差 / RATIO 比率 / CONFIRM 交叉确认 / PRECURSOR 前兆 / RECOVERY 恢复 / ASYMMETRY 不对称）
- input_roles: 输入角色列表（如 [side_1_flow, side_2_flow] / [depth, price] / [oi, price] ...）
- reference_frame: 参照系（contemporaneous_difference 同时差 / capacity_normalized 容量归一化 / zscore 滚动标准化 / cross_feed 跨feed / cross_contract 跨合约 / historical_baseline 历史基准 ...）
- temporal_form: 时间形式（fixed_clock_window 固定窗口 / event_window 事件窗口 / snapshot 快照 / lead_lag 领先滞后 / multi_horizon 多horizon / rolling_rank 滚动分位 ...）
- output_form: 输出形式（signed_scalar 带符号标量 / unsigned_magnitude 无符号量 / probability / rank_percentile / sparse_gate 稀疏门控 ...）
- structural_tags: 结构标签（如 flow / depth / price / oi / cancel / spread / trade / recovery / gate / reversal / momentum ...）

输入族（每族含 known_factors 和 formula_snippet 供推断）：

{json.dumps(registry[:k], ensure_ascii=False, indent=1)}

输出：只输出 JSON 数组，每族一条，字段同输入（question_id + 六元组 + structural_tags 填好，known_factors/formula_snippet 原样保留）。不要输出其他文字。"""


def main():
    with get_conn() as conn:
        registry = build_template(conn)
    OUT.write_text(json.dumps(registry, ensure_ascii=False, indent=1))
    from collections import Counter
    fams = Counter(r["family"] for r in registry)
    total = sum(r["n_factors"] for r in registry)
    print(f"问题族: {len(registry)} 个, 覆盖因子 {total}/272")
    print("=== 族分布 (按因子数) ===")
    for fam, n in fams.most_common(20):
        factors = [r for r in registry if r["family"] == fam][0]["n_factors"]
        print(f"  {fam:<18} {factors} 因子")
    print(f"\n→ {OUT}")
    print("\n=== 批注提示词预览 (前 2 族) ===")
    print(annotate_prompt(registry[:2], k=2)[-800:])


if __name__ == "__main__":
    main()
