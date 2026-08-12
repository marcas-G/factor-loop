"""种子 axiom(理论公理,新库初始化时预填)。从 factors.db dump,可复现。

用法: python factor_db/seed_axioms.py [--db PATH]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.db import db

AXIOMS = [
    ('basis_reversion', 'cross_contract', '跨合约价差(基差)受套利约束,偏离统计均衡后均值回归', 'spread(t)=p_main-p_sub; spread 均值回复(负自相关)', {'mean_reversion': '价差偏离→回归(负自相关显著)'}, '统计套利/基差交易'),
    ('info_propagation', 'cross_contract', '信息从主力合约向次月/相关品种传导(主力先吸收信息,次月滞后跟随,lead-lag)', 'r_main(t-k) → r_sub(t), k>0 Granger', {'lead_lag': '主力收益 Granger-cause 次月收益(k秒滞后正相关)'}, '主力-次月信息传导文献'),
    ('emh', 'efficiency', '有效市场假说:价格已反映所有可得信息,收益不可预测(自相关≈0、无持续超额收益)。', 'E[r_{t+1}|Ω_t]=r_f, 自相关≈0', {'autocorr': 'near_zero', 'no_persistent_alpha': 'true'}, 'Fama 1970 EMH'),
    ('info_diffusion_monotone', 'efficiency', '信息扩散单调性:新信息对价格的冲击随 horizon 单调衰减(不回升)。', '|impact(h)| 关于 h 单调递减', {'impact_vs_horizon': 'monotone_decreasing'}, '微观结构/信息扩散'),
    ('info_orthogonality', 'efficiency', '信息正交性:不同信息源(不同字段/因子)携带的未来订单流信息应正交,否则冗余。', '不同信息源的 IC 残差不应高度共线', {'ic_residual_decorrelation': 'low_redundancy'}, '信息论/因子正交'),
    ('adverse_selection', 'informed', '做市商面临逆向选择(知情者先交易),需扩大价差补偿毒性风险', 'spread 与知情交易概率正相关', {'spread_toxicity': '价差与知情概率/毒性正相关'}, 'Glosten-Milgrom 1985 / Copeland-Galai 1983'),
    ('toxicity_detectable', 'informed', '订单流毒性可从成交强度+方向突变检测(毒性积聚预示大波动)', 'VPIN 高 → 后续 |r| 大', {'vpin': '高毒性时段→后续波动大'}, 'Easley OPM / Easley-López VPIN 2012'),
    ('liquidity_commonality', 'liquidity', '流动性有共同因子(系统性流动性),合约间流动性共动', 'liq_i 与 market_liq 相关(common factor)', {'commonality': '合约流动性与市场流动性正相关'}, 'Chordia 2000 流动性共动'),
    ('liquidity_premium', 'liquidity', '流动性供给者要求补偿,低流动性时期/品种瞬时预期收益更高(流动性溢价)', 'E[r|low_liq] > E[r|high_liq]', {'amihud': 'Amihud 流动性低→未来收益高(负相关)'}, 'Amihud 2002 / Pastor-Stambaugh 2003'),
    ('manipulation_costly', 'manipulation', '大规模操纵有成本(套利/监管/资金约束),小规模挂单可短期诱导但价格终回归', '操纵信号(异常挂单)→短期偏移→回归', {'spoof_revert': '异常挂单→短期价格偏移→回归'}, '市场操纵微观结构'),
    ('hurst_memory', 'memory', 'Hurst 指数:H<0.5 均值回复,H>0.5 动量持续,H=0.5 随机游走(无记忆)。', 'H = lim_{n→∞} (R/S)_n / log(n)', {'hurst_lt_half': 'mean_reverting', 'hurst_gt_half': 'trending'}, 'Hurst 1951 / R/S'),
    ('gatheral_nomanip', 'microstructure', 'Gatheral 无操纵条件:价格冲击的临时冲击随时间凸非增(无套利/无操纵),冲击衰减具凸性。', '∂²G(τ)/∂τ² ≥ 0(G 为响应函数)', {'impact_decay_convex': 'true'}, 'Gatheral 2010'),
    ('kyle_lambda', 'microstructure', 'Kyle(1985):净订单流冲击价格,冲击量与净流线性正相关,比例 λ>0(价格冲击系数)。', 'Δp = λ·净流 + ε, λ>0', {'impact_slope': 'positive_significant'}, 'Kyle 1985'),
    ('leverage_effect', 'microstructure', '杠杆效应(Black 1976):价格下跌→波动率上升,方向不对称(跌的波动响应强于涨)。', 'Cov(r_t, σ²_{t+1}) < 0 ∧ |跌→波动| > |涨→波动|', {'neg_return_vol_response': 'stronger_than_pos'}, 'Black 1976'),
    ('roll_bounce', 'microstructure', 'Roll(1984)有效价差假设:观测收益的 lag-1 自相关为负(bid-ask bounce),k≥2 阶趋近于零。', 'Cov(r_t,r_{t+1})<0 ∧ Cov(r_t,r_{t+k})≈0 for k≥2', {'lag1_ac': 'negative_significant', 'lagk_ac_ge2': 'near_zero'}, 'Roll 1984'),
    ('oi_informed', 'oi', '持仓量变化含信息(大资金建仓/OI 异动反映知情方向),ΔOI 异常预示后续价格方向', 'ΔOI 异常 ∧ 同向 → 后续 r 同向', {'oi_direction': 'ΔOI 尾部异常→后续价格方向'}, '持仓量信息含量文献'),
    ('profit_L1', 'profit_source', 'L1 别人的机械反应:止损/强平/追涨者的机械反应可被猎取(hunter 赚机械方的钱)。', '机械反应存在 ∧ 级联收益 > 推价成本', {'mechanical_cascade': 'present', 'post_trigger_drift': 'same_direction'}, 'framework §2 L1'),
    ('profit_L2', 'profit_source', 'L2 流动性补偿:做市商赚价差+返佣,承担逆向选择损失(价差收益>逆向选择损失)。', '价差收益 + 返佣 > 逆向选择损失', {'spread_capture': 'exceeds_adverse_selection'}, 'framework §2 L2'),
    ('profit_L3', 'profit_source', 'L3 信息优势:知情者赚信息滞后者(信息优势>获取成本 ∧ 未泄露)。', '信息优势价值 > 获取成本 ∧ 信息未提前扩散', {'informed_flow_predictive': 'significant'}, 'framework §2 L3'),
    ('profit_L4', 'profit_source', 'L4 速度优势:高频赚慢方。500ms 定频快照下基本失效(时间分辨率不足)。', '速度差存在 → 抢先成交获利', {'latency_arbitrage': 'absent_at_500ms'}, 'framework §2 L4'),
    ('profit_L5', 'profit_source', 'L5 风险溢价:持仓者赚风险补偿。短周期(tick/500ms)几近为零。', 'E[r] = r_f + 风险补偿,短周期风险补偿≈0', {'short_horizon_risk_premium': 'near_zero'}, 'framework §2 L5'),
    ('session_regime', 'session', '不同交易时段信息密度/参与者结构不同(开盘信息密集/夜盘流动性薄),IC/波动时段差异显著', 'IC/icir 跨时段显著差异', {'session_diff': '时段间 IC/波动差异显著'}, '日内微观结构时段研究'),
    ('volatility_clustering', 'volatility', '波动率聚集(高波动后跟高波动,GARCH 效应,波动率自相关)', '|r_t|² 自相关正显著', {'arch': '|收益|平方自相关正显著(波动率聚集)'}, 'Engle ARCH 1982 / Bollerslev GARCH 1986'),
]

def seed(db_path=None):
    with db.get_conn(db_path or db.DB_PATH) as c:
        for code,cat,stmt,formal,sig,src in AXIOMS:
            db.add_axiom(c, code, cat, stmt, formal, sig, src)
        print(f"seeded {len(AXIOMS)} axioms")

if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DB_PATH))
    a=ap.parse_args(); seed(a.db)
