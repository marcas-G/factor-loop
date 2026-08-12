#!/usr/bin/env python3
"""Case A probe2 —— conditional-sufficiency test(用户修正版)。

探针 probe_T-A 暴露真实三坐标 sig_coord/gate_coord/prod_coord(rank 前 raw)。
本 probe 检验: product 是否为 (signal, gate) 对任务行为的充分统计量?
  H_充分: E[Y | product, 其余同] 不依赖 (signal, gate) 分解 → product 充分
  H_不充分: 控制 product 后 signal(或 gate)仍有稳定增量 → product 压缩不充分
    → A4 的「乘积标量等价」是过度压缩,challenge 成立

关键(用户修正): signal 自身预测力【不是】需要消除的混杂——若控制 product 后
signal 仍有稳定增量,这本身就是 product 不充分的证据。所以不做"消除 signal IC",
而是做 conditional-sufficiency: matched-product 内 signal 的增量预测。

方法(严格,防 adaptive mining):
1. 全量 117 天(或指定天数),receive_time 严格排序
2. MATCH product: 按 product 分位分层(等频 5 桶),桶内固定 product
3. 桶内 STRATIFY signal 分位(5 桶),COMPARE 未来收益 Y@h
4. OOS: 时间切分 train(前 2/3)/test(后 1/3),方向/效应在 test 上独立复现
5. 检验: 桶内 signal 分层 → Y 的条件均值/命中率是否有单调/稳定差异
   - 显著 → product 不充分(signal 有增量)→ A4 压缩不充分
   - 无差异 → product 充分 → challenge 不支持
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "factor_db"))

import numpy as np
import pandas as pd

from cog_protocol.investigation import xycache

PROBE = "probe_T-A"
SIG, GATE, PROD = "sig_coord", "gate_coord", "prod_coord"
Y = "Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1"


def load_all(days=None):
    df = xycache.load_days(PROBE, days)
    cols = ["receive_time"] + [c for c in df.columns if c.startswith("X.") and "SHFE-AG@" in c] + [Y]
    d = df[cols].copy()
    d = d.rename(columns={c: c.split("@")[-1] for c in d.columns if c.startswith("X.")})
    return d


def _grp_stats(g):
    return {"n": len(g), "mean_y": float(g["y"].mean()),
            "hit_rate": float((g["y"] > 0).mean()), "std_y": float(g["y"].std())}


def run(days=None, out_path="evidence_T-A-1_probe2.json"):
    d = load_all(days)
    d = d[d[PROD].notna() & d[SIG].notna() & d[GATE].notna()].copy()
    d["y"] = d[Y]
    n_total = len(d)

    # OOS 切分:按 receive_time 前 2/3 训练、后 1/3 测试
    d = d.sort_values("receive_time").reset_index(drop=True)
    cut = int(n_total * 2 / 3)
    d["split"] = "train"
    d.loc[cut:, "split"] = "test"

    # MATCH product:等频 5 桶(桶内 product 固定)
    d["prod_q"] = pd.qcut(d[PROD].rank(method="first"), 5, labels=["p1", "p2", "p3", "p4", "p5"])
    # 桶内 STRATIFY signal:等频 5 桶
    d["sig_q"] = pd.qcut(d[SIG].rank(method="first"), 5, labels=["s1", "s2", "s3", "s4", "s5"])

    result = {"y_horizon": "1", "n_total": n_total, "days": days,
              "product_buckets": 5, "signal_buckets_within_product": 5}
    rows = []
    for pq in ["p1", "p2", "p3", "p4", "p5"]:
        sub = d[d["prod_q"] == pq]
        row = {"product_quantile": pq, "n": len(sub)}
        for split in ["train", "test"]:
            s = sub[sub["split"] == split]
            by_sig = []
            for sq in ["s1", "s2", "s3", "s4", "s5"]:
                g = s[s["sig_q"] == sq]
                if len(g) >= 50:
                    by_sig.append({"signal_quantile": sq, **_grp_stats(g)})
            # 单调性:mean_y 随 signal 分位
            if len(by_sig) >= 3:
                ys = [b["mean_y"] for b in by_sig]
                row[f"{split}_mean_by_sig"] = [round(v, 6) for v in ys]
                row[f"{split}_n_by_sig"] = [b["n"] for b in by_sig]
                row[f"{split}_max_effect"] = round(abs(ys[-1] - ys[0]), 6)
                # 简化 z:组间极差 / 池化标准误
                ses = [b["std_y"] / max(np.sqrt(b["n"]), 1) for b in by_sig]
                se = np.sqrt(np.mean(np.array(ses) ** 2))
                row[f"{split}_z"] = round(abs(ys[-1] - ys[0]) / (se + 1e-9), 2)
        rows.append(row)
    result["by_product_quantile"] = rows
    Path(ROOT / "logs" / "cog_protocol" / "investigation").mkdir(parents=True, exist_ok=True)
    (Path(ROOT / "logs" / "cog_protocol" / "investigation") / out_path
     ).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    days = sys.argv[1] if len(sys.argv) > 1 else None
    run(days=days)
