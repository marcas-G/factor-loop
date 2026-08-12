"""信息角度元层:本体预填 + 因子标注 + 覆盖度。

让 graph-engine 感知"哪些信息角度饱和/未探索",自动换角度(不靠人喂)。

用法: python factor_db/seed_angles.py   # 建表+预填本体+标注因子+打印覆盖度
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.db import db

# 本体:数据→信息角度字典(基于 BookSnapshotInfo 46列字段族×提取结构枚举)
ANGLES = [
    dict(code="book_imbalance", name="盘口不平衡", field_family="size", extraction="截面差(bid-ask)",
         signal_target="方向", theory_axiom="profit_L3",
         description="bid/ask size差→方向(库内RawBook族饱和)"),
    dict(code="add_cancel_imbalance", name="加撤不平衡", field_family="add_cancel", extraction="截面差(bid-ask净流)",
         signal_target="方向", theory_axiom="profit_L3",
         description="ofi式加撤净流→方向(库内ofi族饱和)"),
    dict(code="depth_shape", name="深度形状", field_family="size", extraction="分布矩(档间熵/偏度/凹凸)",
         signal_target="流动性/冲击", theory_axiom="kyle_lambda",
         description="5档size分布形状→流动性/冲击(未探索)"),
    dict(code="depth_slope", name="深度斜率", field_family="size+price", extraction="截面差(价位-深度斜率)",
         signal_target="流动性/成本", theory_axiom=None, description="价位-深度斜率→成本"),
    dict(code="add_cancel_pattern", name="加撤模式/存活", field_family="add_cancel", extraction="时序存活(挂单存活/交替)",
         signal_target="意图/spoof", theory_axiom="profit_L1",
         description="加撤时序模式→真实意图/spoof指纹(未探索)"),
    dict(code="trade_rhythm", name="成交节奏", field_family="volume/turnover", extraction="时间聚类(爆发/Hawkes)",
         signal_target="信息冲击", theory_axiom="info_diffusion_monotone",
         description="成交爆发节奏→信息冲击(未探索)"),
    dict(code="trade_imbalance", name="成交不平衡", field_family="volume", extraction="截面方向代理",
         signal_target="方向", theory_axiom="profit_L3", description="成交方向代理→方向(部分RankTrade)"),
    dict(code="price_microstructure", name="价格微观", field_family="mid/last_trade", extraction="游程序列(跳跃/反转)",
         signal_target="状态/regime", theory_axiom="roll_bounce",
         description="价格游程→trend/reversal regime(部分Roll观测)"),
    dict(code="volatility_regime", name="波动regime", field_family="mid", extraction="水平动量(滚动std分位)",
         signal_target="状态", theory_axiom="hurst_memory", description="波动率regime→状态依赖(部分VolRegime)"),
    dict(code="oi_anomaly", name="OI异常", field_family="oi", extraction="异常突变(尾部/突变)",
         signal_target="资金事件", theory_axiom="profit_L1", description="OI突变→资金事件(方向已试薄)"),
    dict(code="spread_structure", name="价差结构", field_family="price", extraction="截面差(bid-ask价差)",
         signal_target="流动性/成本", theory_axiom="profit_L2", description="价差→成本/毒性"),
    dict(code="intensity_level", name="强度水平", field_family="volume/oi", extraction="水平动量(值/变化)",
         signal_target="活跃度", theory_axiom=None, description="成交/持仓强度→活跃度"),
]

# 因子→角度 关键词规则(顺序敏感:先匹配先标。加撤/深度等特定类先于 book 兜底)
ANGLE_RULES = [
    ("add_cancel_pattern", ["CancelStorm", "Flee", "CancelPersist", "CancelVelocity", "Iceberg",
                            "Spoof", "RetailAddCancel", "ImpactFleeCancel", "QuoteTiltAsym"]),
    ("add_cancel_imbalance", ["OFI", "Ofi", "ofi", "NetFlow", "KeyPush", "AddCancel", "OrderFlow",
                              "OfiCancel", "TradeFlowSurprise", "TradeFlowImbalance", "RankTradeFlow",
                              "CascadeDepth", "CascadeVelocity"]),
    ("depth_shape", ["Depth", "Shape", "Entropy", "DepthWeighted"]),
    ("depth_slope", ["Slope", "Tilt", "Gradient", "PressureDiverge", "BreachPressure"]),
    ("trade_rhythm", ["TradeRun", "VolBurst", "FreqStorm", "RetailFreq", "Burst", "TradePriceVol"]),
    ("trade_imbalance", ["TradeFlow", "TradeImb", "DirectionalBreach", "BreachRun", "ImpactFlee"]),
    ("price_microstructure", ["PriceTilt", "Coherence", "PriceVol", "Microstructure", "PriceTiltCoherence"]),
    ("volatility_regime", ["VolRegime", "Regime", "CascadeVelocityRegime"]),
    ("oi_anomaly", ["OIChase", "RetailOI", "OpenInterest"]),
    ("spread_structure", ["Spread", "SpreadDelta", "SpreadOFI"]),
    ("book_imbalance", ["Imbalance", "Imb", "RawBook", "BHHI", "LiquidityVoid", "VolPricePush",
                        "QuoteTilt", "FleeRunPath", "BPDiff"]),  # 盘口不平衡兜底
]


def classify(name: str, formula: str) -> str | None:
    text = f"{name or ''} {formula or ''}"
    for angle, keywords in ANGLE_RULES:
        if any(k in text for k in keywords):
            return angle
    return None


def main():
    with db.get_conn() as c:
        db.ensure_angle_schema(c)
        for a in ANGLES:
            db.add_angle(c, **a)
        print(f"本体预填: {len(ANGLES)} 个信息角度")
        factors = c.execute("SELECT xname, class_name, formula_text, angle_code FROM factors").fetchall()
        n_tagged = n_skip = 0
        for f in factors:
            if f["angle_code"]:
                n_skip += 1
                continue
            ang = classify(f["class_name"], f["formula_text"])
            if ang:
                db.tag_factor_angle(c, f["xname"], ang)
                n_tagged += 1
            else:
                n_skip += 1
        print(f"因子标注: 新标 {n_tagged}, 跳过(已标/无匹配) {n_skip}, 共 {len(factors)}")
        print("\n=== angle_coverage(按饱和度) ===")
        cov = db.query_angle_coverage(c)
        order = {"unexplored": 0, "thin": 1, "partial": 2, "saturated": 3}
        for cov_i in sorted(cov, key=lambda x: order.get(x["saturation"], 9)):
            print(f"  [{cov_i['saturation']:<11}] {cov_i['code']:<22} "
                  f"因子={cov_i['n_factors']:<3} dead_end={cov_i['n_dead_end']:<3} "
                  f"max_icir={str(cov_i['max_icir'])[:5]:<6} {cov_i['name']}")


if __name__ == "__main__":
    main()
