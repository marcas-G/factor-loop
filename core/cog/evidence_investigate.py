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
# ── 词表即概念缓存: 事实源在 data/concept_lexicon.json ──
# (cog-concept-compiler agent 的编译产物回填到 JSON, 逐轮生长;
#  本 .py 内置表仅作 JSON 缺失时的 fallback)
_LEXICON_PATH = Path(__file__).resolve().parents[2] / "data" / "concept_lexicon.json"


def _load_lexicon() -> list[tuple[list[str], str]]:
    if _LEXICON_PATH.exists():
        entries = json.loads(_LEXICON_PATH.read_text())["entries"]
        return [(e["keywords"], e["col"]) for e in entries]
    return _KEYWORD_TO_COLUMN_FALLBACK


_KEYWORD_TO_COLUMN_FALLBACK = [
    # depth / 深档
    (["深档", "depth", "档位分布", "entropy", "重心", "centroid"], "bid_depth_entropy"),
    (["重心位置", "档位索引", "argmax", "深档位置", "depth_centroid"], "bid_depth_centroid"),
    (["深档", "depth", "厚度", "thickness"], "deep_thickness_imb"),
    (["深档厚度", "买侧厚度", "bid 侧厚度"], "deep_bid_thickness"),
    (["卖侧厚度", "ask 侧厚度"], "deep_ask_thickness"),
    # imb / 不平衡
    (["imb", "不平衡", "imbalance", "bid0", "ask0", "最优档"], "imb"),
    (["d_imb", "imb 变化", "imb 差分", "新息"], "d_imb"),
    (["买一量变化", "d_bid0", "bid0 变化"], "d_bid0_z"),
    (["卖一量变化", "d_ask0", "ask0 变化"], "d_ask0_z"),
    # OI
    (["oi", "持仓", "open_interest", "能量"], "oi_energy"),
    (["d_oi", "持仓变化", "oi 变化"], "d_oi"),
    (["增仓", "减仓", "开仓", "平仓", "oi_open"], "oi_open"),
    # tempo / 路径
    (["路径", "path", "跳跃", "渐变", "burst", "突发"], "burst_score"),
    (["run_length", "游程", "连续"], "run_length"),
    # hawkes / 级联
    (["hawkes", "级联", "cascade", "自激发"], "hawkes_trade_z"),
    (["成交自激发", "trade hawkes"], "hawkes_trade_z"),
    (["撤单自激发", "撤单级联", "cancel hawkes"], "hawkes_cancel_z"),
    (["挂单自激发", "add hawkes"], "hawkes_add_z"),
    (["连续性", "continuation", "hawkes_cont"], "hawkes_cont_z"),
    # price / mid
    (["价格", "中价", "mid", "price_step", "步阶"], "d_mid_z"),
    # spread
    (["spread", "价差", "买卖价差"], "spread"),
    # spoof / 意图
    (["spoof", "虚假", "诱骗", "意图"], "spoof_any_sign"),
    (["intent", "意图", "撤单"], "intent_action_divergence"),
    (["意图流", "intent_flow"], "intent_flow"),
    (["行动流", "action_flow"], "action_flow"),
    (["意图行动比", "意图与行动"], "action_intent_ratio"),
    # ── 事件代理族(A1/A9 型"来源不可区分"假设的检验弹药) ──
    (["成交事件", "trade_event", "有无成交"], "trade_event"),
    (["主动买", "买方成交", "trade_buy", "买盘成交"], "trade_buy"),
    (["主动卖", "卖方成交", "trade_sell", "卖盘成交"], "trade_sell"),
    (["大撤单", "large_cancel", "大单撤销"], "large_cancel_any"),
    (["大挂单", "large_add", "大单新增"], "large_add_any"),
    (["买侧大撤单"], "large_cancel_bid"),
    (["卖侧大撤单"], "large_cancel_ask"),
    (["买侧大挂单"], "large_add_bid"),
    (["卖侧大挂单"], "large_add_ask"),
    (["主动压力", "行动压力", "active pressure"], "pressure_active"),
    (["被动压力", "挂单压力", "passive pressure"], "pressure_passive"),
    (["深档撤单对齐", "深档与撤单"], "deep_bid_cancel_align"),
    # volume
    (["volume", "成交量", "d_volume"], "d_volume_z"),
    # regime / 波动
    (["regime", "波动", "vol", "低流动", "高流动"], "d_mid_std"),
]


