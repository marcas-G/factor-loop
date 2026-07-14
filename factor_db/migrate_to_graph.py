"""现有数据 → 知识图节点 + 边 迁移脚本。幂等（UNIQUE 约束 + IF NOT EXISTS）。

分层知识图（详见 plan）：
  AXIOM(axioms表,种子) → DERIVED/HYPOTHESIS(ideas表) → EVIDENCE/REFUTATION(lessons/factors/observe_outputs)
  graph_edges 跨表软引用 (from_table, from_id)。

迁移映射（机械派生，默认安全跑）：
  ideas      → node_layer（necessity_grade necessary/identification → DERIVED，其余 HYPOTHESIS）
  lessons    → REFUTES(dead_end)/SUPPORTS(success_pattern) 边 → ideas(idea_id)
  factors    → INSTANTIATES(evaluated)/REFUTES(dead_end) 边 → ideas(经 idea_factor_links)
  iterations → SPECIALIZES 边 from_xname → to_xname（演化树）
  observe JSON → observe_outputs + CONTRADICTS 边 → axioms（依赖 observe --out，T4）

⚠️ seed_axioms（13 条理论种子）默认不跑——种子是污染源，需人工 review 后用 --seed-axioms 触发。

用法:
  python factor_db/migrate_to_graph.py                       # 机械迁移（不含种子）
  python factor_db/migrate_to_graph.py --seed-axioms         # 追加种子（需 review）
  python factor_db/migrate_to_graph.py --observe-dir DIR     # 追加 observe 导入
  python factor_db/migrate_to_graph.py --dry-run             # 只打印不写
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db

# ============ AXIOM 种子（草稿 · 需人工 review）============
# 8 理论命题（microstructure/efficiency/memory）+ 5 利润来源（framework §2 L1-L5）。
# source 标出处；formal_form 用标准表述；expected_signature 是理论预期可观测签名（用于和 observe 实测比对产 CONTRADICTS）。
SEED_AXIOMS = [
    # --- microstructure ---
    dict(code="roll_bounce", category="microstructure",
         statement="Roll(1984)有效价差假设:观测收益的 lag-1 自相关为负(bid-ask bounce),k≥2 阶趋近于零。",
         formal_form="Cov(r_t,r_{t+1})<0 ∧ Cov(r_t,r_{t+k})≈0 for k≥2",
         expected_signature={"lag1_ac": "negative_significant", "lagk_ac_ge2": "near_zero"},
         source="Roll 1984", falsifiable="若 bid-ask bounce 不存在(如成交无弹性),则 lag1 自相关为零"),
    dict(code="kyle_lambda", category="microstructure",
         statement="Kyle(1985):净订单流冲击价格,冲击量与净流线性正相关,比例 λ>0(价格冲击系数)。",
         formal_form="Δp = λ·净流 + ε, λ>0",
         expected_signature={"impact_slope": "positive_significant"},
         source="Kyle 1985", falsifiable="若价格对净流无响应,则 λ=0"),
    dict(code="gatheral_nomanip", category="microstructure",
         statement="Gatheral 无操纵条件:价格冲击的临时冲击随时间凸非增(无套利/无操纵),冲击衰减具凸性。",
         formal_form="∂²G(τ)/∂τ² ≥ 0(G 为响应函数)",
         expected_signature={"impact_decay_convex": "true"},
         source="Gatheral 2010", falsifiable="若存在操纵,则冲击衰减非凸(可套利)"),
    dict(code="leverage_effect", category="microstructure",
         statement="杠杆效应(Black 1976):价格下跌→波动率上升,方向不对称(跌的波动响应强于涨)。",
         formal_form="Cov(r_t, σ²_{t+1}) < 0 ∧ |跌→波动| > |涨→波动|",
         expected_signature={"neg_return_vol_response": "stronger_than_pos"},
         source="Black 1976", falsifiable="若无杠杆效应,则涨跌的波动响应对称"),
    # --- memory ---
    dict(code="hurst_memory", category="memory",
         statement="Hurst 指数:H<0.5 均值回复,H>0.5 动量持续,H=0.5 随机游走(无记忆)。",
         formal_form="H = lim_{n→∞} (R/S)_n / log(n)",
         expected_signature={"hurst_lt_half": "mean_reverting", "hurst_gt_half": "trending"},
         source="Hurst 1951 / R/S", falsifiable="若序列无长记忆,则 H=0.5"),
    # --- efficiency ---
    dict(code="info_orthogonality", category="efficiency",
         statement="信息正交性:不同信息源(不同字段/因子)携带的未来订单流信息应正交,否则冗余。",
         formal_form="不同信息源的 IC 残差不应高度共线",
         expected_signature={"ic_residual_decorrelation": "low_redundancy"},
         source="信息论/因子正交", falsifiable="若两信息源完全冗余,则 IC 残差共线≈1"),
    dict(code="info_diffusion_monotone", category="efficiency",
         statement="信息扩散单调性:新信息对价格的冲击随 horizon 单调衰减(不回升)。",
         formal_form="|impact(h)| 关于 h 单调递减",
         expected_signature={"impact_vs_horizon": "monotone_decreasing"},
         source="微观结构/信息扩散", falsifiable="若信息可被反复利用,则冲击非单调"),
    dict(code="emh", category="efficiency",
         statement="有效市场假说:价格已反映所有可得信息,收益不可预测(自相关≈0、无持续超额收益)。",
         formal_form="E[r_{t+1}|Ω_t]=r_f, 自相关≈0",
         expected_signature={"autocorr": "near_zero", "no_persistent_alpha": "true"},
         source="Fama 1970 EMH", falsifiable="若存在持续可预测性,则 EMH 在该尺度失效"),
    # --- profit_source (framework §2 L1-L5) ---
    dict(code="profit_L1", category="profit_source",
         statement="L1 别人的机械反应:止损/强平/追涨者的机械反应可被猎取(hunter 赚机械方的钱)。",
         formal_form="机械反应存在 ∧ 级联收益 > 推价成本",
         expected_signature={"mechanical_cascade": "present", "post_trigger_drift": "same_direction"},
         source="framework §2 L1", falsifiable="若机械反应消失(无止损聚集),则 L1 闭环断裂"),
    dict(code="profit_L2", category="profit_source",
         statement="L2 流动性补偿:做市商赚价差+返佣,承担逆向选择损失(价差收益>逆向选择损失)。",
         formal_form="价差收益 + 返佣 > 逆向选择损失",
         expected_signature={"spread_capture": "exceeds_adverse_selection"},
         source="framework §2 L2", falsifiable="若毒性上升压过价差,则 L2 闭环断裂"),
    dict(code="profit_L3", category="profit_source",
         statement="L3 信息优势:知情者赚信息滞后者(信息优势>获取成本 ∧ 未泄露)。",
         formal_form="信息优势价值 > 获取成本 ∧ 信息未提前扩散",
         expected_signature={"informed_flow_predictive": "significant"},
         source="framework §2 L3", falsifiable="若信息已扩散/泄露,则 L3 闭环断裂"),
    dict(code="profit_L4", category="profit_source",
         statement="L4 速度优势:高频赚慢方。500ms 定频快照下基本失效(时间分辨率不足)。",
         formal_form="速度差存在 → 抢先成交获利",
         expected_signature={"latency_arbitrage": "absent_at_500ms"},
         source="framework §2 L4", falsifiable="500ms 定频下无微观速度差异,L4 不成立"),
    dict(code="profit_L5", category="profit_source",
         statement="L5 风险溢价:持仓者赚风险补偿。短周期(tick/500ms)几近为零。",
         formal_form="E[r] = r_f + 风险补偿,短周期风险补偿≈0",
         expected_signature={"short_horizon_risk_premium": "near_zero"},
         source="framework §2 L5", falsifiable="短周期无持仓风险补偿,L5 不成立"),
]

# observe 脚本 → axiom code 映射（import_observe 用）
# ⚠️ 基于脚本实际观测内容(非脚本名)映射。读脚本后修正:
#   microstructure 实测 IC 跨horizon 单调衰减(非 Kyle λ) → info_diffusion_monotone
#   cross_factor 实测两量冗余 → info_orthogonality
#   regime 实测 regime 条件矛盾(无独立 axiom,暂挂扩散单调性)
# ❌ gatheral_nomanip / kyle_lambda 两个强 axiom 当前无 observe 覆盖
#    (需新写算冲击衰减凸性 / 价格冲击 λ 的 observe 脚本)
OBSERVE_AXIOM_MAP = {
    "observe_autocorrelation": "roll_bounce",
    "observe_microstructure": "info_diffusion_monotone",
    "observe_regime": "info_diffusion_monotone",
    "observe_asymmetry": "leverage_effect",
    "observe_lead_lag": "info_diffusion_monotone",
    "observe_cross_factor": "info_orthogonality",
    "book_pressure_horizon": "info_diffusion_monotone",
    "observe_distribution": "emh",
}


def seed_axioms(conn, dry_run: bool = False) -> int:
    """写 13 条种子到 axioms 表（幂等，code 唯一）。⚠️ 草稿，需 review。"""
    n = 0
    for a in SEED_AXIOMS:
        if dry_run:
            print(f"  [dry] {a['code']:<22} {a['statement'][:48]}")
            n += 1
            continue
        db.add_axiom(conn, **a)
        n += 1
    return n


def migrate_ideas_layer(conn, dry_run: bool = False) -> int:
    """设 ideas.node_layer:necessity_grade=necessary/identification→DERIVED,其余→HYPOTHESIS。"""
    total = conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0]
    if dry_run:
        return total
    conn.execute(
        "UPDATE ideas SET node_layer='DERIVED' WHERE necessity_grade IN ('necessary','identification')"
    )
    conn.execute(
        """UPDATE ideas SET node_layer='HYPOTHESIS'
           WHERE node_layer IS NULL OR node_layer NOT IN ('DERIVED','HYPOTHESIS')"""
    )
    return total


def migrate_lessons(conn, dry_run: bool = False) -> int:
    """lessons(dead_end)→REFUTES 边→ideas;success_pattern→SUPPORTS。idea_id NULL 跳过。"""
    rows = conn.execute(
        "SELECT id, type, idea_id FROM lessons WHERE idea_id IS NOT NULL AND deprecated_at IS NULL"
    ).fetchall()
    n = 0
    for r in rows:
        et = "REFUTES" if r["type"] == "dead_end" else "SUPPORTS"
        if dry_run:
            n += 1
            continue
        if db.add_graph_edge(conn, "lessons", r["id"], "ideas", r["idea_id"], et):
            n += 1
    return n


def migrate_factors(conn, dry_run: bool = False) -> int:
    """factors 经 idea_factor_links→ideas:evaluated→INSTANTIATES,dead_end→REFUTES。"""
    rows = conn.execute(
        """
        SELECT f.xname, f.status, ifl.idea_id
        FROM factors f JOIN idea_factor_links ifl ON ifl.factor_xname = f.xname
        WHERE ifl.idea_id IS NOT NULL AND f.deprecated_at IS NULL
        """
    ).fetchall()
    n = 0
    for r in rows:
        et = "REFUTES" if r["status"] == "dead_end" else "INSTANTIATES"
        if dry_run:
            n += 1
            continue
        if db.add_graph_edge(conn, "factors", r["xname"], "ideas", r["idea_id"], et):
            n += 1
    return n


def migrate_iterations(conn, dry_run: bool = False) -> int:
    """iterations(realized)→SPECIALIZES 边 from_xname→to_xname,weight=|icir_delta|。"""
    rows = conn.execute(
        """SELECT from_xname, to_xname, icir_delta FROM iterations
           WHERE status='realized' OR status IS NULL"""
    ).fetchall()
    n = 0
    for r in rows:
        w = abs(r["icir_delta"]) if r["icir_delta"] is not None else None
        if dry_run:
            n += 1
            continue
        if db.add_graph_edge(conn, "factors", r["from_xname"], "factors", r["to_xname"], "SPECIALIZES", w):
            n += 1
    return n


def import_observe(conn, observe_dir: str, dry_run: bool = False) -> int:
    """扫 observe_dir/*.json → observe_outputs + CONTRADICTS 边→axioms。
    JSON 约定:{script?, axiom_code?, violation, summary?, symbol?, weight?, ...}。"""
    d = Path(observe_dir)
    if not d.exists():
        print(f"  observe-dir 不存在: {d}")
        return 0
    n = 0
    for jf in sorted(d.glob("*.json")):
        try:
            data = json.loads(jf.read_text())
        except json.JSONDecodeError as e:
            print(f"  跳过 {jf.name}: JSON 解析失败 {e}")
            continue
        script = data.get("script", jf.stem)
        axiom_code = data.get("axiom_code") or OBSERVE_AXIOM_MAP.get(script)
        if not axiom_code:
            print(f"  跳过 {jf.name}: 无 axiom_code 且 {script} 不在映射表")
            continue
        violation = data.get("violation")
        if not violation:
            print(f"  跳过 {jf.name}: violation 为空(符合 {axiom_code} 预期,非矛盾)")
            continue
        summary = data.get("summary")
        symbol = data.get("symbol")
        if dry_run:
            print(f"  [dry] {script} → {axiom_code} ({violation})")
            n += 1
            continue
        # 去重:同 script+axiom_code+violation+symbol 已存在则跳过(幂等,observe_outputs 无唯一约束)
        dup = conn.execute(
            "SELECT 1 FROM observe_outputs WHERE script=? AND axiom_code=? AND violation=? "
            "AND COALESCE(symbol,'')=COALESCE(?,'')",
            (script, axiom_code, violation, symbol),
        ).fetchone()
        if dup:
            print(f"  跳过 {jf.name}: observe_output 已存在(去重)")
            continue
        oid = db.add_observe_output(conn, script, axiom_code, violation, summary, data, symbol)
        arow = conn.execute("SELECT id FROM axioms WHERE code = ?", (axiom_code,)).fetchone()
        if arow:
            db.add_graph_edge(conn, "observe_outputs", oid, "axioms", arow["id"], "CONTRADICTS",
                              weight=data.get("weight"))
        n += 1
    return n


def check_pattern_cards(conn):
    """核实 pattern_cards 真实数据（HANDOFF 称 62，探索查得 0，对不上）。"""
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM pattern_cards GROUP BY status"
        ).fetchall()
        if not rows:
            return "0 条（表空）"
        return ", ".join(f"{r['status']}={r['n']}" for r in rows)
    except sqlite3.Error:
        return "表不存在"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--observe-dir", help="observe JSON 输出目录，导入为 CONTRADICTS 边")
    ap.add_argument("--seed-axioms", action="store_true", help="写入 13 条 AXIOM 种子（⚠️ 需 review）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写")
    args = ap.parse_args()

    with db.get_conn() as conn:
        db.ensure_graph_schema(conn)
        print("=== pattern_cards 核实 ===")
        print(f"  {check_pattern_cards(conn)}")

        if args.seed_axioms:
            n = seed_axioms(conn, args.dry_run)
            tag = " [dry-run]" if args.dry_run else ""
            print(f"=== seed_axioms: {n} 条{tag} ===")

        steps = [
            ("migrate_ideas_layer", migrate_ideas_layer),
            ("migrate_lessons", migrate_lessons),
            ("migrate_factors", migrate_factors),
            ("migrate_iterations", migrate_iterations),
        ]
        for name, fn in steps:
            n = fn(conn, args.dry_run)
            tag = " [dry-run]" if args.dry_run else ""
            print(f"=== {name}: {n}{tag} ===")

        if args.observe_dir:
            n = import_observe(conn, args.observe_dir, args.dry_run)
            tag = " [dry-run]" if args.dry_run else ""
            print(f"=== import_observe: {n}{tag} ===")

        if not args.dry_run:
            print("=== graph_stats ===")
            for k, v in db.graph_stats(conn).items():
                print(f"  {k}: {v}")


if __name__ == "__main__":
    import sqlite3  # noqa: E402 (check_pattern_cards 异常类型用)
    main()
