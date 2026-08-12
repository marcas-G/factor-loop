"""逐样本 .xy 缓存加载与 JOIN 引擎。

/Users 无此数据 —— 数据在 /home/lgao/tmp/factor-vec-cache/<Factor>/dailyX/daily-YYYYMMDD.xy
列: receive_time, weight, X×10(5品种×主力/@1), Y×5(AG@h1/5/10/60/300)

关键事实:不同因子的 .xy 按 receive_time 行集完全一致(35541/35541 全交集)
→ 多因子可 JOIN 得到同一时刻多坐标 + 未来收益,这是 probe 的逐样本弹药。
"""
import pandas as pd
from pathlib import Path

CACHE_ROOT = Path("/home/lgao/tmp/factor-vec-cache")
Y_COLS = ["Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1", "Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@5",
          "Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@10", "Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@60",
          "Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@300"]


def list_cached_factors() -> list:
    """缓存里有哪些因子。"""
    if not CACHE_ROOT.exists():
        return []
    return sorted(p.name for p in CACHE_ROOT.iterdir() if (p / "dailyX").exists())


def load_days(factor: str, days: list) -> pd.DataFrame:
    """加载某因子若干天的 .xy,合并。返回 [receive_time, X..., Y...]。

    days: 如 ["20240102", "20240103"];或 None=全部天。
    只取该因子的 X 列(第 3~12 列)+ 共享的 Y 列。
    """
    d = CACHE_ROOT / factor / "dailyX"
    if not d.exists():
        raise FileNotFoundError(f"缓存不存在: {d}")
    if days is None:
        files = sorted(d.glob("daily-*.xy"))
    else:
        files = [d / f"daily-{day}.xy" for day in days]
    frames = []
    for f in files:
        if not f.exists():
            continue
        df = pd.read_csv(f)
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"无数据: {factor} {days}")
    out = pd.concat(frames, ignore_index=True)
    return out


def load_multi(factors: dict) -> pd.DataFrame:
    """多因子按 receive_time JOIN。factors: {label: (factor_name, days)}。

    返回: receive_time + weight + 每因子 X 列(自动改名为 {label}__{orig_x_col})
            + Y 列(只保留一份,各因子相同)。
    """
    joined = None
    y_cols = None
    for label, (fname, days) in factors.items():
        df = load_days(fname, days)
        x_cols = [c for c in df.columns if c.startswith("X.")]
        # 保留 @1 子 feed 区分: X.SHFE-AG@main → {label}__X.SHFE-AG;X.SHFE-AG@1@sub → {label}__X.SHFE-AG@1
        rename = {c: f"{label}__{c}" for c in x_cols}
        keep = df[["receive_time"] + x_cols + Y_COLS].rename(columns=rename)
        if y_cols is None:
            y_cols = Y_COLS
        if joined is None:
            joined = keep
        else:
            joined = joined.merge(keep[["receive_time"] + [c for c in keep.columns if c.startswith(label)]],
                                  on="receive_time", how="inner")
    return joined


def concat_joined(factor_list: list, days=None) -> pd.DataFrame:
    """简单版:多个因子拼接(每因子只留 X 主列,receive_time 对齐由调用方 merge)。"""
    frames = []
    for fname in factor_list:
        df = load_days(fname, days)
        frames.append(df)
    return frames