def _match_columns(assumption_text: str, available_cols: list[str]) -> tuple[str | None, str | None]:
    """从 assumption 文本提取 held_equal(被压成相同的)和 collapsed(被合并的差异)对应的列名。

    返回 (held_equal_col, collapsed_col)。匹配不到 → (None, None)。
    v2 规则: 双通道全词表匹配——
      collapsed 优先取"盲区/差异"文本段(认知盲区+equivalent_states)命中的列;
      held 取"假设主体"(assumption 文本)命中且与 collapsed 不同的列;
      两通道独立, 都走完整词表(不再限定 held 候选池), 互不同列。
    """
    text_all = assumption_text.lower()
    # 盲区段: collapsed 的语义主场(描述"被压掉什么")
    text_blind = ""
    for sep in ("认知盲区", "equivalent_states"):
        idx = text_all.find(sep)
        if idx >= 0:
            text_blind += " " + text_all[idx:]
    text_blind = text_blind or text_all

    def _first_hit(text: str, exclude: set[str]) -> str | None:
        for keywords, col in _load_lexicon():
            if col not in available_cols or col in exclude:
                continue
            if any(kw.lower() in text for kw in keywords):
                return col
        return None

    # 通道 1: collapsed 从盲区段找(差异维度的语义主场)
    collapsed_col = _first_hit(text_blind, set())
    # 通道 2: held 从全文找, 排除 collapsed
    held_col = _first_hit(text_all, {collapsed_col} if collapsed_col else set())

    # 兜底: 任一侧缺, 从另一段补
    if held_col and not collapsed_col:
        collapsed_col = _first_hit(text_all, {held_col})
    if collapsed_col and not held_col:
        held_col = _first_hit(text_all, {collapsed_col})

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


# ── v2: investigation 管线接线(契约结构 + 分裂检测 + 假阳性抑制) ──
# 实测基线(143 假设/60 裁定): 程序 CONTRADICTS 精确率 22%, UNCLEAR 率 40%,
# A10 型真矛盾(per-bin 跨零分裂)被平均成边界值。v2 三项修正:
#   1. CONDITIONAL_SPLIT 新档: per-bin 跨零 + spread>0.04 直接标出, 不再依赖平均
#   2. CONTRADICTS 加方向一致性(≥80% bin 同号), 抑制单 bin 带飞的假阳性
#   3. 列匹配不到 → UNTESTABLE(盲区登记素材), 与证据 UNCLEAR 分流, 裁判不审空案


def _split_and_consistency(per_bin: list[dict]) -> dict:
    """per-bin 偏 IC 的分裂检测 + 方向一致性。"""
    ics = [b["ic_collapsed"] for b in per_bin or []]
    if not ics:
        return {"n_bins": 0, "sign_flip": False, "spread": 0.0, "consistency": 0.0}
    pos = sum(1 for x in ics if x > 0)
    neg = sum(1 for x in ics if x < 0)
    return {
        "n_bins": len(ics),
        "sign_flip": pos > 0 and neg > 0,
        "spread": round(max(ics) - min(ics), 4),
        "consistency": round(max(pos, neg) / len(ics), 2),
    }


def _verdict_v2(avg_ic_collapsed: float, avg_ic_held: float, sc: dict) -> tuple[str, str]:
    """v2 判定: 分裂优先, 平均次之, 一致性把关。"""
    if sc["sign_flip"] and sc["spread"] > 0.04:
        return ("CONDITIONAL_SPLIT",
                f"per-bin IC 跨零分裂(spread={sc['spread']}): collapsed 的信息方向随 held 分位"
                f"翻转——条件化信息, 直接送 adjudicator(勿看平均值)")
    if (abs(avg_ic_collapsed) > 0.02
            and abs(avg_ic_collapsed) > abs(avg_ic_held) * 0.3
            and sc["consistency"] >= 0.8):
        return ("CONTRADICTS",
                f"控制后偏 IC={avg_ic_collapsed:.4f}(>0.02)且 {int(sc['consistency'] * 100)}% "
                f"bin 同号, 携带方向一致的额外信息")
    if abs(avg_ic_collapsed) < 0.005:
        return ("SUPPORTS",
                f"控制后偏 IC={avg_ic_collapsed:.4f}(<0.005), 无额外信息")
    return ("UNCLEAR",
            f"偏 IC={avg_ic_collapsed:.4f} 边界或方向不一致(consistency={sc['consistency']}), "
            f"需 adjudicator")


