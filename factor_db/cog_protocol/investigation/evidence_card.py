"""Evidence Card —— probe 结果 → 结构化证据 + H 蕴含规则。

probe 输出的统计结果 + Contract 的 competing_predictions → Evidence Card:
  样本/匹配质量/效应/稳定性/H 蕴含(SUPPORT/CONTRADICT/NEUTRAL)/限制/强度
H 蕴含用确定性规则:对照每个 H 的 unique_prediction 描述的观测模式 vs 实际效应方向。
"""
import numpy as np

STRENGTH_MAP = {"DIRECT": "STRONG", "INDIRECT": "MODERATE", "WEAK": "WEAK"}


def _monotonic(xs: list, ys: list) -> str:
    """判定 y 随 x 分位的单调方向: up / down / none / nonmonotonic。"""
    if len(ys) < 3:
        return "none"
    d1 = ys[1] - ys[0]
    d2 = ys[2] - ys[1]
    if abs(d1) < 1e-9 and abs(d2) < 1e-9:
        return "none"
    if d1 > 0 and d2 > 0:
        return "up"
    if d1 < 0 and d2 < 0:
        return "down"
    if (d1 > 0) != (d2 > 0):
        return "nonmonotonic"
    return "none"


def build_evidence(probe_result: dict, contract: dict, observed_incompat_strength: str = "INDIRECT") -> dict:
    """从 probe 统计 + contract 产 Evidence Card。"""
    preds = contract["competing_predictions"]
    ev = {
        "test_id": contract.get("test_id"),
        "sample": {"n_total": probe_result.get("n_total"), "y_horizon": probe_result.get("y_horizon")},
        "matched_quality": {},
        "result": {},
        "stability": {"day_consistency": "UNEVALUATED", "block_consistency": "UNEVALUATED"},
        "hypothesis_implications": {},
        "limitations": [],
        "evidence_strength": STRENGTH_MAP.get(observed_incompat_strength, "MODERATE"),
    }

    # 逐变化维度:单调方向 + 组间差异幅度
    by_dim = probe_result.get("by_dim", {})
    for dim, groups in by_dim.items():
        ys = [g["mean_y"] for g in groups]
        hs = [g["hit_rate"] for g in groups]
        dirn = _monotonic(list(range(len(ys))), ys)
        max_diff = abs(ys[-1] - ys[0]) if len(ys) > 1 else 0.0
        # 简单显著性:组间差 vs 组内 std 混合
        stderrs = [g["std_y"] / max(np.sqrt(g["n"]), 1) for g in groups]
        pooled_se = np.sqrt(np.mean(np.array(stderrs) ** 2)) if stderrs else 0.0
        z = max_diff / (pooled_se + 1e-9) if pooled_se > 0 else 0.0
        ev["result"][dim] = {
            "monotonic_direction": dirn,
            "mean_y_by_quantile": [round(g["mean_y"], 5) for g in groups],
            "hit_rate_by_quantile": [round(g["hit_rate"], 4) for g in groups],
            "max_effect": round(max_diff, 5),
            "z_approx": round(float(z), 2),
            "n_by_quantile": [g["n"] for g in groups],
        }

    # H 蕴含:确定性规则(每个 H 的 unique_prediction 描述的模式 → 实际方向对照)
    for hid in ["H1", "H2", "H3", "H0"]:
        pred = (preds.get(hid) or {}).get("unique_prediction", "").lower()
        implied = "NEUTRAL"
        for dim, r in ev["result"].items():
            d = r["monotonic_direction"]
            if d == "none":
                continue
            # H1/H2 常预言"随 X 单调上升/下降" —— 匹配方向词
            if "单调" in pred or "上升" in pred or "增加" in pred:
                if d == "up":
                    implied = "SUPPORT"
                elif d == "down":
                    implied = "CONTRADICT"
            elif "下降" in pred or "减少" in pred:
                if d == "down":
                    implied = "SUPPORT"
                elif d == "up":
                    implied = "CONTRADICT"
            elif "不变" in pred or "消失" in pred or "无差异" in pred:
                if d == "none":
                    implied = "SUPPORT"
                else:
                    implied = "CONTRADICT"
        ev["hypothesis_implications"][hid] = implied

    # 限制
    if ev["sample"]["n_total"] is None or ev["sample"]["n_total"] < 1000:
        ev["limitations"].append("样本量小(<1000)")
    if observed_incompat_strength != "DIRECT":
        ev["limitations"].append(f"证据基于 {observed_incompat_strength} 迹象")
    return ev
