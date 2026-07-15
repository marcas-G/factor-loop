"""收益分布形态观测。

收益的偏度/峰度(肥尾)/波动聚集(|r| 的自相关)。
反常:负偏(下行尾重)/肥尾(峰度>3)/波动聚集(|r|自相关显著,GARCH效应)。
这是 Y 自身的分布形态,不依赖 X。
"""
from __future__ import annotations
import argparse
import json
from observe_common import *


def observe(days, symbol):
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    need = ["receive_time", mid_col(symbol)]
    skew_list, kurt_list, vol_ac1, vol_ac5 = [], [], [], []
    for fp in files:
        df = pd.read_csv(fp, usecols=lambda c: c in need)
        if mid_col(symbol) not in df.columns:
            continue
        r = df[mid_col(symbol)].astype(np.float64).diff().dropna().values
        if len(r) < 200:
            continue
        skew_list.append(float(((r - r.mean()) ** 3).mean() / (r.std() ** 3 + 1e-12)))
        kurt_list.append(float(((r - r.mean()) ** 4).mean() / (r.std() ** 4 + 1e-12)))
        ar = np.abs(r)
        ac1 = float(np.corrcoef(ar[:-1], ar[1:])[0, 1])
        ac5 = float(np.corrcoef(ar[:-5], ar[5:])[0, 1])
        vol_ac1.append(ac1)
        vol_ac5.append(ac5)
    if not skew_list:
        return {"error": "数据不足"}
    n = len(skew_list)
    se = 1.96 / np.sqrt(len(r))
    skew_mean = float(np.mean(skew_list))
    kurt_mean = float(np.mean(kurt_list))
    vac1 = float(np.mean(vol_ac1))
    vac5 = float(np.mean(vol_ac5))
    # 反常判定
    neg_skew = skew_mean < -0.1 and all(s < 0 for s in skew_list)
    fat_tail = kurt_mean > 5  # 显著肥尾(>3 是正态界,>5 强)
    vol_cluster = vac1 > 0.05 and all(v > 0 for v in vol_ac1)
    return {
        "observation": "return_distribution",
        "symbol": symbol, "n_days": n,
        "skewness": skew_mean, "kurtosis": kurt_mean,
        "abs_ret_ac1": vac1, "abs_ret_ac5": vac5,
        "bartlett_se": float(se),
        "neg_skew_significant": bool(neg_skew),
        "fat_tail_significant": bool(fat_tail),
        "vol_cluster_significant": bool(vol_cluster),
        "summary": (
            f"收益 偏度={skew_mean:+.3f}({'负偏★' if neg_skew else '对称'}) "
            f"峰度={kurt_mean:.2f}({'肥尾★' if fat_tail else '正态级'}) "
            f"|r|自相关 ac1={vac1:+.3f}({'聚集★' if vol_cluster else '无聚集'}); "
            f"反常:{' / '.join([x for x,y in [('负偏',neg_skew),('肥尾',fat_tail),('波动聚集',vol_cluster)] if y]) or '无明显分布反常'}"
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--symbol", default="SHFE-AG")
    a = p.parse_args()
    print(json.dumps(observe(a.days, a.symbol), ensure_ascii=False, indent=2))
