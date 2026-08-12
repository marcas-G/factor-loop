#!/usr/bin/env python3
"""Case A probe1 —— 乘积分解等价性(零提交 proxy 版)。

用缓存现成因子对实例化 (signal, gate):
  signal = BsiDepthWeightedImbalanceRank   (深度加权失衡强度)
  gate   = CancelPrecursorDerivSignGate    (撤单前兆门控)
  product = signal × gate (归一后)

Contract T-A-1 编译:
  MATCH   product 分位分箱(等 product 分位 = 表面等价)
  STRATIFY gate 分位(high/low) + signal 分位 —— 分解维度
  COMPARE Y@h 条件均值/命中率
  H1 预言: 等 product 下 gate 分位↑ → E[Y] 单调↑
  H2 预言: 等 product 下 signal 分位驱动差异(非单调或反向)
  H0 预言: 无差异
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "factor_db"))

import numpy as np
import pandas as pd

from cog_protocol.investigation import xycache, evidence_card

SIGNAL_F = "BsiDepthWeightedImbalanceRank"
GATE_F = "CancelPrecursorDerivSignGate"
DAYS = ["20240102", "20240103", "20240104"]  # 首 3 天(验证用);全量 None

CONTRACT = json.loads(Path(ROOT / "logs" / "cog_protocol" / "investigation" / "contract_T-A-1.json").read_text())


def main():
    df = xycache.load_multi({"signal": (SIGNAL_F, DAYS), "gate": (GATE_F, DAYS)})
    # signal/gate 的 AG 主列:列名形如 signal__X.SHFE-AG@...,子 feed 带 @1@ 后缀
    s_col = [c for c in df.columns if c.startswith("signal__X.") and "SHFE-AG@" in c and "@1@" not in c][0]
    g_col = [c for c in df.columns if c.startswith("gate__X.") and "SHFE-AG@" in c and "@1@" not in c][0]
    df["signal"] = df[s_col]
    df["gate"] = df[g_col]

    # 归一(乘积分解对尺度假定):rank 化到 [-1,1] 再乘,product 分位
    df["signal_r"] = df["signal"].rank(pct=True) * 2 - 1
    df["gate_r"] = df["gate"].rank(pct=True) * 2 - 1
    df["product"] = df["signal_r"] * df["gate_r"]

    # MATCH: product 等分位(表面等价桶)
    df["product_q"] = pd.qcut(df["product"].rank(method="first"), 5,
                              labels=["p1", "p2", "p3", "p4", "p5"])
    # STRATIFY: gate / signal 分位(分解维度)
    df["gate_q"] = pd.qcut(df["gate_r"].rank(method="first"), 3,
                           labels=["g_low", "g_mid", "g_high"])
    df["signal_q"] = pd.qcut(df["signal_r"].rank(method="first"), 3,
                             labels=["s_low", "s_mid", "s_high"])

    y_col = "Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1"
    df["y"] = df[y_col]

    # 主分析:等 product 中间分位下,gate 分位 × E[Y](H1)+ signal 分位 × E[Y](H2)
    sub = df[df["product_q"] == "p3"]  # 中间 product 桶(表面等价样本)
    def _grp(col):
        out = []
        for q, g in sub.groupby(col, observed=True):
            out.append({"quantile": str(q), "n": len(g),
                        "mean_y": float(g["y"].mean()),
                        "hit_rate": float((g["y"] > 0).mean()),
                        "std_y": float(g["y"].std())})
        return out

    out = {"y_horizon": "1", "n_total": len(df),
           "n_matched": len(sub), "days": DAYS,
           "signal_factor": SIGNAL_F, "gate_factor": GATE_F,
           "by_dim": {"gate": _grp("gate_q"), "signal": _grp("signal_q")}}

    # Evidence Card(用 H1/H2/H0 对照)
    ev = evidence_card.build_evidence(out, CONTRACT, observed_incompat_strength="INDIRECT")
    Path(ROOT / "logs" / "cog_protocol" / "investigation").mkdir(parents=True, exist_ok=True)
    (Path(ROOT / "logs" / "cog_protocol" / "investigation" / "evidence_T-A-1_probe1.json")
     ).write_text(json.dumps(ev, ensure_ascii=False, indent=2))
    print(json.dumps(ev, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