def investigate_v2(assumptions: list[dict], xname: str, y_horizon: str = "1",
                   contracts: dict[str, dict] | None = None) -> dict:
    """investigation 管线版: 契约摘要 + 分裂检测 + 假阳性抑制 + 可测试性分离。

    contracts: cog-concept-compiler agent 的编译产物 {assumption_id: contract}。
    有 contract 的假设直接执行(held/collapsed 由 agent 角色分配, 精确);
    无 contract 的回退词表双通道匹配(快但有角色反转风险)。
    输出 schema 与 legacy 兼容(同字段 + 新增 split_detect/contract_digest/testability),
    adjudicator prompt 无需改。guidance 更新: UNTESTABLE 不派裁判(走盲区登记)。
    """
    print(f"[evidence-v2] 加载 14 探针 + derive 89 维度...", file=sys.stderr)
    df = derive(load_raw(days=None))
    available_cols = [c for c in df.columns if c not in ["receive_time", "weight"]
                      and not c.startswith("X.") and not c.startswith("Y.")]
    y_candidates = [c for c in df.columns if "PriceMid" in c and f"@{y_horizon}" in c]
    if not y_candidates:
        return {"error": f"找不到 Y 列(horizon={y_horizon})"}
    y_col = y_candidates[0]
    print(f"[evidence-v2] Y={y_col[:50]}, 派生维度={len(available_cols)}, "
          f"contracts={len(contracts or {})}/{len(assumptions)}", file=sys.stderr)

    results = []
    for a in assumptions:
        aid = a.get("id", "?")
        c = (contracts or {}).get(aid)
        if c and c.get("held_col") in available_cols and c.get("collapsed_col") in available_cols:
            held_col, collapsed_col = c["held_col"], c["collapsed_col"]
            source = "agent_contract"
        else:
            text = a.get("assumption", "") + " " + a.get("认知盲区", "") + " " + a.get("equivalent_states", "")
            held_col, collapsed_col = _match_columns(text, available_cols)
            source = "lexicon_fallback"

        if not held_col or not collapsed_col:
            results.append({
                "assumption_id": aid,
                "programmatic_verdict": "UNTESTABLE",
                "testability": "UNMATCHED",
                "reason": f"概念在派生维度中无对应列(held={held_col}, collapsed={collapsed_col})"
                          f"——盲区登记素材, 非证据不足, 不派 adjudicator",
                "matched_held_col": held_col, "matched_collapsed_col": collapsed_col,
            })
            continue

        slice_result = _conditional_slice_ic(df, held_col, collapsed_col, y_col)
        sc = _split_and_consistency(slice_result.get("per_bin"))
        verdict, reason = _verdict_v2(slice_result.get("avg_ic_collapsed", 0.0),
                                      slice_result.get("avg_ic_held", 0.0), sc)
        results.append({
            "assumption_id": aid,
            "assumption": a.get("assumption", "")[:120],
            "matched_held_col": held_col,
            "matched_collapsed_col": collapsed_col,
            "programmatic_verdict": verdict,
            "reason": reason,
            "n": slice_result.get("n"),
            "avg_ic_collapsed": slice_result.get("avg_ic_collapsed"),
            "avg_ic_held": slice_result.get("avg_ic_held"),
            "per_bin": slice_result.get("per_bin"),
            "split_detect": sc,
            "testability": "TESTED",
            "match_source": source,
            "contract_digest": {
                "held_equal": held_col,
                "collapsed": collapsed_col,
                "competing_predictions": {
                    "H_collapse": f"若等价失效, Y 应随 {collapsed_col} 分位单调变化",
                    "H_conditional": f"若信息条件化, {collapsed_col} 的 IC 随 {held_col} 分位变号",
                    "H0": f"Y 不随 {collapsed_col} 变化(等价成立)",
                },
            },
        })
        print(f"  {aid}: {verdict} — {reason}", file=sys.stderr)

    def _count(v):
        return sum(1 for r in results if r["programmatic_verdict"] == v)

    summary = {v: _count(v) for v in
               ("CONTRADICTS", "CONDITIONAL_SPLIT", "SUPPORTS", "UNCLEAR", "UNTESTABLE")}

    return {
        "xname": xname,
        "mode": "investigation",
        "y_col": y_col[:60],
        "n_samples": len(df),
        "n_assumptions": len(assumptions),
        "summary": summary,
        "results": results,
        "guidance": (
            f"CONTRADICTS({summary['CONTRADICTS']}) 与 CONDITIONAL_SPLIT({summary['CONDITIONAL_SPLIT']})"
            f" 派 adjudicator 语义确认(后者重点审分裂结构); "
            f"SUPPORTS({summary['SUPPORTS']}) 程序化已判; "
            f"UNCLEAR({summary['UNCLEAR']}) 需 adjudicator; "
            f"UNTESTABLE({summary['UNTESTABLE']}) 不派裁判——盲区登记素材"
        ),
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
    ap.add_argument("--mode", default="investigation",
                    choices=["investigation", "legacy"],
                    help="investigation=v2 管线(分裂检测+假阳性抑制+UNTESTABLE 分流); "
                         "legacy=旧关键词平均判定(回放对照用)")
    ap.add_argument("--contracts-file",
                    help="cog-concept-compiler agent 产物: {assumption_id: {held_col, collapsed_col, ...}}。"
                         "有 contract 的假设跳过词表匹配直接执行")
    args = ap.parse_args()

    if args.assumptions_file:
        assumptions = json.loads(Path(args.assumptions_file).read_text())
    elif args.assumption:
        assumptions = [json.loads(args.assumption)]
    else:
        ap.error("需 --assumption 或 --assumptions-file")

    contracts = None
    if args.contracts_file:
        contracts = json.loads(Path(args.contracts_file).read_text())

    if args.mode == "legacy":
        card = investigate(assumptions, args.xname, args.y_horizon)
    else:
        card = investigate_v2(assumptions, args.xname, args.y_horizon, contracts=contracts)
    print(json.dumps(card, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
