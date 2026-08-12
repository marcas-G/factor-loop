#!/usr/bin/env python3
"""Evidence Derive Engine — 从原始 book snapshot 自推断所有分析维度。

不依赖平台 Feed::Cancel/Order/Trade(那些是平台从快照差分推断的不透明中间产物)。
只用 4 个可信原始字段(bid/ask size + price 的 500ms 快照), 自己推断:
- 价格族: mid / spread / return
- 挂单族: imb / d_imb
- tempo 族: burst_score / run_length / phase_raw
- 事件推断族(自推断, 透明可控): cancel_proxy / add_proxy / trade_proxy / spoof_signature / pressure_source

基于 TRADING_WORLD_MODEL §3(事件语义)/§4(价格形成)/§6(时间结构)。
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, __file__.rsplit("/cog_protocol/", 1)[0])
from cog_protocol.investigation.xycache import load_multi


def load_raw(days=None):
    """JOIN 14 个原始字段探针(receive_time 对齐)。返回 wide DataFrame。"""
    return load_multi({
        "bid_size0":   ("RawBidSize0",   days),
        "ask_size0":   ("RawAskSize0",   days),
        "bid_price0":  ("RawBidPrice0",  days),
        "ask_price0":  ("RawAskPrice0",  days),
        "bid_size1":   ("RawBidSize1",   days),
        "bid_size2":   ("RawBidSize2",   days),
        "bid_size3":   ("RawBidSize3",   days),
        "bid_size4":   ("RawBidSize4",   days),
        "ask_size1":   ("RawAskSize1",   days),
        "ask_size2":   ("RawAskSize2",   days),
        "ask_size3":   ("RawAskSize3",   days),
        "ask_size4":   ("RawAskSize4",   days),
        "oi":          ("RawOI",         days),
        "total_volume":("RawTotalVolume",days),
    })


def _main_col(df, label, sub):
    """找主力 X 列(不含 @1@)。"""
    for c in df.columns:
        if c.startswith(label + "__") and sub in c and "@1@" not in c:
            return c
    raise KeyError(f"找不到 {label} 主力列(含 {sub})")


def derive(df, win=20, price_move_threshold=2):
    """算派生机制维度(价格族 + 挂单族 + tempo 族 + 事件推断族)。

    Args:
        df: load_raw 返回的 DataFrame
        win: rolling 窗口(用于 burst_score 的 std 基线)
        price_move_threshold: trade_proxy 判定阈值(d_mid 的 z-score 倍数, 默认 2σ)
    """
    df = df.sort_values("receive_time").reset_index(drop=True).copy()
    bs = _main_col(df, "bid_size0",  "raw_bid_size0")
    as_ = _main_col(df, "ask_size0", "raw_ask_size0")
    bp = _main_col(df, "bid_price0", "raw_bid_price0")
    ap = _main_col(df, "ask_price0", "raw_ask_price0")

    # ═══ 价格族 ═══
    df["mid"] = (df[bp] + df[ap]) / 2
    df["spread"] = df[ap] - df[bp]
    df["d_mid"] = df["mid"].diff()
    df["d_mid_std"] = df["d_mid"].rolling(win).std()
    df["d_mid_z"] = df["d_mid"] / (df["d_mid_std"] + 1e-9)  # 价格变化的 z-score

    # ═══ 挂单族 ═══
    df["imb"] = (df[bs] - df[as_]) / (df[bs] + df[as_] + 1e-9)
    df["d_bid0"] = df[bs].diff()
    df["d_ask0"] = df[as_].diff()
    df["d_imb"] = df["imb"].diff()

    # ═══ tempo 族 ═══
    df["d_bid0_std"] = df["d_bid0"].rolling(win).std()
    df["burst_score"] = df["d_bid0"].abs() / (df["d_bid0_std"] + 1e-9)
    s = np.sign(df["d_bid0"].fillna(0).values)
    chg = (pd.Series(s) != pd.Series(s).shift()).cumsum()
    df["run_length"] = (pd.Series(s).groupby(chg).cumcount() + 1) * (s != 0)
    # phase_raw 已删(与 burst_score 冗余 r=0.971)

    # ═══ 事件推断族(自推断, 不信平台 Feed::Cancel/Order/Trade) ═══
    _derive_event_proxies(df, price_move_threshold)

    # ═══ 霍克斯过程族(事件自激发强度 — 门控用途) ═══
    _derive_hawkes(df)

    # ═══ 深档结构族 + OI/Volume 族 ═══
    _derive_depth_oi_volume(df)

    return df


def _derive_depth_oi_volume(df):
    """深档结构 + OI 能量 + 成交强度派生。

    需 14 个原始字段(load_raw 已加载深档 + OI + volume)。
    若某字段缺失(旧缓存), 跳过对应派生。
    """
    import numpy as np

    # ── 深档 size ──
    def safe_col(df, label, sub):
        for c in df.columns:
            if c.startswith(label + "__") and sub in c and "@1@" not in c:
                return df[c]
        return None

    bid_sizes = []
    ask_sizes = []
    for i in range(5):
        b = safe_col(df, f"bid_size{i}", f"raw_bid_size{i}")
        a = safe_col(df, f"ask_size{i}", f"raw_ask_size{i}")
        if b is not None: bid_sizes.append(b)
        if a is not None: ask_sizes.append(a)

    if len(bid_sizes) >= 2 and len(ask_sizes) >= 2:
        # 深档累计厚度(可击穿性代理)
        bid_depth_total = sum(bid_sizes[1:])  # 档 1..N 的总和(不含最优档)
        ask_depth_total = sum(ask_sizes[1:])
        df["deep_bid_thickness"] = bid_depth_total.fillna(0)
        df["deep_ask_thickness"] = ask_depth_total.fillna(0)
        df["deep_thickness_imb"] = (bid_depth_total - ask_depth_total) / (bid_depth_total + ask_depth_total + 1e-9)

        # 深档 entropy(分布集中度: 均匀 vs 堆积某档)
        bid_arr = pd.concat([b.fillna(0) for b in bid_sizes], axis=1)
        ask_arr = pd.concat([a.fillna(0) for a in ask_sizes], axis=1)
        def _entropy(row_arr):
            p = row_arr / (row_arr.sum() + 1e-9)
            p = p[p > 0]
            return -(p * np.log(p)).sum() if len(p) > 0 else 0
        df["bid_depth_entropy"] = bid_arr.apply(_entropy, axis=1, raw=True)
        df["ask_depth_entropy"] = ask_arr.apply(_entropy, axis=1, raw=True)

        # 深档重心(加权平均档位: 重心高=集中在最优档, 低=深档堆积)
        weights = np.arange(1, len(bid_sizes) + 1)
        df["bid_depth_centroid"] = bid_arr.values @ weights / (bid_arr.values.sum(axis=1) + 1e-9)
        df["ask_depth_centroid"] = ask_arr.values @ weights / (ask_arr.values.sum(axis=1) + 1e-9)

        # 深档变化联动(多档同撤 vs 单档撤)
        if len(bid_sizes) >= 2:
            d_deep_bid = bid_sizes[1].diff().fillna(0)  # 档 1 变化(代表深档)
            df["deep_bid_cancel_align"] = ((d_deep_bid < 0) & (df.get("d_bid0", 0) < 0)).astype(int)  # 最优+深档同撤
            df["deep_bid_only_cancel"] = ((d_deep_bid < 0) & (df.get("d_bid0", 0) >= 0)).astype(int)  # 只深档撤

    # ── OI ──
    oi = safe_col(df, "oi", "raw_oi")
    if oi is not None:
        # 跨天边界: OI 可能跨天重置/跳变 → 用日内 diff(每天第一行 diff=0)
        df["_day"] = pd.to_datetime(df["receive_time"]).dt.date if "receive_time" in df else None
        if df["_day"] is not None:
            df["d_oi"] = oi.groupby(df["_day"]).diff()
            # 清跨天极端(d_oi > 1000 或 < -1000 归 0)
            df.loc[df["d_oi"].abs() > 1000, "d_oi"] = 0
        else:
            df["d_oi"] = oi.diff()
        df["d_oi_z"] = df["d_oi"] / (df["d_oi"].rolling(20).std() + 1e-9)
        df["oi_energy"] = df["d_oi"].abs().ewm(alpha=0.1).mean()
        df["oi_open"] = (df["d_oi"] > 0).astype(int)
        df["oi_close"] = (df["d_oi"] < 0).astype(int)

    # ── Total Volume ──
    vol = safe_col(df, "total_volume", "raw_total_volume")
    if vol is not None:
        # 跨天 volume 重置: 日内 diff + 清极端
        if df["_day"] is not None:
            df["d_volume"] = vol.groupby(df["_day"]).diff().clip(lower=0)
        else:
            df["d_volume"] = vol.diff().clip(lower=0)
        # 清跨天极端(d_volume > 10000 归 0)
        df.loc[df["d_volume"] > 10000, "d_volume"] = 0
        df["d_volume_z"] = df["d_volume"] / (df["d_volume"].rolling(20).std() + 1e-9)
        d_size_total = df.get("d_bid0", pd.Series(0, index=df.index)).abs() + df.get("d_ask0", pd.Series(0, index=df.index)).abs()
        df["action_intent_ratio"] = (df["d_volume"] / (d_size_total + 1.0)).clip(0, 5)


def _derive_hawkes(df, alpha_trade=0.8, beta_trade=0.2,
                   alpha_cancel=0.5, beta_cancel=0.1,
                   alpha_add=0.5, beta_add=0.1, mu_win=100):
    """霍克斯自激发强度 — 门控用途(不是线性预测器)。

    后验发现: 霍克斯直接对 Y 的 IC 弱(~0.003), 但作为门控有价值:
      - trade 级联中(高λ): imb IC 提升 ~30% (0.31→0.41)
      - 连续量霍克斯(|d_bid0|)有长期反转信号(IC@60s=-0.034)
      - 极端 top5% λ: 级联后 60s 反转 -0.062

    用法:
      hawkes_*_z > 阈值 → 级联状态(其他维度信号在此放大/变化)
      hawkes_*_gate = 1/0 → 二值门控(级联 vs 平静)
      hawkes_cont_z → 连续量版本(长期反转)

    Args:
        alpha/beta 各事件独立参数(经网格搜索校准):
          trade: α=0.8 β=0.2 (强激发短衰减, 门控效果最好)
          cancel: α=0.5 β=0.1
          add: α=0.5 β=0.1
    """
    params = {
        "trade":  ("trade_event", alpha_trade, beta_trade),
        "cancel": ("large_cancel_any", alpha_cancel, beta_cancel),
        "add":    ("large_add_any", alpha_add, beta_add),
    }
    for name, (col, alpha, beta) in params.items():
        if col not in df.columns:
            continue
        events = df[col].fillna(0).values.astype(float)
        n = len(events)
        decay = np.exp(-beta)
        lam_branch = np.zeros(n)
        for t in range(1, n):
            lam_branch[t] = lam_branch[t-1] * decay + alpha * events[t-1]
        mu = pd.Series(events).rolling(mu_win, min_periods=1).mean().values
        lam_total = mu + lam_branch
        df[f"hawkes_{name}"] = lam_total
        # z-score
        s = pd.Series(lam_total)
        lam_mean = s.rolling(mu_win, min_periods=1).mean()
        lam_std = s.rolling(mu_win, min_periods=1).std(ddof=0)
        df[f"hawkes_{name}_z"] = ((s - lam_mean) / (lam_std + 1e-9)).fillna(0).values
        # 门控(z > 1.5 = 级联中)
        df[f"hawkes_{name}_gate"] = (df[f"hawkes_{name}_z"] > 1.5).astype(int).values

    # 连续量霍克斯(|d_bid0|, 不二值化 — 长期反转信号 IC@60s=-0.034)
    cont = df["d_bid0"].abs().fillna(0).values if "d_bid0" in df.columns else None
    if cont is not None:
        alpha_c, beta_c = 0.1, 0.05
        decay_c = np.exp(-beta_c)
        lam_c = np.zeros(len(cont))
        for t in range(1, len(cont)):
            lam_c[t] = lam_c[t-1] * decay_c + alpha_c * cont[t-1]
        mu_c = pd.Series(cont).rolling(mu_win, min_periods=1).mean().values
        total_c = mu_c + lam_c
        sc = pd.Series(total_c)
        df["hawkes_cont"] = total_c
        df["hawkes_cont_z"] = ((sc - sc.rolling(mu_win, min_periods=1).mean()) /
                               (sc.rolling(mu_win, min_periods=1).std(ddof=0) + 1e-9)).fillna(0).values


def _derive_event_proxies(df, price_move_threshold=2, size_anomaly_sigma=2.5, spoof_window=5):
    """从 d_bid0 / d_ask0 / d_mid_z 交叉推断事件类型。

    基于微观结构调研(OBERON/Stanford)的分层置信度:
      高置信: 价格动(d_mid_z ≥ threshold) → 有成交(trade)
      中置信: size 大幅变(超自身 rolling std 的 N 倍) + 价格不动 → 疑似大额撤单/挂单
      低置信: large_add 后跟 large_cancel → 疑似 spoof(双重推断, 只当签名)

    核心歧义(OBERON 确认): 最优档 size 小幅减 + 价格不动, 无法区分 cancel 还是小单成交。
    处理: 只看大幅异常(size_anomaly_sigma 倍 std), 小幅变化归"无明确事件"。

    Args:
        price_move_threshold: trade 判定阈值(d_mid_z 的 σ 倍数)
        size_anomaly_sigma: large_add/cancel 判定阈值(d_bid0 超自身 rolling std 的 N 倍)
        spoof_window: spoof 签名窗口(K 步内 add 后 cancel)
    """
    # 价格是否动(高置信: 动了 = 有成交)
    price_up = df["d_mid_z"] >= price_move_threshold
    price_down = df["d_mid_z"] <= -price_move_threshold
    price_moved = price_up | price_down
    price_steady = ~price_moved

    # size 变化的 z-score(只看大幅异常)
    df["d_bid0_z"] = df["d_bid0"] / (df["d_bid0_std"] + 1e-9)
    df["d_ask0_std"] = df["d_ask0"].rolling(20).std()
    df["d_ask0_z"] = df["d_ask0"] / (df["d_ask0_std"] + 1e-9)

    bid_large_neg = (df["d_bid0_z"] <= -size_anomaly_sigma) & price_steady  # bid 大减 + 价格不动
    bid_large_pos = (df["d_bid0_z"] >= size_anomaly_sigma) & price_steady   # bid 大增 + 价格不动
    ask_large_neg = (df["d_ask0_z"] <= -size_anomaly_sigma) & price_steady
    ask_large_pos = (df["d_ask0_z"] >= size_anomaly_sigma) & price_steady

    # ═══ 高置信: 成交事件(价格动了) ═══
    df["trade_event"] = price_moved.astype(int)          # 1=有成交
    df["trade_buy"] = price_up.astype(int)               # 价格上跳 = 买方主动
    df["trade_sell"] = price_down.astype(int)            # 价格下跳 = 卖方主动

    # ═══ 中置信: 大额挂单/撤单(size 大幅变 + 价格不动) ═══
    df["large_cancel_bid"] = bid_large_neg.astype(int)   # bid 大减 + 价格不动(疑似撤大单)
    df["large_add_bid"] = bid_large_pos.astype(int)      # bid 大增 + 价格不动(疑似挂大单)
    df["large_cancel_ask"] = ask_large_neg.astype(int)
    df["large_add_ask"] = ask_large_pos.astype(int)
    df["large_cancel_any"] = (bid_large_neg | ask_large_neg).astype(int)
    df["large_add_any"] = (bid_large_pos | ask_large_pos).astype(int)

    # ═══ 压力来源归因(意图 vs 行动) ═══
    # trade = 主动冲击(知情者/方向性, 有行动)
    # large_add/cancel = 被动调整(做市商, 意图层)
    df["pressure_active"] = df["trade_event"]                                    # 1=主动行动
    df["pressure_passive"] = (df["large_cancel_any"] | df["large_add_any"]).astype(int)  # 1=被动意图

    # ═══ 低置信: spoof 签名(大额挂单后短窗内大额撤单, 双重推断) ═══
    recent_bid_add = df["large_add_bid"].rolling(spoof_window).max().fillna(0).astype(bool)
    recent_ask_add = df["large_add_ask"].rolling(spoof_window).max().fillna(0).astype(bool)
    df["spoof_bid_sign"] = (recent_bid_add & df["large_cancel_bid"].astype(bool)).astype(int)
    df["spoof_ask_sign"] = (recent_ask_add & df["large_cancel_ask"].astype(bool)).astype(int)
    df["spoof_any_sign"] = (df["spoof_bid_sign"] | df["spoof_ask_sign"]).astype(int)

    # ═══ 意图 vs 行动 累积(EMA, 做市商 vs 知情者行为对比) ═══
    decay = 0.1
    # 意图流: 大额挂(+1) - 大额撤(-1), 只用中置信的大额事件
    intent_raw = (df["large_add_bid"].astype(float) - df["large_cancel_bid"].astype(float)
                + df["large_add_ask"].astype(float) - df["large_cancel_ask"].astype(float))
    df["intent_flow"] = intent_raw.ewm(alpha=decay).mean()
    # 行动流: 买方成交(+1) - 卖方成交(-1)
    df["action_flow"] = (df["trade_buy"].astype(float) - df["trade_sell"].astype(float)).ewm(alpha=decay).mean()
    # 背离: 意图说一个方向, 行动说另一个(spoof/虚假诱导特征)
    df["intent_action_divergence"] = df["intent_flow"] - df["action_flow"]


def conditional_slice(df, match_cols, stratify_col, y_col, n_match_bins=3, n_strat_bins=3,
                      gate_col=None):
    """多变量 match + stratify + 门控。

    Args:
        match_cols: 要控制的坐标(数值, 各自分位桶)
        stratify_col: 要检验的维度(数值, 分位桶)
        y_col: Y 列
        gate_col: 可选门控列(如 hawkes_trade_gate, 0/1 二值)。
                  若提供, 分别报告 gate=1(级联中) vs gate=0(平静) 的 IC 差。
    """
    sub = df.dropna(subset=match_cols + [stratify_col, y_col]).copy()
    for c in match_cols:
        sub[f"_mbin_{c}"] = pd.qcut(sub[c].rank(method="first"), n_match_bins,
                                     labels=[f"{c}_q{i+1}" for i in range(n_match_bins)])
    sub[f"_sbin"] = pd.qcut(sub[stratify_col].rank(method="first"), n_strat_bins,
                            labels=[f"q{i+1}" for i in range(n_strat_bins)])
    mbin_keys = [f"_mbin_{c}" for c in match_cols]
    g = sub.groupby(mbin_keys + [f"_sbin"], observed=True)[y_col].agg(["mean", "count"]).reset_index()

    if gate_col and gate_col in sub.columns:
        # 门控下的 IC 差: gate=1 vs gate=0 中 stratify_col → y_col 的 IC
        from scipy.stats import spearmanr
        gate = sub[gate_col].fillna(0).values
        on = gate == 1
        off = gate == 0
        ic_on = spearmanr(sub.loc[on, stratify_col], sub.loc[on, y_col])[0] if on.sum() > 50 else 0
        ic_off = spearmanr(sub.loc[off, stratify_col], sub.loc[off, y_col])[0] if off.sum() > 50 else 0
        g.attrs["gate"] = gate_col
        g.attrs["ic_gate_on"] = ic_on
        g.attrs["ic_gate_off"] = ic_off
        g.attrs["ic_gate_delta"] = ic_on - ic_off
        g.attrs["n_gate_on"] = int(on.sum())
        g.attrs["n_gate_off"] = int(off.sum())

    return g, sub


if __name__ == "__main__":
    days = sys.argv[1:4] if len(sys.argv) > 1 else None
    if days and len(days) == 1 and "-" not in days[0]:
        all_days = sorted(__import__("pathlib").Path(
            "/home/lgao/tmp/factor-vec-cache/RawBidSize0/dailyX").glob("daily-*.xy"))
        days = [d.name.replace("daily-", "").replace(".xy", "") for d in all_days[:int(days[0])]]
    print(f"加载 {len(days) if days else '全部'} 天...")
    df = load_raw(days)
    print(f"  原始: {len(df)} 行, 列 {len(df.columns)}")
    df = derive(df)
    print(f"\n=== 派生维度分布 ===")
    groups = {
        "价格族": ["mid", "spread", "d_mid_z"],
        "挂单族": ["imb", "d_imb"],
        "tempo族": ["burst_score", "run_length"],
        "事件-高置信(成交)": ["trade_event", "trade_buy", "trade_sell"],
        "事件-中置信(大额挂撤)": ["large_cancel_bid", "large_add_bid", "large_cancel_ask", "large_add_any",
                              "large_cancel_any", "pressure_active", "pressure_passive"],
        "事件-低置信(spoof签名)": ["spoof_bid_sign", "spoof_ask_sign", "spoof_any_sign", "intent_action_divergence"],
        "霍克斯(门控)": ["hawkes_trade", "hawkes_trade_z", "hawkes_trade_gate",
                     "hawkes_cancel_z", "hawkes_cancel_gate",
                     "hawkes_add_z", "hawkes_add_gate",
                     "hawkes_cont_z"],
        "深档结构": ["deep_bid_thickness", "deep_ask_thickness", "deep_thickness_imb",
                   "bid_depth_entropy", "ask_depth_entropy",
                   "bid_depth_centroid", "ask_depth_centroid",
                   "deep_bid_cancel_align", "deep_bid_only_cancel"],
        "OI/Volume": ["d_oi", "d_oi_z", "oi_energy", "oi_open", "oi_close",
                      "d_volume", "d_volume_z", "action_intent_ratio"],
    }
    for group, cols in groups.items():
        print(f"\n  --- {group} ---")
        for c in cols:
            if c in df.columns:
                s = df[c].dropna()
                if s.nunique() <= 2:  # binary proxy
                    print(f"  {c}: {s.mean()*100:.1f}% positive (n={len(s)})")
                else:
                    print(f"  {c}: mean={s.mean():.3f} std={s.std():.3f} "
                          f"[{s.quantile(.05):.3f} .. {s.quantile(.95):.3f}]")
