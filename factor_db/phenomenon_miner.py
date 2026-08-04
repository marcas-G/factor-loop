#!/usr/bin/env python3
"""Phase 1 每日 IC 现象矿工：factor_ic_daily → 高置信研究行为分歧。

范围：当前只有逐日 IC 向量（无快照级状态），因此发现的是"研究行为现象"：
  1. CROSS_FEED_SCALE_MISMATCH  同一测量问题在主力/@1 两个流动性层级的预测行为持续分歧
  2. MIRROR_BEHAVIOR_ASYMMETRY  库内镜像对（IC 序列 ≈ -1 相关）行为不对称
  3. REGIME_EFFECT_DIVERGENCE   前/后半期 ICIR 翻转或塌缩（时间 regime 分歧）

三级筛选（宁缺毋滥）：
  - 最小覆盖: 共享有效天数 >= MIN_VALID_DAYS(30), 每侧 >= MIN_DAYS_PER_SIDE(15)
  - 持续性:   滚动块中支配方向一致 >= PERSIST_FRACTION(0.75)
  - 稳健性:   去掉 3 个极端 |IC| 天后结论仍成立

输出：detections JSON（供 card_builder 转方向中性现象卡）。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from db import get_conn  # noqa: E402

MIN_VALID_DAYS = 30
MIN_DAYS_PER_SIDE = 15
PERSIST_FRACTION = 0.75
PERSIST_BLOCK = 20          # 滚动块天数
ROBUST_DROP = 3             # 稳健性: 去掉的极端天数
MIRROR_CORR = -0.85         # 镜像对阈值
EFF_ICIR = 0.3              # 有效侧 ICIR 门槛（与 assess 一致）
EFF_IC = 0.005              # 有效侧 |mean IC| 门槛
FLIP_ICIR = 0.3             # regime 翻转门槛
COLLAPSE_ICIR = 0.1         # regime 塌缩门槛
MAG_RATIO = 2.0             # 镜像不对称幅度比门槛

OUT = Path(__file__).resolve().parent / "concept_cards" / "detections.json"


# ---------------------------------------------------------------- 数据装载
def load_series(conn):
    """factor → horizon → feed → {date: ic}。feed: 'main' | 'sub' | 'legacy'。"""
    rows = conn.execute("""
        SELECT factor_xname, date, freq, y_horizon, ic FROM factor_ic_daily
        WHERE symbol='SHFE-AG'
    """).fetchall()
    series = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for fx, date, freq, h, ic in rows:
        if freq == "default:main":
            feed = "main"
        elif freq == "default:sub":
            feed = "sub"
        else:
            feed = "legacy"
        series[fx][h][feed][date] = ic
    return series


def to_vec(d):
    return {k: v for k, v in sorted(d.items())}


def shared_dates(a, b):
    return sorted(set(a) & set(b))


def icir(vec):
    if len(vec) < 5:
        return 0.0
    v = np.array(list(vec.values()), dtype=float)
    s = v.std()
    return float(v.mean() / s) if s > 1e-12 else 0.0


def mean_abs(vec):
    v = np.array(list(vec.values()), dtype=float)
    return float(np.abs(v).mean()) if len(v) else 0.0


def effective(vec):
    v = np.array(list(vec.values()), dtype=float)
    return len(v) >= MIN_DAYS_PER_SIDE and abs(icir(vec)) >= EFF_ICIR and abs(v.mean()) >= EFF_IC


def drop_extreme(vec, k=ROBUST_DROP):
    """去掉 k 个最大 |IC| 天后的序列。"""
    items = sorted(vec.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return dict(items[k:])


def block_direction(vec, date_order, relation, need=10):
    """滚动块内支配方向一致率。relation(dict_block) -> +1/-1/0。"""
    agrees, total = 0, 0
    dates = [d for d in date_order if d in vec]
    for i in range(0, len(dates), PERSIST_BLOCK):
        blk = dates[i:i + PERSIST_BLOCK]
        if len(blk) < need:
            continue
        d = relation({k: vec[k] for k in blk if k in vec})
        if d == 0:
            continue
        total += 1
        agrees += 1 if d > 0 else 0
    return agrees / total if total else 0.0


# ---------------------------------------------------------------- 检测1: 跨 feed 尺度失配
def detect_scale_mismatch(series):
    dets = []
    for fx, by_h in series.items():
        if "main" not in by_h.get(1, {}) or "sub" not in by_h.get(1, {}):
            continue  # 仅新格式双 feed 因子可检
        for h, feeds in by_h.items():
            m, s = feeds.get("main", {}), feeds.get("sub", {})
            sd = shared_dates(m, s)
            if len(sd) < MIN_VALID_DAYS:
                continue
            mf, sf = {d: m[d] for d in sd}, {d: s[d] for d in sd}
            ir_m, ir_s = icir(mf), icir(sf)
            eff_m, eff_s = effective(mf), effective(sf)
            sign_flip = (ir_m >= EFF_ICIR and ir_s <= -EFF_ICIR) or (ir_m <= -EFF_ICIR and ir_s >= EFF_ICIR)
            eff_diff = eff_m != eff_s
            mag_gap = abs(mean_abs(mf) - mean_abs(sf)) >= 0.004
            if not (sign_flip or eff_diff or mag_gap or abs(ir_m - ir_s) >= 1.0):
                continue
            # 持续性: 支配方向(|μ| 谁大) 滚动块一致
            dom_main = mean_abs(mf) > mean_abs(sf)
            rel = lambda blk: (1 if (mean_abs(blk) > mean_abs({d: s[d] for d in blk})) else -1) if dom_main \
                else (-1 if (mean_abs(blk) > mean_abs({d: s[d] for d in blk})) else 1)
            persist = block_direction(mf, sd, rel)
            # 稳健性: 去极端后失配仍成立
            mf_r, sf_r = drop_extreme(mf), drop_extreme(sf)
            ir_mr, ir_sr = icir(mf_r), icir(sf_r)
            robust = (sign_flip and ((ir_mr >= EFF_ICIR and ir_sr <= -EFF_ICIR) or (ir_mr <= -EFF_ICIR and ir_sr >= EFF_ICIR))) or \
                     (eff_diff and effective(mf_r) != effective(sf_r)) or \
                     (mag_gap and abs(mean_abs(mf_r) - mean_abs(sf_r)) >= 0.004)
            if persist < PERSIST_FRACTION or not robust:
                continue
            dets.append({
                "type": "CROSS_FEED_SCALE_MISMATCH",
                "factor": fx, "horizon": h,
                "n_days": len(sd),
                "icir_main": round(ir_m, 3), "icir_sub": round(ir_s, 3),
                "mean_abs_main": round(mean_abs(mf), 4), "mean_abs_sub": round(mean_abs(sf), 4),
                "effective_main": eff_m, "effective_sub": eff_s,
                "sign_flip": bool(sign_flip), "mag_gap": round(abs(mean_abs(mf) - mean_abs(sf)), 4),
                "persistence": round(persist, 2), "robust": bool(robust),
            })
    return dets


# ---------------------------------------------------------------- 检测2: 镜像行为不对称
def detect_mirror_asymmetry(series):
    """自动找 IC≈-1 镜像对, 再检查幅度/有效性/feed 依赖不对称。"""
    # 每因子每 horizon 一条聚合序列: 优先 main, 其次 legacy
    agg = {}
    for fx, by_h in series.items():
        for h, feeds in by_h.items():
            vec = feeds.get("main") or feeds.get("legacy") or feeds.get("sub")
            if vec:
                agg.setdefault(h, {})[fx] = vec

    dets = []
    for h, facs in agg.items():
        names = sorted(facs)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = facs[names[i]], facs[names[j]]
                sd = shared_dates(a, b)
                if len(sd) < 40:
                    continue
                av = np.array([a[d] for d in sd]); bv = np.array([b[d] for d in sd])
                if av.std() == 0 or bv.std() == 0:
                    continue
                r = float(np.corrcoef(av, bv)[0, 1])
                if r > MIRROR_CORR:
                    continue
                am, bm = av.mean(), bv.mean()
                mag_ratio = max(abs(am), abs(bm)) / (min(abs(am), abs(bm)) + 1e-12)
                eff_a, eff_b = effective(a), effective(b)
                # 收紧: 两侧都有真实信号 + 至少一侧强 ICIR（过滤随机 -0.85 噪声对）
                if min(abs(am), abs(bm)) < 0.008 or max(abs(icir(a)), abs(icir(b))) < 0.5:
                    continue
                asym = mag_ratio >= MAG_RATIO or eff_a != eff_b
                if not asym:
                    continue
                # 稳健性: 去极端后不对称仍成立
                a_r, b_r = drop_extreme(a), drop_extreme(b)
                r_rob = abs(mean_abs(a_r) / (mean_abs(b_r) + 1e-12))
                robust = (max(r_rob, 1 / max(r_rob, 1e-12)) >= MAG_RATIO) or (effective(a_r) != effective(b_r))
                if not robust:
                    continue
                dets.append({
                    "type": "MIRROR_BEHAVIOR_ASYMMETRY",
                    "factor_a": names[i], "factor_b": names[j], "horizon": h,
                    "n_days": len(sd), "corr": round(r, 3),
                    "mean_a": round(am, 4), "mean_b": round(bm, 4),
                    "icir_a": round(icir(a), 3), "icir_b": round(icir(b), 3),
                    "mag_ratio": round(mag_ratio, 2),
                    "effective_a": eff_a, "effective_b": eff_b,
                    "robust": bool(robust),
                })
    return dets


# ---------------------------------------------------------------- 库基线（去偏）
def library_baseline(series):
    """每 horizon 每半期全体因子的 mean|IC|。用于剔除"跟随库基线"的假分歧。"""
    per = defaultdict(lambda: {"first": [], "second": []})
    for fx, by_h in series.items():
        for h, feeds in by_h.items():
            vec = feeds.get("main") or feeds.get("legacy") or feeds.get("sub")
            if not vec or len(vec) < 2 * MIN_DAYS_PER_SIDE + 10:
                continue
            dates = sorted(vec)
            mid = len(dates) // 2
            h1 = np.array([vec[d] for d in dates[:mid]])
            h2 = np.array([vec[d] for d in dates[mid:]])
            if len(h1) < MIN_DAYS_PER_SIDE or len(h2) < MIN_DAYS_PER_SIDE:
                continue
            per[h]["first"].append(float(np.abs(h1).mean()))
            per[h]["second"].append(float(np.abs(h2).mean()))
    base = {}
    for h, v in per.items():
        if v["first"] and v["second"]:
            base[h] = {"first": float(np.mean(v["first"])), "second": float(np.mean(v["second"]))}
    return base


# ---------------------------------------------------------------- 检测3: 时间 regime 分歧
def detect_regime_divergence(series, baseline):
    dets = []
    for fx, by_h in series.items():
        for h, feeds in by_h.items():
            vec = feeds.get("main") or feeds.get("legacy") or feeds.get("sub")
            if not vec or len(vec) < 2 * MIN_DAYS_PER_SIDE + 10:
                continue
            dates = sorted(vec)
            mid = len(dates) // 2
            h1 = {d: vec[d] for d in dates[:mid]}
            h2 = {d: vec[d] for d in dates[mid:]}
            if len(h1) < MIN_DAYS_PER_SIDE or len(h2) < MIN_DAYS_PER_SIDE:
                continue
            i1, i2 = icir(h1), icir(h2)
            m1 = sum(h1.values()) / len(h1)
            m2 = sum(h2.values()) / len(h2)
            # 严格翻转: 两侧都有效且符号相反（两侧 |mean| 门槛，非噪声翻转）
            flip = (i1 >= FLIP_ICIR and i2 <= -FLIP_ICIR and abs(m1) >= EFF_IC and abs(m2) >= EFF_IC) or \
                   (i1 <= -FLIP_ICIR and i2 >= FLIP_ICIR and abs(m1) >= EFF_IC and abs(m2) >= EFF_IC)
            if not flip:
                continue
            # 稳健性: 去极端后翻转仍成立
            h1_r, h2_r = drop_extreme(h1), drop_extreme(h2)
            i1r, i2r = icir(h1_r), icir(h2_r)
            flip_r = (i1r >= FLIP_ICIR and i2r <= -FLIP_ICIR) or (i1r <= -FLIP_ICIR and i2r >= FLIP_ICIR)
            if not flip_r:
                continue
            # 与库基线的关系（区分"跟库走"与"反库走"）
            b = baseline.get(h, {})
            b1, b2 = b.get("first", 0.0), b.get("second", 0.0)
            if b2 >= b1:
                trend = "WITH_LIBRARY_STRENGTHENING" if abs(m2) >= abs(m1) else "COUNTER_LIBRARY"
            else:
                trend = "WITH_LIBRARY_DECAY" if abs(m2) < abs(m1) else "COUNTER_LIBRARY"
            dets.append({
                "type": "REGIME_EFFECT_DIVERGENCE",
                "factor": fx, "horizon": h,
                "n_days": len(dates), "split": mid,
                "icir_first": round(i1, 3), "icir_second": round(i2, 3),
                "mean_first": round(m1, 4), "mean_second": round(m2, 4),
                "library_first": round(b1, 4), "library_second": round(b2, 4),
                "flip": True, "trend": trend,
                "robust": True,
            })
    return dets


def _json_default(o):
    import numpy as _np
    if isinstance(o, _np.bool_):
        return bool(o)
    if isinstance(o, _np.floating):
        return float(o)
    if isinstance(o, _np.integer):
        return int(o)
    raise TypeError(f"{type(o)} not serializable")


def dedupe(dets, key_fn, score_fn, keep=5):
    """每 key 只保留最强一条，按 score 排序截断 top-k。"""
    best = {}
    for d in dets:
        k = key_fn(d)
        if k not in best or score_fn(d) > score_fn(best[k]):
            best[k] = d
    return sorted(best.values(), key=score_fn, reverse=True)[:keep]


def dedupe_mirror(dets, keep=6):
    """镜像对贪心去重：每因子最多出现一次（按 score 降序取对）。"""
    scored = sorted(dets, key=lambda d: d["mag_ratio"] * max(abs(d["icir_a"]), abs(d["icir_b"])), reverse=True)
    used, out = set(), []
    for d in scored:
        if d["factor_a"] in used or d["factor_b"] in used:
            continue
        used.add(d["factor_a"]); used.add(d["factor_b"])
        out.append(d)
        if len(out) >= keep:
            break
    return out


def main():
    with get_conn() as conn:
        series = load_series(conn)
    base = library_baseline(series)
    scale = dedupe(detect_scale_mismatch(series), lambda d: d["factor"],
                   lambda d: abs(d["icir_main"]) + abs(d["icir_sub"]), keep=6)
    mirror = dedupe_mirror(detect_mirror_asymmetry(series), keep=6)
    regime = dedupe(detect_regime_divergence(series, base), lambda d: d["factor"],
                    lambda d: abs(d["icir_first"]) + abs(d["icir_second"]), keep=6)
    dets = scale + mirror + regime
    # 类型分组排序输出
    by_type = defaultdict(list)
    for d in dets:
        by_type[d["type"]].append(d)
    OUT.write_text(json.dumps(dets, ensure_ascii=False, indent=1, default=_json_default))
    for t, ds in by_type.items():
        print(f"\n=== {t}: {len(ds)} 条 ===")
        for d in ds:
            print("  ", json.dumps(d, ensure_ascii=False, default=_json_default))
    print(f"\n合计 {len(dets)} 条 → {OUT}")


if __name__ == "__main__":
    main()
