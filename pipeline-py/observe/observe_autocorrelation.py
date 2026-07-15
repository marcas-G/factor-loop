"""数据观测工具:收益自相关(Roll 式 bid-ask bounce 签名)。

从 raw mid_price 算快照收益,测各阶自相关。Roll (1984) 的 bid-ask bounce 签名:
  - 1-lag 显著负(收益反转,盘口弹跳)
  - k≥2 趋零(单 lag 现象)
若有 → 认识论缺口型反常:负自相关 ↔ 有效价差的可识别(可反推价差,机制不唯一)。

这是"Y 自身形态"观测(前面扫的都是"量 vs Y")。显著性用 Bartlett 标准误 ±1.96/√N。
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW_DIR = Path("/home/lgao/work/quant/factor-evaluate-tmp/BookSnapshotInfo_raw/BookSnapshotInfo/dailyX")
LAGS = [1, 2, 3, 5, 10]


def autocorr(x: np.ndarray, lag: int) -> float:
    x = x[np.isfinite(x)]
    n = len(x)
    if n < lag + 30:
        return float("nan")
    xm = x - x.mean()
    c0 = float((xm * xm).sum() / n)
    if c0 == 0:
        return float("nan")
    ck = float((xm[:-lag] * xm[lag:]).sum() / n)
    return ck / c0


def observe(days: int, symbol: str, contract: str) -> dict:
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    if not files:
        return {"error": f"无 daily-*.xy 于 {RAW_DIR}"}

    prefix = f"X.{symbol}{contract}@bsi_"
    mid_col = f"{prefix}mid_price"
    ac_by_lag: dict[int, list[float]] = {l: [] for l in LAGS}
    n_per_day: list[int] = []

    for fp in files:
        df = pd.read_csv(fp, usecols=lambda c: c in ("receive_time", mid_col))
        if mid_col not in df.columns:
            continue
        mid = df[mid_col].astype(np.float64).values
        r = np.diff(mid)  # 快照间价格变化(tick 收益)
        n_per_day.append(len(r))
        for l in LAGS:
            ac = autocorr(r, l)
            if np.isfinite(ac):
                ac_by_lag[l].append(ac)

    avg_n = float(np.mean(n_per_day)) if n_per_day else 0.0
    se = 1.96 / np.sqrt(avg_n) if avg_n > 0 else float("inf")  # Bartlett 标准误

    by_lag: dict[str, dict] = {}
    for l in LAGS:
        arr = np.array(ac_by_lag[l])
        if len(arr) == 0:
            continue
        mean_ac = float(arr.mean())
        by_lag[str(l)] = {
            "mean_ac": mean_ac,
            "std": float(arr.std()),
            "n_days": int(len(arr)),
            "pos_ratio": float((arr > 0).mean()),
            "significant": bool(abs(mean_ac) > se),
            "sign": "+" if mean_ac > 0 else "-",
        }

    lag1 = by_lag.get("1", {})
    lag2 = by_lag.get("2", {})
    # Roll 签名: lag1 负显著 ∧ lag2 趋零(单 lag 现象)
    roll_negative = lag1.get("sign") == "-" and lag1.get("significant", False) and lag1.get("pos_ratio", 1) < 0.25
    lag2_small = abs(lag2.get("mean_ac", 1.0)) < se
    roll_signature = bool(roll_negative and lag2_small)

    return {
        "observation": "return_autocorrelation",
        "symbol": f"{symbol}{contract}",
        "n_days": len(files),
        "avg_samples_per_day": avg_n,
        "bartlett_se": float(se),
        "by_lag": by_lag,
        "roll_bounce_signature": roll_signature,
        "lag1_ac": lag1.get("mean_ac", float("nan")),
        "summary": (
            f"收益自相关 lag1={lag1.get('mean_ac', 0):+.4f}(正天{lag1.get('pos_ratio', 0):.0%}, "
            f"{'显著' if lag1.get('significant') else '不显著'}), "
            f"lag2={lag2.get('mean_ac', 0):+.4f}; "
            f"{'Roll bounce签名(1-lag负显著+k≥2趋零)' if roll_signature else '非Roll签名'}"
        ),
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from observe_common import emit

    p = argparse.ArgumentParser(description="收益自相关观测(Roll 式)")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--symbol", default="SHFE-AG")
    p.add_argument("--contract", default="")
    p.add_argument("--out", default=None, help="写 JSON 到文件(默认 print)")
    a = p.parse_args()
    res = observe(a.days, a.symbol, a.contract)
    res["axiom_code"] = "roll_bounce"
    # 违反 Roll 预期(应有 1-lag 负显著 ∧ k≥2 趋零)时填 violation;符合则 None(非矛盾,不导入)
    res["violation"] = None if res.get("roll_bounce_signature") else (
        "roll_bounce_signature=False(实测无 1-lag 负显著 ∧ k≥2 趋零)"
    )
    emit(res, a.out)
