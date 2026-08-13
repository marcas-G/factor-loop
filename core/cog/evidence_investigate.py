#!/usr/bin/env python3
r"""Evidence Investigation 原子 CLI(黑洞①修复)。

把 S2.2 的 4 步(bridge→compile→probe→derive→card)合成一个 CLI,
主会话只调 1 次,不再逐步 Bash + 拼 import(原来 8 假设 × 4 步 = 32 次调用的根因)。

用法:
    python core/cog/evidence_investigate.py --assumption '{"id":"A4",...}' --xname ImbalanceBase
    python core/cog/evidence_investigate.py --assumptions-file /tmp/assumptions.json --xname ImbalanceBase

输出:单个 JSON(evidence_card),含每条假设的 programmatic_verdict + IC 数据。

设计:
    - 不依赖加工因子 .xy(那需要预下载 + 平台 DAG,脆弱且缺数据)
    - 直接用 evidence_derive 从 14 Raw 探针派生 89 维度(覆盖 depth/path/regime/tempo/OI)
    - 对每条假设:从 assumption.equivalent_states 提取 held_equal + collapsed 维度名
      → 在 evidence_derive 输出里匹配列 → conditional slice(控制 held_equal 分位,
      看 collapsed 维度的 Y 预测力)→ programmatic_verdict
    - programmatic_verdict: SUPPORTS(证据支持假设) / CONTRADICTS(证据反驳) / UNCLEAR(模糊)
      CONSISTENT → 不需要派 adjudicator(程序化已判)
      CONTRADICTS/UNCLEAR → 派 adjudicator 做语义确认
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

from core.cog.evidence_derive import load_raw, derive
from core.cog.bridge_validator import validate_bridge


# assumption 描述里的关键词 → evidence_derive 列名映射
# (assumption-extractor 用自然语言描述,这里做受控词汇 → 列名匹配)
_KEYWORD_TO_COLUMN = [
    # depth / 深档
    (["深档", "depth", "档位分布", "entropy", "重心", "centroid"], "bid_depth_entropy"),
    (["深档", "depth", "厚度", "thickness"], "deep_thickness_imb"),
    # imb / 不平衡
    (["imb", "不平衡", "imbalance", "bid0", "ask0", "最优档"], "imb"),
    (["d_imb", "imb 变化", "imb 差分", "新息"], "d_imb"),
    # OI
    (["oi", "持仓", "open_interest", "能量"], "oi_energy"),
    (["d_oi", "持仓变化", "oi 变化"], "d_oi"),
    # tempo / 路径
    (["路径", "path", "跳跃", "渐变", "burst", "突发"], "burst_score"),
    (["run_length", "游程", "连续"], "run_length"),
    # hawkes / 级联
    (["hawkes", "级联", "cascade", "自激发"], "hawkes_trade_z"),
    # price / mid
    (["价格", "mid", "price_step", "步阶"], "d_mid_z"),
    # spread
    (["spread", "价差", "买卖价差"], "spread"),
    # spoof / 意图
    (["spoof", "虚假", "诱骗", "意图"], "spoof_any_sign"),
    (["intent", "意图", "撤单"], "intent_action_divergence"),
    # volume
    (["volume", "成交量", "d_volume"], "d_volume_z"),
    # regime / 波动
    (["regime", "波动", "vol", "低流动", "高流动"], "d_mid_std"),
]


def _match_columns(assumption_text: str, available_cols: list[str]) -> tuple[str | None, str | None]:
    """从 assumption 文本提取 held_equal(被压成相同的)和 collapsed(被合并的差异)对应的列名。

    返回 (held_equal_col, collapsed_col)。匹配不到 → (None, None)。
    """
    text = assumption_text.lower()
    held_col = None
    collapsed_col = None

    # 先找 collapsed(被合并的差异)— 这是假设里说的"盲区"/"看错"的维度
    for keywords, col in _KEYWORD_TO_COLUMN:
        if col not in available_cols:
            continue
        for kw in keywords:
            if kw.lower() in text:
                # heuristic: collapsed 是假设里提到的"差异/盲区"维度
                # held_equal 是因子"压成相同"的维度(通常是 imb 或 oi_energy)
                if col in ("imb", "oi_energy", "spread", "d_mid_z"):
                    if held_col is None:
                        held_col = col
                else:
                    if collapsed_col is None:
                        collapsed_col = col
                break

    # 兜底:如果只匹配到一个,根据假设上下文猜
    if held_col and not collapsed_col:
        # held 找到了,collapsed 没找到 → 从文本再找 "d_" 开头的
        for keywords, col in _KEYWORD_TO_COLUMN:
            if col.startswith("d_") and col in available_cols and col != held_col:
                for kw in keywords:
                    if kw.lower() in text:
                        collapsed_col = col
                        break
                if collapsed_col:
                    break

    return held_col, collapsed_col


def _conditional_slice_ic(df: pd.DataFrame, held_col: str, collapsed_col: str,
                          y_col: str, n_bins: int = 5) -> dict:
    """控制 held_col 分位后,collapsed_col 对 Y 的偏 IC(conditional slice)。

    返回 {n_bins, avg_ic_collapsed, avg_ic_held, per_bin: [...], verdict}
    """
    valid = df[[held_col, collapsed_col]].notna().all(axis=1) & df[y_col].notna()
    d = df.loc[valid, [held_col, collapsed_col]].copy()
    d["y"] = df.loc[valid, y_col]

    if len(d) < 200:
        return {"verdict": "UNCLEAR", "reason": f"样本不足({len(d)}),无法判", "n": len(d)}

    d["held_bin"] = pd.qcut(d[held_col], n_bins, labels=False, duplicates="drop")
    actual_bins = d["held_bin"].nunique()
    if actual_bins < 2:
        return {"verdict": "UNCLEAR", "reason": f"held_col 分位不足({actual_bins} bin)", "n": len(d)}

    per_bin = []
    ic_collapsed_list = []
    ic_held_list = []
    for b, g in d.groupby("held_bin"):
        if len(g) < 50:
            continue
        ic_c = g[collapsed_col].corr(g["y"])
        ic_h = g[held_col].corr(g["y"])
        if np.isnan(ic_c) or np.isnan(ic_h):
            continue
        per_bin.append({"bin": int(b), "n": len(g),
                        "ic_collapsed": round(float(ic_c), 4),
                        "ic_held": round(float(ic_h), 4)})
        ic_collapsed_list.append(ic_c)
        ic_held_list.append(ic_h)

    if not ic_collapsed_list:
        return {"verdict": "UNCLEAR", "reason": "分位内样本不足", "n": len(d)}

    avg_ic_collapsed = float(np.mean(ic_collapsed_list))
    avg_ic_held = float(np.mean(ic_held_list))

    # verdict:控制 held 后 collapsed 仍有显著 IC → CONTRADICTS(假设说 collapsed 无信息)
    # collapsed IC 接近 0 → SUPPORTS(假设对,collapsed 确实无额外信息)
    if abs(avg_ic_collapsed) > 0.02 and abs(avg_ic_collapsed) > abs(avg_ic_held) * 0.3:
        verdict = "CONTRADICTS"
        reason = f"控制 {held_col} 后 {collapsed_col} 仍有 IC={avg_ic_collapsed:.4f}(>0.02),携带额外信息"
    elif abs(avg_ic_collapsed) < 0.005:
        verdict = "SUPPORTS"
        reason = f"控制 {held_col} 后 {collapsed_col} IC={avg_ic_collapsed:.4f}(<0.005),无额外信息"
    else:
        verdict = "UNCLEAR"
        reason = f"控制 {held_col} 后 {collapsed_col} IC={avg_ic_collapsed:.4f}(边界,需 adjudicator)"

    return {
        "verdict": verdict, "reason": reason, "n": len(d),
        "n_bins": len(per_bin), "avg_ic_collapsed": round(avg_ic_collapsed, 4),
        "avg_ic_held": round(avg_ic_held, 4), "per_bin": per_bin,
    }


def investigate(assumptions: list[dict], xname: str, y_horizon: str = "1") -> dict:
    """对一组假设跑 evidence investigation,返回 evidence_card。

    每条假设:match columns → conditional slice → programmatic_verdict。
    """
    print(f"[evidence] 加载 14 探针 + derive 89 维度...", file=sys.stderr)
    df = derive(load_raw(days=None))
    available_cols = [c for c in df.columns if c not in ["receive_time", "weight"]
                      and not c.startswith("X.") and not c.startswith("Y.")]
    y_candidates = [c for c in df.columns if "PriceMid" in c and f"@{y_horizon}" in c]
    if not y_candidates:
        return {"error": f"找不到 Y 列(horizon={y_horizon})"}
    y_col = y_candidates[0]
    print(f"[evidence] Y={y_col[:50]}, 派生维度={len(available_cols)}", file=sys.stderr)

    results = []
    for a in assumptions:
        aid = a.get("id", "?")
        text = a.get("assumption", "") + " " + a.get("认知盲区", "") + " " + a.get("equivalent_states", "")
        held_col, collapsed_col = _match_columns(text, available_cols)

        if not held_col or not collapsed_col:
            results.append({
                "assumption_id": aid,
                "programmatic_verdict": "UNCLEAR",
                "reason": f"无法匹配列(held={held_col}, collapsed={collapsed_col}),需 adjudicator",
                "matched_held_col": held_col, "matched_collapsed_col": collapsed_col,
            })
            continue

        slice_result = _conditional_slice_ic(df, held_col, collapsed_col, y_col)
        results.append({
            "assumption_id": aid,
            "assumption": a.get("assumption", "")[:120],
            "matched_held_col": held_col,
            "matched_collapsed_col": collapsed_col,
            "programmatic_verdict": slice_result["verdict"],
            "reason": slice_result["reason"],
            "n": slice_result.get("n"),
            "avg_ic_collapsed": slice_result.get("avg_ic_collapsed"),
            "avg_ic_held": slice_result.get("avg_ic_held"),
            "per_bin": slice_result.get("per_bin"),
        })
        print(f"  {aid}: {slice_result['verdict']} — {slice_result['reason']}", file=sys.stderr)

    # 汇总
    n_contradicts = sum(1 for r in results if r["programmatic_verdict"] == "CONTRADICTS")
    n_supports = sum(1 for r in results if r["programmatic_verdict"] == "SUPPORTS")
    n_unclear = sum(1 for r in results if r["programmatic_verdict"] == "UNCLEAR")

    return {
        "xname": xname,
        "y_col": y_col[:60],
        "n_samples": len(df),
        "n_assumptions": len(assumptions),
        "summary": {"CONTRADICTS": n_contradicts, "SUPPORTS": n_supports, "UNCLEAR": n_unclear},
        "results": results,
        "guidance": (
            f"CONTRADICTS({n_contradicts}) 的假设值得派 adjudicator 做语义确认; "
            f"SUPPORTS({n_supports}) 的假设程序化已判,不需要 adjudicator; "
            f"UNCLEAR({n_unclear}) 需 adjudicator 判定"
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Evidence Investigation 原子 CLI")
    ap.add_argument("--assumption", help="单条假设 JSON 字符串")
    ap.add_argument("--assumptions-file", help="假设数组 JSON 文件")
    ap.add_argument("--xname", required=True, help="因子 xname")
    ap.add_argument("--y-horizon", default="1", help="Y horizon(秒,默认 1)")
    args = ap.parse_args()

    if args.assumptions_file:
        assumptions = json.loads(Path(args.assumptions_file).read_text())
    elif args.assumption:
        assumptions = [json.loads(args.assumption)]
    else:
        ap.error("需 --assumption 或 --assumptions-file")

    card = investigate(assumptions, args.xname, args.y_horizon)
    print(json.dumps(card, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
