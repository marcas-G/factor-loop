#!/usr/bin/env python3
"""现象卡生成器：detections.json → 方向中性现象卡（双视图）。

双视图设计：
  inventor_view  — 匿名、无因子名/机制词、无买卖方向词。只给概念发明器看。
  memory_view    — 完整来源(因子名/horizon/统计)。只进提案-实验记忆库。

方向中性规则：observation 内禁止出现 买方/卖方/上涨/下跌/买单/卖单/多头/空头。
用 两侧角色 / 符号 / 方向 等抽象词表述。

输出：cards/*.json（每卡一个文件）+ cards/index.json。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DETS = ROOT / "concept_cards" / "detections.json"
OUT = ROOT / "concept_cards" / "cards"

AVAILABLE_OBSERVATIONS = [
    "multi_level_depth_snapshot",
    "midprice",
    "spread",
    "directional_flow_proxies",
    "snapshot_differences",
    "cross_feed(main_vs_sub)",
    "daily_ic_vectors",
]

FORBIDDEN_DEPENDENCIES = [
    "order_identity",
    "order_event_time",
    "real_intervention_model",
    "pointwise_state_distance",
]

# 敏感词黑名单（方向中性校验）
FORBIDDEN_WORDS = ["买", "卖", "涨", "跌", "多单", "空单", "bid", "ask", "buy", "sell"]


CONTENT_FIELDS = ("observation", "unanswered_question", "expected_symmetry")


def check_direction_neutral(inv, card_id):
    """只扫内容字段值，不扫元字段名（forbidden_dependencies 的 key 含 'bid'）。"""
    text = json.dumps({k: inv[k] for k in CONTENT_FIELDS if k in inv}, ensure_ascii=False).lower()
    hits = [w for w in FORBIDDEN_WORDS if w in text]
    if hits:
        raise ValueError(f"{card_id}: inventor_view 含方向词 {hits}")


def family_of(factor):
    if factor.startswith("Imbalance"):
        return "imbalance_family"
    return factor


def build_scale_card(dets):
    """尺度失配按测量问题家族合并 → 家族卡 + 单因子卡。"""
    cards = []
    families = {}
    singles = []
    for d in dets:
        fam = family_of(d["factor"])
        if fam == "imbalance_family":
            families.setdefault(fam, []).append(d)
        else:
            singles.append(d)

    for fam, ds in families.items():
        n = len(ds)
        best = max(ds, key=lambda d: abs(d["icir_main"]) + abs(d["icir_sub"]))
        cards.append({
            "phenomenon_id": "PH_SCALE_IMB_FAMILY",
            "source_type": "CROSS_FEED_SCALE_MISMATCH",
            "inventor_view": {
                "observation": (
                    f"共享同一测量问题(盘口两侧相对规模不平衡)的 {n} 个实现，"
                    "在流动性较高的合约层级上预测有效且同号，"
                    "在流动性较低的层级上符号反转或失效。"
                    "同一测量问题在两个流动性层级上的预测行为持续分歧"
                    f"(滚动块一致率 {best['persistence']:.2f}，去极端稳健)。"
                ),
                "controlled_dimensions": ["commodity", "measurement_question", "prediction_horizon", "period"],
                "varying_dimensions": ["liquidity_level", "contract_position"],
                "matched_conditions": "PENDING_STATE_DATA",
                "unanswered_question": "两个流动性层级为何对同一测量呈现符号相反/幅度悬殊的预测行为?",
                "available_observations": AVAILABLE_OBSERVATIONS,
                "forbidden_dependencies": FORBIDDEN_DEPENDENCIES,
            },
            "memory_view": {
                "source_factors": [d["factor"] for d in ds],
                "horizon": best["horizon"],
                "n_days": best["n_days"],
                "icir_main": best["icir_main"], "icir_sub": best["icir_sub"],
                "sign_flip": best["sign_flip"], "persistence": best["persistence"], "robust": best["robust"],
                "all_detections": ds,
            },
        })

    for d in singles:
        cid = f"PH_SCALE_{d['factor'][:20]}"
        flip_desc = "符号反转" if d["sign_flip"] else "幅度悬殊"
        cards.append({
            "phenomenon_id": cid,
            "source_type": "CROSS_FEED_SCALE_MISMATCH",
            "inventor_view": {
                "observation": (
                    f"一个测量问题在两个流动性层级上预测行为{flip_desc}："
                    f"主力层级 ICIR={d['icir_main']:+.2f}，次主力层级 ICIR={d['icir_sub']:+.2f}，"
                    f"平均效应量差 {d['mag_gap']:.4f}。滚动块一致率 {d['persistence']:.2f}，去极端稳健。"
                ),
                "controlled_dimensions": ["commodity", "measurement_question", "prediction_horizon", "period"],
                "varying_dimensions": ["liquidity_level", "contract_position"],
                "matched_conditions": "PENDING_STATE_DATA",
                "unanswered_question": "该测量在两个层级间的行为差异由何种层级性状态条件解释?",
                "available_observations": AVAILABLE_OBSERVATIONS,
                "forbidden_dependencies": FORBIDDEN_DEPENDENCIES,
            },
            "memory_view": d,
        })
    return cards


def build_mirror_card(d):
    strong, weak = (d["factor_a"], d["factor_b"]) if abs(d["mean_a"]) >= abs(d["mean_b"]) else (d["factor_b"], d["factor_a"])
    s_m, w_m = (d["mean_a"], d["mean_b"]) if strong == d["factor_a"] else (d["mean_b"], d["mean_a"])
    cards = [{
        "phenomenon_id": f"PH_MIRROR_{d['factor_a'][:12]}_{d['factor_b'][:12]}",
        "source_type": "MIRROR_BEHAVIOR_ASYMMETRY",
        "inventor_view": {
            "observation": (
                f"两个测量实现的日级预测行为互为镜像(相关 {d['corr']:.2f})，"
                f"但平均效应量相差 {d['mag_ratio']:.1f} 倍"
                f"(强侧 |IC|≈{abs(s_m):.3f} 且有效，弱侧 |IC|≈{abs(w_m):.3f} 且{'有效' if (d['effective_a'] and d['effective_b']) else '无效或边缘'})。"
                "交换两侧角色并反转响应方向后，理论镜像的行为并不对称。"
            ),
            "expected_symmetry": "mirrored_behavior_should_match_or_reverse",
            "observed_violation": ["magnitude_difference", "effectiveness_difference"],
            "matched_conditions": "PENDING_STATE_DATA",
            "unanswered_question": "哪个当前未测量的方向中性状态，使两个镜像过程不再等价?",
            "available_observations": AVAILABLE_OBSERVATIONS,
            "forbidden_dependencies": FORBIDDEN_DEPENDENCIES,
        },
        "memory_view": d,
    }]
    return cards


def build_regime_card(d):
    trend_desc = {
        "COUNTER_LIBRARY": "反库基线的方向运动",
        "WITH_LIBRARY_STRENGTHENING": "与库基线同向(库增强)",
        "WITH_LIBRARY_DECAY": "与库基线同向(库衰减)",
    }.get(d["trend"], d["trend"])
    return [{
        "phenomenon_id": f"PH_REGIME_{d['factor'][:24]}",
        "source_type": "REGIME_EFFECT_DIVERGENCE",
        "inventor_view": {
            "observation": (
                f"某测量问题的预测行为在时间前半段有效且方向为负"
                f"(ICIR={d['icir_first']:+.2f}，|IC|={abs(d['mean_first']):.4f})，"
                f"后半段有效且方向为正(ICIR={d['icir_second']:+.2f}，|IC|={abs(d['mean_second']):.4f})——"
                "符号严格翻转，两侧效应量均达有效门槛，去极端稳健。"
                f"同期库内其他测量整体{trend_desc}。"
            ),
            "controlled_dimensions": ["commodity", "measurement_question", "liquidity_level"],
            "varying_dimensions": ["time_period"],
            "matched_conditions": "PENDING_STATE_DATA",
            "unanswered_question": "何种未测量的状态条件在时间中途翻转了该测量的预测方向?",
            "available_observations": AVAILABLE_OBSERVATIONS,
            "forbidden_dependencies": FORBIDDEN_DEPENDENCIES,
        },
        "memory_view": d,
    }]


def main():
    dets = json.loads(DETS.read_text())
    # 尺度失配按测量问题家族合并（imbalance 家族 4 条 → 1 张卡），其余逐条成卡
    scale_dets = [d for d in dets if d["type"] == "CROSS_FEED_SCALE_MISMATCH"]
    others = [d for d in dets if d["type"] != "CROSS_FEED_SCALE_MISMATCH"]
    cards = build_scale_card(scale_dets) + [c for d in others for c in
                                            (build_mirror_card(d) if d["type"] == "MIRROR_BEHAVIOR_ASYMMETRY" else build_regime_card(d))]

    # 方向中性校验
    for c in cards:
        check_direction_neutral(c["inventor_view"], c["phenomenon_id"])

    OUT.mkdir(exist_ok=True)
    index = []
    for c in cards:
        fp = OUT / f"{c['phenomenon_id']}.json"
        fp.write_text(json.dumps(c, ensure_ascii=False, indent=1))
        index.append(c["phenomenon_id"])
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))

    from collections import Counter
    print("现象卡:", len(cards), "张")
    for c in cards:
        print(f"  {c['phenomenon_id']:<34} {c['source_type']}")
    print("→", OUT)


if __name__ == "__main__":
    main()
