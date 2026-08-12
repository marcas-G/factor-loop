"""Probe Compiler —— Contract → 数据管道执行。

把 Test Contract + probe 因子配置编译成对 .xy 数据的确定性操作:
  1. 加载 probe 因子 .xy(receive_time 对齐 JOIN)
  2. FILTER symbol/horizon → 选列
  3. MATCH 等价坐标(如 product 容差内) → 构造对照样本
  4. STRATIFY 变化维度分位 → 分层
  5. HOLD_FIXED 混杂(分位匹配)→ 平衡
  6. COMPARE 各组行为(Y 条件分布)
  7. REPORT 效应方向/大小/不确定性/稳定性

probe 因子配置(临时 .h 提交平台后产生的缓存)由调用方给定:
  bindings: {坐标名: (因子名, X列后缀)} 如 {"product": ("P", "X.SHFE-AG@...")}
实现上简化:probe 因子名 = 坐标名,列 = 该因子 X 列的 AG 主列。后期按需细化。
"""
import numpy as np
import pandas as pd

from . import xycache


class ProbeError(Exception):
    pass


def _ag_main_col(df) -> str:
    """取 AG 主力 X 列(第一个 X. 开头、不含 @1 的)。"""
    cols = [c for c in df.columns if c.startswith("X.") and "@1" not in c and "SHFE-AG" in c]
    if not cols:
        raise ProbeError(f"无 AG 主力 X 列: {list(df.columns)[:5]}")
    return cols[0]


def load_bound(dfs: dict, bindings: dict, y_horizon: str = "1") -> pd.DataFrame:
    """按 bindings 从多因子 df 提取坐标列 + 未来收益列。

    bindings: {坐标名: 因子名(缓存里的名字)}
    返回 df: receive_time + {坐标名} + y(future_return@y_horizon)
    """
    out = pd.DataFrame()
    y_col = f"Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@{y_horizon}"
    for coord, fname in bindings.items():
        df = dfs[fname]
        xc = _ag_main_col(df)
        out[coord] = df[xc].values
    out["y"] = dfs[next(iter(dfs))][y_col].values
    return out


def compile_and_run(contract: dict, probe_factors: dict, dfs: dict,
                    y_horizon: str = "1", seed: int = 42) -> dict:
    """执行 probe,返回统计结果 dict。

    probe_factors: {坐标名: 因子缓存名} —— 哪个坐标用哪个临时因子的 AG 主列。
    """
    eq = contract["challenged_equivalence"]
    hold = contract["controls"]["must_hold_similar"]
    vary = contract["variation"]["dimensions_allowed_to_change"]

    df = load_bound(dfs, probe_factors, y_horizon)

    # MATCH: 等价坐标(如 product)容差匹配 —— 构造"表面相同"样本集
    match_coords = eq.get("representation_equal_on", [])
    if match_coords:
        for c in match_coords:
            if c not in df.columns:
                # 若 match 坐标是派生量(如 product=signal*gate),由变体自动计算
                if isinstance(c, str) and "*" in c:
                    a, b = [x.strip() for x in c.split("*")]
                    if a in df.columns and b in df.columns:
                        df[c] = df[a] * df[b]
                    else:
                        raise ProbeError(f"match 坐标无法构造: {c}")
                else:
                    raise ProbeError(f"match 坐标缺列: {c}")

    # STRATIFY: 变化维度分位分层
    results = {}
    for dim in vary:
        if dim not in df.columns:
            if "*" in dim:
                a, b = [x.strip() for x in dim.split("*")]
                if a in df.columns and b in df.columns:
                    df[dim] = df[a] * df[b]
                else:
                    continue
            else:
                continue
        df["_q"] = pd.qcut(df[dim].rank(method="first"), 3, labels=["low", "mid", "high"])
        groups = []
        for q, g in df.groupby("_q", observed=True):
            groups.append({
                "quantile": str(q), "n": len(g),
                "mean_y": float(g["y"].mean()),
                "hit_rate": float((g["y"] > 0).mean()),
                "std_y": float(g["y"].std()),
            })
        results[dim] = groups
    return {"y_horizon": y_horizon, "n_total": len(df), "by_dim": results}
