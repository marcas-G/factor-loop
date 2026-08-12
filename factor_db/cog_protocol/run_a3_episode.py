#!/usr/bin/env python3
"""A3 Step 3: episode 对象构造 + 归属分层(evidence 对象层)。

从"统计量分层"(phase_raw=burst/run)升级到"对象归属分层":
- 构造 ShockEpisode(冲击) / TrendEpisode(趋势) 对象(生灭规则)
- 给每个样本标注 episode_type + episode_phase
- 控制 imb(F) + d_imb(新息) 后, 按 episode 归属看 Y

攻 Phase 4 的门: episode 归属 ≠ N3 统计量(统计描述序列 ≠ 把样本归到对象)。
"""
import sys
sys.path.insert(0, "factor_db")
import numpy as np
import pandas as pd
from pathlib import Path
from cog_protocol.evidence_derive import load_raw, derive


def detect_episodes(df, vol_win=20, shock_z=2.0, trend_k=5, trend_step_max=0.8,
                    settle_steps=5, settle_z=0.5):
    """检测冲击/趋势 episode, 标注每行 episode_type + episode_phase。"""
    df = df.copy()
    df["d_mid"] = df["mid"].diff()
    df["mid_std"] = df["d_mid"].rolling(vol_win).std()
    df["d_mid_z"] = df["d_mid"] / (df["mid_std"] + 1e-9)

    n = len(df)
    z = df["d_mid_z"].fillna(0).values
    ep_type = np.array(["none"] * n, dtype=object)
    ep_phase = np.array(["none"] * n, dtype=object)

    def mark(start, end, etype, phases):
        length = max(end - start, 1)
        for k in range(start, min(end, n)):
            ep_type[k] = etype
            frac = (k - start) / length
            ep_phase[k] = phases[0] if frac < 0.33 else (phases[1] if frac < 0.66 else phases[2])

    i = 0
    while i < n:
        if abs(z[i]) > shock_z:                            # 冲击起点
            start = i; j = i + 1; settle = 0
            while j < n:
                if abs(z[j]) < settle_z:
                    settle += 1
                    if settle >= settle_steps: break
                else: settle = 0
                j += 1
            mark(start, j + 1, "shock", ["shock_start", "shock_mid", "shock_dissipate"])
            i = j + 1; continue
        if i + trend_k < n:                                # 趋势起点(连续小同向)
            window = z[i:i + trend_k]
            signs = np.sign(window)
            if (signs > 0).all() or (signs < 0).all():
                mabs = np.abs(window).mean()
                if 1e-9 < mabs < trend_step_max:
                    start = i; sgn = signs[0]; j = i + trend_k
                    while j < n and np.sign(z[j]) == sgn and abs(z[j]) < trend_step_max * 2:
                        j += 1
                    mark(start, j, "trend", ["trend_start", "trend_mid", "trend_exhaust"])
                    i = j; continue
        i += 1

    df["episode_type"] = ep_type
    df["episode_phase"] = ep_phase
    return df


def episode_evidence(df, match_cols, y_col, n_match_bins=3):
    """控制 match_cols(数值桶) 后, 按 episode_phase(类别) 看 Y。"""
    sub = df.dropna(subset=match_cols + ["episode_phase", y_col]).copy()
    for c in match_cols:
        sub[f"_mbin_{c}"] = pd.qcut(sub[c].rank(method="first"), n_match_bins,
                                     labels=[f"q{i+1}" for i in range(n_match_bins)])
    mbin = [f"_mbin_{c}" for c in match_cols]
    g = sub.groupby(mbin + ["episode_phase"], observed=True)[y_col].agg(["mean", "count"]).reset_index()
    return g, sub


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "5"
    if arg == "all":
        days = None
    else:
        all_d = sorted(Path("/home/lgao/tmp/factor-vec-cache/RawBidSize0/dailyX").glob("daily-*.xy"))
        days = [d.name.replace("daily-", "").replace(".xy", "") for d in all_d[:int(arg)]]

    print(f"加载 {len(days) if days else '全部'} 天...")
    df = load_raw(days)
    df = derive(df)
    df = detect_episodes(df)
    print(f"  {len(df)} 行")

    print(f"\n=== episode 归属分布 ===")
    vc = df["episode_phase"].value_counts()
    for k, v in vc.items():
        print(f"  {k}: {v} ({v/len(df)*100:.1f}%)")

    y_col = [c for c in df.columns if "PriceMid>.SHFE-AG@1" == c[-22:]]
    y_col = y_col[0] if y_col else [c for c in df.columns if "PriceMid" in c][0]

    g, sub = episode_evidence(df, ["imb", "d_imb"], y_col)
    print(f"\n=== 控制 imb+d_imb 后, episode_phase → Y@1 ===")
    piv = g.pivot_table(index=["_mbin_imb", "_mbin_d_imb"], columns="episode_phase",
                        values="mean", observed=True)
    print(piv.round(5).to_string())

    # 偏回归: 控制 imb+d_imb 后 episode_type 对 Y 的 R² 增量
    # 关键判定: 再加 burst_score(N3 统计) 控制, 看 episode 增量是否保留
    from numpy.linalg import lstsq
    sub2 = df[[y_col, "imb", "d_imb", "burst_score", "episode_type"]].dropna()
    sub2 = sub2[sub2["episode_type"].isin(["none", "shock"])]  # trend 太少去掉
    print(f"\n=== 偏回归(只看 none vs shock, n={len(sub2)}) ===")
    # 基线 1: imb + d_imb
    b1 = np.c_[np.ones(len(sub2)), sub2["imb"].values, sub2["d_imb"].values]
    r1 = sub2[y_col].values - b1 @ lstsq(b1, sub2[y_col].values, rcond=None)[0]
    ss1 = (r1 ** 2).sum()
    dummies = pd.get_dummies(sub2["episode_type"], drop_first=True).values.astype(float)
    # 加 episode: 在 imb+d_imb 之上
    Xe = np.c_[b1, dummies]
    re = sub2[y_col].values - Xe @ lstsq(Xe, sub2[y_col].values, rcond=None)[0]
    sse = (re ** 2).sum()
    r2_inc_episode = (ss1 - sse) / ss1
    # 基线 2: imb + d_imb + burst_score(N3)
    b2 = np.c_[b1, sub2["burst_score"].values]
    r2 = sub2[y_col].values - b2 @ lstsq(b2, sub2[y_col].values, rcond=None)[0]
    ss2 = (r2 ** 2).sum()
    # 加 episode: 在 imb+d_imb+burst_score 之上(关键!)
    Xe2 = np.c_[b2, dummies]
    re2 = sub2[y_col].values - Xe2 @ lstsq(Xe2, sub2[y_col].values, rcond=None)[0]
    sse2 = (re2 ** 2).sum()
    r2_inc_episode_over_burst = (ss2 - sse2) / ss2
    print(f"  episode 在 [imb+d_imb] 之上的 R²_inc:            {r2_inc_episode:.6f}")
    print(f"  episode 在 [imb+d_imb+burst_score] 之上的 R²_inc: {r2_inc_episode_over_burst:.6f}  ← 关键")
    print(f"  (若后者≈0 → episode 只是 burst 的重新包装, N3 能接)")
    print(f"  (若后者>0 且显著 → episode 归属在 N3 统计之外有独立信息 → 可能 IRREDUCIBLE)")
    print(f"\n  burst_score 在 [imb+d_imb] 之上的 R²_inc(对照): {(ss1-ss2)/ss1:.6f}")
