#!/usr/bin/env python3
"""A3 真检验: 控制 imb(F) + d_imb(新息) 后, 按 phase_raw(突发/累积) 分层看 Y。

minimal-repair 的精确路径: 之前 A3 用 d_bp rank(单点新息)只触到新息层(N3)。
现在用原始字段派生的 phase_raw(burst/run 组合), 控制 imb + d_imb 后看 phase 是否
仍有独立 Y 增量 → 触到"形成相位结构"(N3 之外)。

phase_raw = burst_score / (run_length + 1): 高=突发(单步大跳短 run), 低=累积(小步长 run)
"""
import sys
sys.path.insert(0, "factor_db")
from cog_protocol.evidence_derive import load_raw, derive, conditional_slice
from pathlib import Path

# 默认 5 天验证, 传 "all" 跑全样本
arg = sys.argv[1] if len(sys.argv) > 1 else "5"
if arg == "all":
    days = None
else:
    all_d = sorted(Path("/home/lgao/tmp/factor-vec-cache/RawBidSize0/dailyX").glob("daily-*.xy"))
    days = [d.name.replace("daily-", "").replace(".xy", "") for d in all_d[:int(arg)]]

print(f"加载 {len(days) if days else '全部'} 天...")
df = load_raw(days)
df = derive(df)
print(f"  {len(df)} 行")

# 找 Y@1 列
y_col = [c for c in df.columns if "PriceMid>.SHFE-AG@1" == c[-22:]]
if not y_col:
    y_col = [c for c in df.columns if "@1" in c and "PriceMid" in c and "@1" == c.split("AG@")[-1][:2]]
y_col = y_col[0] if y_col else [c for c in df.columns if "PriceMid" in c][0]
print(f"Y col: {y_col}")

# A3 真检验: 控制 imb + d_imb, 按 phase_raw 分层
g, sub = conditional_slice(df, match_cols=["imb", "d_imb"],
                           stratify_col="phase_raw", y_col=y_col,
                           n_match_bins=3, n_strat_bins=3)
print(f"\n=== (imb_q × d_imb_q × phase_q) → mean_Y@1 ===")
piv = g.pivot_table(index=["_mbin_imb", "_mbin_d_imb"], columns="_sbin", values="mean")
if "q1" in piv.columns and "q3" in piv.columns:
    piv["Δ(q3-q1)"] = piv["q3"] - piv["q1"]
    print(piv.round(5).to_string())
    delta_mean = piv["Δ(q3-q1)"].mean()
    delta_pos = (piv["Δ(q3-q1)"] > 0).sum()
    print(f"\n控制 imb + d_imb 后, phase_raw(q3-q1) 平均 Y 增量: {delta_mean:.5f}")
    print(f"  正增量组合: {delta_pos}/{len(piv)} (正=突发>累积)")
    # 显著性: 用全样本 phase_raw vs Y@1 偏相关(控制 imb+d_imb)
    import numpy as np
    sub2 = df[[y_col, "imb", "d_imb", "phase_raw"]].dropna()
    # 残差化 Y 和 phase_raw 对 imb+d_imb, 看残差相关
    from numpy.linalg import lstsq
    X = np.c_[np.ones(len(sub2)), sub2["imb"], sub2["d_imb"]]
    y_res = sub2[y_col].values - X @ lstsq(X, sub2[y_col].values, rcond=None)[0]
    p_res = sub2["phase_raw"].values - X @ lstsq(X, sub2["phase_raw"].values, rcond=None)[0]
    if p_res.std() > 1e-9:
        corr = np.corrcoef(p_res, y_res)[0, 1]
        n = len(sub2)
        z = corr * np.sqrt(n)
        print(f"\n偏相关(phase_raw, Y@1 | imb, d_imb): r={corr:.4f}  z≈{z:.1f}  n={n}")
        print("  → r 显著(>|0.005|)且 z>5 = phase 在新息之外有独立信息(N3 之外候选)")
else:
    print(g.to_string())
