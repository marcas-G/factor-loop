#!/usr/bin/env python3
"""Factor Evidence Bridge Validator — Gate C 程序化。

防止 adjudicator 拿一个不对应 assumption 的 evidence 来判(P002 的 OOD 根因前移)。

Bridge valid iff:
  1. evidence.held_fixed ⊇ assumption.held_equal_coordinates
     (evidence 控制了 assumption 要求匹配的所有坐标)
  2. evidence.varied_dimension ∩ assumption.collapsed_difference ≠ ∅
     (evidence 触及了 assumption 声称被压掉的某个维度)

任一不满足 → BRIDGE_INVALID,不进 Adjudicator。

词汇归一:_norm 把中英同义词映射到受控 token(scale/量级/absolute_size → size;
feed/main_sub → feed 等),防 LLM 用同义词绕过程序化检查。
"""
import re

# 受控词汇归一表(小写)。新增同义词往这里加。
_ALIAS = {
    # size / magnitude / scale
    "absolute_size": "size", "abs_size": "size", "size": "size",
    "magnitude": "size", "scale": "size", "量级": "size", "绝对量级": "size",
    "绝对规模": "size", "规模": "size", "幅度": "size", "大小": "size",
    # ratio
    "ratio": "ratio", "比例": "ratio", "比值": "ratio", "相对比": "ratio",
    "归一化比": "ratio",
    # feed
    "feed": "feed", "feed_identity": "feed", "main_sub": "feed",
    "盘口来源": "feed", "主力次主力": "feed", "feed_source": "feed",
    # horizon
    "horizon": "horizon", "time_horizon": "horizon", "预测窗口": "horizon",
    "时间尺度": "horizon", "预测期": "horizon",
    # sign / direction
    "sign": "sign", "direction": "sign", "符号": "sign", "方向": "sign",
    # path / sequence
    "path": "path", "sequence": "path", "路径": "path", "到达序列": "path",
    "preceding_sequence": "path",
    # tempo / timing
    "tempo": "tempo", "timing": "tempo", "节奏": "tempo", "时间分布": "tempo",
    "tick_distribution": "tempo",
    # depth level
    "depth_level": "depth", "level": "depth", "档位": "depth", "深度档": "depth",
    # regime
    "regime": "regime", "状态": "regime", "市场状态": "regime",
}


def _norm_token(t):
    if t is None:
        return None
    t = str(t).strip().lower()
    t = re.sub(r"[\s\-]+", "_", t)
    return _ALIAS.get(t, t)  # 未登记的 token 原样保留(暴露词汇不一致)


def _norm_set(tokens):
    out = set()
    for t in (tokens or []):
        n = _norm_token(t)
        if n:
            out.add(n)
    return out


def validate_bridge(assumption, evidence_test):
    """Gate C。返回 {bridge_valid, missing_hold_fixed, varied_touches_collapsed, reason}。

    assumption: {held_equal_coordinates:[...], collapsed_difference:[...], ...}
    evidence_test: {held_fixed:[...], varied_dimension:[...], behavioral_target:...}
    """
    held_equal = _norm_set(assumption.get("held_equal_coordinates"))
    collapsed = _norm_set(assumption.get("collapsed_difference"))
    held_fixed = _norm_set(evidence_test.get("held_fixed"))
    varied = _norm_set(evidence_test.get("varied_dimension"))

    missing_hold = held_equal - held_fixed
    touches_collapsed = bool(varied & collapsed)

    valid = (not missing_hold) and touches_collapsed and bool(held_equal) and bool(collapsed)

    if not held_equal or not collapsed:
        reason = ("assumption 必须显式列出 held_equal_coordinates 和 collapsed_difference "
                  "(Gate A 未通过,无法程序化验 bridge)")
    elif missing_hold:
        reason = (f"evidence.held_fixed 缺少 assumption 要求匹配的坐标: "
                  f"{sorted(missing_hold)} → conditioning 未闭合 (Gate B/C 失败)")
    elif not touches_collapsed:
        reason = (f"evidence.varied_dimension {sorted(varied)} 未触及 "
                  f"assumption.collapsed_difference {sorted(collapsed)} → "
                  f"evidence 测的根本不是 assumption 声称被压掉的维度 (P002 OOD 根因)")
    else:
        reason = (f"bridge valid: evidence 在 held_fixed={sorted(held_fixed)} 下变化 "
                  f"{sorted(varied & collapsed)}(assumption 声称被压),conditioning 闭合")

    return {
        "bridge_valid": valid,
        "gate": "C",
        "assumption_held_equal": sorted(held_equal),
        "assumption_collapsed": sorted(collapsed),
        "evidence_held_fixed": sorted(held_fixed),
        "evidence_varied": sorted(varied),
        "missing_hold_fixed": sorted(missing_hold),
        "varied_touches_collapsed": touches_collapsed,
        "touched_collapsed_dims": sorted(varied & collapsed),
        "reason": reason,
    }


# ── 受控词汇登记自查(便于扩展)──
def known_tokens():
    return sorted(set(_ALIAS.values()))


if __name__ == "__main__":
    # 自检:F1 ImbalanceBase 的 feed symmetry bridge(应 valid)
    print("=== self-test 1: feed symmetry bridge (应 VALID) ===")
    r = validate_bridge(
        assumption={
            "held_equal_coordinates": ["ratio"],          # F 保持 ratio
            "collapsed_difference": ["feed_identity"],    # formula 不区分 main/sub
        },
        evidence_test={
            "held_fixed": ["ratio"],                       # 同公式同 ratio 桶
            "varied_dimension": ["feed_identity"],         # main vs sub
            "behavioral_target": "IC",
        },
    )
    print(f"  bridge_valid={r['bridge_valid']}  touched={r['touched_collapsed_dims']}")
    print(f"  {r['reason']}")

    print("\n=== self-test 2: horizon decay 套到 scale assumption (应 INVALID, P002 bug) ===")
    r = validate_bridge(
        assumption={
            "held_equal_coordinates": ["ratio"],
            "collapsed_difference": ["absolute_size"],     # scale 被压
        },
        evidence_test={
            "held_fixed": ["ratio"],
            "varied_dimension": ["horizon"],               # 但 evidence 测的是 horizon
            "behavioral_target": "IC",
        },
    )
    print(f"  bridge_valid={r['bridge_valid']}")
    print(f"  {r['reason']}")

    print("\n=== self-test 3: conditioning 未闭合 (应 INVALID, Gate B) ===")
    r = validate_bridge(
        assumption={
            "held_equal_coordinates": ["ratio", "feed_identity"],
            "collapsed_difference": ["absolute_size"],
        },
        evidence_test={
            "held_fixed": ["ratio"],                       # 漏控 feed_identity
            "varied_dimension": ["absolute_size"],
            "behavioral_target": "IC",
        },
    )
    print(f"  bridge_valid={r['bridge_valid']}  missing={r['missing_hold_fixed']}")
    print(f"  {r['reason']}")

    print(f"\nknown tokens: {known_tokens()}")
