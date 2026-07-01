#!/usr/bin/env python3
"""
因子评估一键脚本 (factor-evaluate)

整合三种评估模式:
  1. feval  — 提交 → 下载 → 7 维 feval 评估（含可视化报告）
  2. pearson — Pearson IC 相关系数批量分析
  3. deep    — 因子信息诊断: Daily IC / Rank IC / 条件收益 / 信号稳定性 / 月度 IC

支持 --mode full 同时运行 pearson + deep + feval 全部评估。

用法:
  python3 factor_evaluate.py run --dir <输出目录> --h-dir <.h文件目录> --cookie <cookie>
  python3 factor_evaluate.py run --dir <输出目录> --names factor1,factor2 --mode full
  python3 factor_evaluate.py analyze --dir <输出目录> --mode pearson
  python3 factor_evaluate.py analyze --dir <输出目录> --mode deep
  python3 factor_evaluate.py analyze --dir <输出目录> --mode full
  python3 factor_evaluate.py status --cookie <cookie>
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import tarfile
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

# ==================== 配置 ====================
_DEFAULT_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FEVAL_PATH = os.path.join(_DEFAULT_THIS_DIR, "feval")
if _DEFAULT_THIS_DIR not in sys.path:
    sys.path.insert(0, _DEFAULT_THIS_DIR)

from featuretool_common import HOST, BASE_URL, COOKIE_FILE, COOKIE_NAME, get_cookie, save_cookie, ensure_cookie, fetch, parse_index

DEFAULT_START_COL = 2
DEFAULT_HIGHLIGHT_LAST_N = 5
DEFAULT_START_DATE = "2024-01-02"
DEFAULT_END_DATE = "2024-06-30"
DEFAULT_N_GROUPS = 5
# ===============================================


# ==================== 通用工具（已迁移到 factor-common/featuretool_common.py） ====================

def fetch_factors(cookie):
    """获取因子列表"""
    html = fetch(f"{BASE_URL}/index", cookie)
    username, factors = parse_index(html)
    if not username:
        print("错误: cookie 无效或已过期")
        sys.exit(1)
    return username, factors


def extract_class_name(h_file):
    """从 .h 文件提取类名和模板默认参数（支持多行 template 声明）"""
    with open(h_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    # 预处理：合并多行 template 声明为单行
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'\s*template\s', line):
            full = line.rstrip()
            # 向后合并直到遇到 '>' 结尾
            while not re.search(r'>\s*$', full) and i + 1 < len(lines):
                i += 1
                full += " " + lines[i].strip()
            merged.append(full)
        else:
            merged.append(line)
        i += 1
    for i, line in enumerate(merged):
        if re.search(r':\s*public\s', line):
            m = re.search(r'class\s+(\w+)', line)
            if m:
                cls = m.group(1)
                is_template = (i > 0 and bool(re.match(r'\s*template\s', merged[i - 1])))
                if is_template and i > 0:
                    args_match = re.findall(r'=\s*(\d+(?:\.\d+)?)', merged[i - 1])
                    template_args = ", ".join(args_match) if args_match else ""
                else:
                    template_args = None
                return cls, is_template, template_args
    return None, False, None


def submit_factor(cookie, h_file, class_name, is_template, template_args, feeds, start_date, end_date):
    """提交单个因子"""
    html = fetch(f"{BASE_URL}/submit?username=", cookie)
    formkey_match = re.search(r'name="_formkey"\s+type="hidden"\s+value="([^"]*)"', html)
    if not formkey_match:
        print(f"  错误: 无法获取 CSRF token，cookie 可能已过期")
        return False
    formkey = formkey_match.group(1)

    if is_template and template_args:
        features = f"{class_name}<{template_args}>"
    elif is_template:
        features = f"{class_name}<>"
    else:
        features = class_name
    file_path = Path(h_file)

    print(f"  提交: {features} ({file_path.name})")
    try:
        cmd = [
            "curl", "-s", "-L", "-k", "--max-time", "60",
            "-b", f"{COOKIE_NAME}={cookie}",
            "-F", f"uploaded_file=@{file_path}",
            "-F", f"features={features}",
            "-F", f"Feeds={feeds}",
            "-F", f"start_date={start_date}",
            "-F", f"end_date={end_date}",
            "-F", "_next=/featuretool/default/index",
            "-F", f"_formkey={formkey}",
            "-F", "_formname=default",
            f"{BASE_URL}/submit",
            "-F", "GenerateXs=on",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if 'submit?username=' in result.stdout:
            print(f"  提交成功")
            return True
        else:
            print(f"  提交失败，请检查")
            return False
    except Exception as e:
        print(f"  提交异常: {e}")
        return False


# ==================== 共享: 因子发现 + 数据加载 ====================

def detect_date_range(base_dir):
    """扫描所有因子目录的 dailyX/*.xy 文件，返回最早和最晚日期 (YYYY-MM-DD)。
    如果没有数据文件则返回 None, None。
    """
    all_dates = []
    for entry in os.listdir(base_dir):
        dailyx = os.path.join(base_dir, entry, "dailyX")
        if not os.path.isdir(dailyx):
            continue
        for f in os.listdir(dailyx):
            m = re.match(r"daily-(\d{8})\.xy$", f)
            if m:
                all_dates.append(m.group(1))
    if not all_dates:
        return None, None
    all_dates.sort()
    first, last = all_dates[0], all_dates[-1]
    return f"{first[:4]}-{first[4:6]}-{first[6:]}", f"{last[:4]}-{last[4:6]}-{last[6:]}"


def _try_as_factor_dir(dir_path):
    """检查 dir_path 本身是否是因子目录（直接包含 dailyX/）"""
    dailyx_path = os.path.join(dir_path, "dailyX")
    if not os.path.isdir(dailyx_path):
        return None
    h_files = glob.glob(os.path.join(dailyx_path, "*.h"))
    if not h_files:
        return None
    factor_name = os.path.splitext(os.path.basename(h_files[0]))[0]
    xy_files = glob.glob(os.path.join(dailyx_path, "daily-*.xy"))
    if not xy_files:
        return None
    return {
        "folder_path": dir_path,
        "dailyx_path": dailyx_path,
        "factor_name": factor_name,
        "data_count": len(xy_files)
    }


def scan_factors(base_dir):
    """扫描根目录，找到所有含 dailyX 且有 .h 文件的因子文件夹。
    支持两种格式：
    1. 父目录包含多个因子子目录（每个子目录有 dailyX/）
    2. 目录本身即是因子目录（直接包含 dailyX/）
    """
    # 先检查 base_dir 本身是否就是因子目录
    direct = _try_as_factor_dir(base_dir)
    if direct:
        return [direct]

    factors = []
    for entry in os.listdir(base_dir):
        entry_path = os.path.join(base_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        f = _try_as_factor_dir(entry_path)
        if f:
            factors.append(f)
    return factors


def generate_date_list(start_date, end_date):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return [(start + timedelta(days=i)).strftime("%Y%m%d")
            for i in range((end - start).days + 1)]


def discover_columns(data_dir, date_list, start_col, highlight_last_n):
    """共享: 探测最大列数、读取列名、划分 A/B 分组。

    Returns
    -------
    max_cols : int
    data_names : list[str]       — start_col 之后的所有列名
    group_a : list[str]          — X 列
    group_b : list[str]          — Y 列
    err : str | None
    """
    # 探测最大列数
    max_cols = 0
    for date_str in date_list:
        fp = os.path.join(data_dir, f"daily-{date_str}.xy")
        try:
            sample = pd.read_csv(fp, header=None, nrows=1)
            if sample.shape[1] > max_cols:
                max_cols = sample.shape[1]
        except FileNotFoundError:
            pass

    if max_cols <= start_col:
        return 0, [], [], [], "列数不足"

    n_data = max_cols - start_col

    # 读取列名
    raw_names = None
    for date_str in date_list:
        fp = os.path.join(data_dir, f"daily-{date_str}.xy")
        try:
            header_df = pd.read_csv(fp, header=0, nrows=0)
            names = list(header_df.columns)
            if len(names) >= start_col + n_data:
                raw_names = names
                break
        except (FileNotFoundError, pd.errors.EmptyDataError):
            continue

    if raw_names:
        data_names = raw_names[start_col : start_col + n_data]
    else:
        data_names = [f"col_{i + 1}" for i in range(n_data)]

    # 划分 A/B 分组
    n_total = len(data_names)
    if n_total <= highlight_last_n:
        group_a, group_b = [], list(data_names)
    else:
        group_a = data_names[:-highlight_last_n]
        group_b = data_names[-highlight_last_n:]

    return max_cols, data_names, group_a, group_b, None


def load_daily_dataframes(data_dir, date_list, start_col, max_cols, data_names):
    """共享: 按天加载 daily-*.xy 数据，对齐列数，转为数值。

    Returns dict[str, DataFrame] 或 None（无数据时）。
    """
    n_data = len(data_names)
    daily_dfs = {}
    daily_rt = {}  # date_str → receive_time(int64 ns),供 daily 分桶做 horizon 尾盘截断;
                   # 单独存、不进 df,避免 concat/iloc 全列分析(pearson 等)被时间戳污染
    for date_str in date_list:
        fp = os.path.join(data_dir, f"daily-{date_str}.xy")
        try:
            df = pd.read_csv(fp, header=None)
            rt_ns = pd.to_numeric(df.iloc[:, 0], errors="coerce").astype("int64").values
            if df.shape[1] < max_cols:
                pad = pd.DataFrame(np.nan, index=df.index, columns=range(df.shape[1], max_cols))
                df = pd.concat([df, pad], axis=1)
            df = df.iloc[:, start_col : start_col + n_data].copy()
            df.columns = data_names[: len(df.columns)]
            for c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            daily_dfs[date_str] = df
            daily_rt[date_str] = rt_ns
        except FileNotFoundError:
            pass
    if not daily_dfs:
        return None, None
    return daily_dfs, daily_rt


def load_factor_data(data_dir, date_list, start_col, highlight_last_n):
    """共享: 一站式数据加载 — 发现列名 + 按天加载。

    Returns
    -------
    daily_dfs : dict[str, DataFrame]   — 按天的数据
    group_a : list[str]                — X 列名
    group_b : list[str]                — Y 列名
    daily_rt : dict[str, np.ndarray]   — 每日 receive_time(ns),供分桶截断
    err : str | None
    """
    max_cols, data_names, group_a, group_b, err = discover_columns(
        data_dir, date_list, start_col, highlight_last_n
    )
    if err:
        return None, [], [], None, err

    daily_dfs, daily_rt = load_daily_dataframes(data_dir, date_list, start_col, max_cols, data_names)
    if daily_dfs is None:
        return None, [], [], None, "无有效数据"

    return daily_dfs, group_a, group_b, daily_rt, None


# ==================== feval 评估 ====================

def merge_daily_xy(dailyx_dir):
    """合并 dailyX 目录下所有 daily-*.xy 文件为一个 DataFrame（内存中）"""
    xy_files = sorted(glob.glob(os.path.join(dailyx_dir, "daily-*.xy")))
    if not xy_files:
        return None, None
    dfs = [pd.read_csv(p) for p in xy_files]
    combined = pd.concat(dfs, ignore_index=True)
    return combined, os.path.basename(os.path.dirname(dailyx_dir))


def run_feval_eval(combined_df, report_dir, factor_name, feval_path):
    """运行 feval FeatureEvaluator 完整评估（直接从 DataFrame，无文件 I/O）

    Args:
        combined_df: 合并后的 DataFrame
        report_dir: 报告输出目录
        factor_name: 因子名
        feval_path: feval 包路径

    Returns:
        EvalResult
    """
    if feval_path not in sys.path:
        sys.path.insert(0, feval_path)

    from feval.eval import FeatureEvaluator

    os.makedirs(report_dir, exist_ok=True)

    print(f"\n  评估 {factor_name}...")
    ev = FeatureEvaluator()
    result = ev.evaluate_df(combined_df, label=factor_name)
    ev.report(result, output_dir=report_dir)
    return result


# ==================== Pearson IC 分析 ====================
# ==================== 深度分析 ====================

def _horizon_seconds(col_b):
    """从 Y 列名尾部 @<秒> 解析前瞻 horizon(秒),用于尾盘截断防未来信息泄漏。

    如 'Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@300' → 300。解析失败返回 0(不截断)。
    """
    m = re.search(r"@(\d+)$", str(col_b))
    return int(m.group(1)) if m else 0


def compute_rank_ic(daily_dfs, group_a_cols, group_b_cols, daily_rt=None):
    """Daily 分桶 Spearman Rank IC + per-horizon 尾盘截断(防未来信息泄漏)。

    分桶用 receive_time 的自然日(= X 信号发出日)——信号产生时已知的归属,符合因果。

    防泄漏:每个 Y@h 列,丢弃 receive_time > (当日最末 tick - h 秒) 的尾盘 tick,
    因其 h 秒前瞻收益越过当日收盘、沾染下一交易时段信息。horizon 从 Y 列名 @<秒> 解析;
    daily_rt 为 None 时退化为不截断(保持兼容)。

    返回:每 (X,Y) 对一行,含逐日 rank ic 均值/std/icir/hit_rate/n_days,
    并保留 pooled(同样截断后)作对照。
    """
    rows = []
    for a in group_a_cols:
        for b in group_b_cols:
            h = _horizon_seconds(b)
            daily_ics = []
            pooled_x, pooled_y = [], []
            for _date_str, df in sorted(daily_dfs.items()):
                v = df[[a, b]].dropna()
                if len(v) < 10:
                    continue
                xa = v[a].astype(float).values
                yb = v[b].astype(float).values
                # 尾盘 horizon 截断:剔除距当日收盘不足 h 秒的 tick(Y 会越过收盘)
                if h > 0 and daily_rt is not None and _date_str in daily_rt:
                    rt = daily_rt[_date_str][v.index.to_numpy()]  # 依赖 load 阶段 df 为 RangeIndex
                    last_ns = rt.max()
                    keep = rt <= (last_ns - h * 1_000_000_000)
                    xa, yb = xa[keep], yb[keep]
                if len(xa) < 10:
                    continue
                if np.std(xa) < 1e-15 or np.std(yb) < 1e-15:
                    continue
                r, _ = stats.spearmanr(xa, yb)
                if not np.isnan(r):
                    daily_ics.append(r)
                pooled_x.append(xa)
                pooled_y.append(yb)
            if len(daily_ics) < 3:
                continue
            ic_arr = np.array(daily_ics)
            n = len(ic_arr)
            mean = ic_arr.mean()
            std = ic_arr.std(ddof=1)
            icir = mean / std if std > 1e-12 else 0.0
            hit = float((ic_arr > 0).mean())
            px = np.concatenate(pooled_x) if pooled_x else np.array([])
            py = np.concatenate(pooled_y) if pooled_y else np.array([])
            pooled_r = float(stats.spearmanr(px, py)[0]) if len(px) >= 30 else np.nan
            rows.append({
                "A_col": a, "B_col": b, "horizon_sec": h,
                "daily_rank_ic": round(mean, 6), "daily_ic_std": round(std, 6),
                "daily_icir": round(icir, 4), "hit_rate": round(hit, 4),
                "n_days": n, "ic_pos_days": int((ic_arr > 0).sum()),
                "pooled_rank_ic": (round(pooled_r, 6) if not np.isnan(pooled_r) else None),
                "|daily_rank_ic|": round(abs(mean), 6),
            })
    if not rows:
        return None
    return pd.DataFrame(rows).sort_values("|daily_rank_ic|", ascending=False).reset_index(drop=True)


def compute_daily_ic(daily_dfs, group_a_cols, group_b_cols, daily_rt=None):
    """逐天计算 Spearman IC（过滤 X=0），统计 daily IC 稳定性。
    包含 t-stat/p-value/95% CI/胜率/正负天数/非零率/非零IC 等完整统计。"""
    results = []
    detail = {}

    for a in group_a_cols:
        for b in group_b_cols:
            h = _horizon_seconds(b)
            daily_ics = {}
            daily_nz_rates = {}
            daily_nz_ics = {}

            for date_str, df in sorted(daily_dfs.items()):
                v = df[[a, b]].dropna()
                if len(v) < 10:
                    continue

                # 尾盘 horizon 截断(防未来信息泄漏):丢距当日收盘 < h 秒的 tick,
                # 其 h 秒前瞻收益越过收盘、沾染下一交易时段。与 compute_rank_ic 对称。
                if h > 0 and daily_rt is not None and date_str in daily_rt:
                    rt = daily_rt[date_str][v.index.to_numpy()]  # 依赖 load 阶段 df 为 RangeIndex
                    v = v[rt <= (rt.max() - h * 1_000_000_000)]
                    if len(v) < 10:
                        continue

                # 全样本 IC（不过滤 X=0）
                ic, _ = stats.spearmanr(v[a], v[b])
                if np.isnan(ic):
                    continue
                daily_ics[date_str] = ic

                # Non-zero rate and nonzero IC
                nz_mask = v[a] != 0
                nz_rate = nz_mask.sum() / len(v)
                daily_nz_rates[date_str] = round(nz_rate, 6)
                if nz_mask.sum() >= 10:
                    nz_ic, _ = stats.spearmanr(v.loc[nz_mask, a], v.loc[nz_mask, b])
                    if not np.isnan(nz_ic):
                        daily_nz_ics[date_str] = nz_ic

            if len(daily_ics) < 3:
                continue

            ic_arr = np.array(list(daily_ics.values()))
            n = len(ic_arr)
            ic_mean = ic_arr.mean()
            ic_std = ic_arr.std(ddof=1)
            icir = ic_mean / ic_std if ic_std > 1e-12 else 0.0
            hit_rate = float((ic_arr > 0).mean())
            ic_t = ic_mean / (ic_std / np.sqrt(n)) if ic_std > 1e-12 else 0.0
            p_value = 2 * (1 - stats.t.cdf(abs(ic_t), df=n - 1))

            # 95% 置信区间
            t_crit = stats.t.ppf(0.975, df=n - 1)
            ci_half = t_crit * ic_std / np.sqrt(n)
            ci_lower = ic_mean - ci_half
            ci_upper = ic_mean + ci_half

            # Non-zero stats
            nz_rate_arr = np.array(list(daily_nz_rates.values()))
            nz_rate_mean = round(np.mean(nz_rate_arr), 4) if len(nz_rate_arr) > 0 else 0
            if len(daily_nz_ics) >= 3:
                nz_ic_arr = np.array(list(daily_nz_ics.values()))
                nz_ic_mean = round(np.mean(nz_ic_arr), 6)
                nz_ic_std = round(np.std(nz_ic_arr, ddof=1), 6)
                nz_icir = round(nz_ic_mean / np.std(nz_ic_arr, ddof=1), 4) if np.std(nz_ic_arr, ddof=1) > 0 else 0
                nz_n_days = len(nz_ic_arr)
            else:
                nz_ic_mean = np.nan
                nz_ic_std = np.nan
                nz_icir = 0
                nz_n_days = len(daily_nz_ics)

            results.append({
                "A_col": a, "B_col": b,
                "ic_mean": round(ic_mean, 6),
                "ic_std": round(ic_std, 6),
                "icir": round(icir, 4),
                "hit_rate": round(hit_rate, 4),
                "t_stat": round(ic_t, 4),
                "p_value": round(p_value, 6),
                "ci_95_lower": round(ci_lower, 6),
                "ci_95_upper": round(ci_upper, 6),
                "n_days": n,
                "ic_positive_days": int(np.sum(ic_arr > 0)),
                "ic_negative_days": int(np.sum(ic_arr < 0)),
                "nonzero_rate": nz_rate_mean,
                "nonzero_ic_mean": nz_ic_mean,
                "nonzero_ic_std": nz_ic_std,
                "nonzero_icir": nz_icir,
                "nonzero_n_days": nz_n_days,
            })

            detail[f"{a} vs {b}"] = {k: round(v, 6) for k, v in sorted(daily_ics.items())}

    if not results:
        return None

    summary_rows = results  # all fields are summary-worthy now
    return pd.DataFrame(summary_rows).sort_values("t_stat", key=abs, ascending=False).reset_index(drop=True), detail


def compute_bucket_analysis(daily_dfs, group_a_cols, group_b_cols, n_groups=5):
    """每天按因子值排名分 N 组，计算各组条件收益及 top-bottom spread 稳定性。
    包含年化 Sharpe、累计收益（乘法复利）、最大回撤。"""
    results = []
    detail = {}

    for a in group_a_cols:
        for b in group_b_cols:
            daily_ls = []
            daily_group_rets = []

            for date_str, df in sorted(daily_dfs.items()):
                v = df[[a, b]].dropna()
                if len(v) < n_groups * 5:
                    continue
                v = v.copy()
                v["_pct"] = v[a].rank(pct=True)
                v["_grp"] = pd.cut(v["_pct"], bins=np.linspace(0, 1, n_groups + 1), labels=False, include_lowest=True)
                grp_ret = v.groupby("_grp")[b].mean()
                ls = grp_ret.iloc[-1] - grp_ret.iloc[0] if n_groups > 1 else 0
                daily_ls.append(ls)
                daily_group_rets.append(grp_ret.to_dict())

            if len(daily_ls) < 3:
                continue

            ls_arr = np.array(daily_ls)
            daily_spread_mean = ls_arr.mean()
            daily_spread_std = ls_arr.std()
            spread_ir = daily_spread_mean / daily_spread_std if daily_spread_std > 0 else 0
            annualized_spread_ir = spread_ir * np.sqrt(252)
            spread_sum = ls_arr.sum()

            # 乘法复利累计收益 + 最大回撤（学习对方 compute_backtest）
            cum = np.cumprod(1 + ls_arr)
            cum_pct = (cum[-1] - 1) * 100
            peak = np.maximum.accumulate(cum)
            dd = (cum - peak) / peak
            max_dd = abs(dd.min()) * 100

            # 加法累计 spread + drawdown（保留原有）
            cum_sum = np.cumsum(ls_arr)
            spread_drawdown = abs(min(cum_sum.min(), 0))

            # 年化 Sharpe（学习对方，用 L-S 日收益的标准差）
            annualized_sharpe = daily_spread_mean / daily_spread_std * np.sqrt(252) if daily_spread_std > 0 else 0

            avg_grp = {}
            for g in range(n_groups):
                vals = [dr.get(g, np.nan) for dr in daily_group_rets if g in dr]
                if vals:
                    avg_grp[g] = np.mean(vals)

            grp_vals = [avg_grp.get(g, np.nan) for g in range(n_groups)]
            eps = 1e-12
            inc = all(
                grp_vals[i] <= grp_vals[i + 1] + eps
                for i in range(len(grp_vals) - 1)
                if not (np.isnan(grp_vals[i]) or np.isnan(grp_vals[i + 1]))
            )
            dec = all(
                grp_vals[i] >= grp_vals[i + 1] - eps
                for i in range(len(grp_vals) - 1)
                if not (np.isnan(grp_vals[i]) or np.isnan(grp_vals[i + 1]))
            )
            if inc:
                direction = "positive"
            elif dec:
                direction = "negative"
            else:
                direction = "non_monotonic"

            pair_key = f"{a} vs {b}"
            results.append({
                "A_col": a, "B_col": b,
                "daily_spread_mean": round(daily_spread_mean, 8),
                "daily_spread_std": round(daily_spread_std, 8),
                "annualized_sharpe": round(annualized_sharpe, 4),
                "annualized_spread_ir": round(annualized_spread_ir, 4),
                "cum_ret_%": round(cum_pct, 4),
                "cumulative_spread": round(spread_sum, 6),
                "max_dd_%": round(max_dd, 4),
                "spread_drawdown": round(spread_drawdown, 6),
                "monotonic": direction,
                "n_days": len(daily_ls),
            })
            detail[pair_key] = {
                "avg_group": {str(k): round(v, 8) for k, v in sorted(avg_grp.items())},
                "daily_spread": {sorted(daily_dfs.keys())[i]: round(v, 8) for i, v in enumerate(daily_ls)},
            }

    if not results:
        return None
    return pd.DataFrame(results).sort_values("annualized_sharpe", ascending=False).reset_index(drop=True), detail


def compute_signal_rank_stability(daily_dfs, group_a_cols, n_groups=5):
    """通过因子排名的日间自相关衡量信号稳定性"""
    rows = []

    for a in group_a_cols:
        daily_ranks = {}
        dates_sorted = sorted(daily_dfs.keys())

        for d in dates_sorted:
            v = daily_dfs[d][[a]].dropna()
            if len(v) < n_groups * 5:
                continue
            daily_ranks[d] = v[a].rank(pct=True).values

        usable = [d for d in dates_sorted if d in daily_ranks]
        if len(usable) < 3:
            continue

        autocorrs = []
        for i in range(1, len(usable)):
            r1 = daily_ranks[usable[i - 1]]
            r2 = daily_ranks[usable[i]]
            mn = min(len(r1), len(r2))
            if mn < 10:
                continue
            c, _ = stats.spearmanr(r1[:mn], r2[:mn])
            if not np.isnan(c):
                autocorrs.append(c)

        if not autocorrs:
            continue

        avg_ac = np.mean(autocorrs)
        signal_instability = (1 - avg_ac) / 2 * 100

        rows.append({
            "A_col": a,
            "avg_rank_autocorr": round(avg_ac, 6),
            "signal_instability_%": round(signal_instability, 2),
            "min_autocorr": round(min(autocorrs), 6),
            "max_autocorr": round(max(autocorrs), 6),
            "n_pairs": len(autocorrs),
        })

    if not rows:
        return None
    return pd.DataFrame(rows).sort_values("signal_instability_%", ascending=True).reset_index(drop=True)


def compute_monthly_ic(daily_dfs, group_a_cols, group_b_cols):
    """按月计算 Spearman IC，统计 IC 均值 / 标准差 / ICIR / 胜率"""
    results = []

    for a in group_a_cols:
        for b in group_b_cols:
            monthly = {}

            for date_str, df in daily_dfs.items():
                mkey = date_str[:6]
                v = df[[a, b]].dropna()
                if len(v) < 30:
                    continue
                ic, _ = stats.spearmanr(v[a], v[b])
                if np.isnan(ic):
                    continue
                monthly.setdefault(mkey, []).append(ic)

            if len(monthly) < 1:
                continue

            avg = {k: np.mean(vs) for k, vs in sorted(monthly.items())}
            ic_arr = list(avg.values())

            ic_mean = np.mean(ic_arr)
            ic_std = np.std(ic_arr)
            icir = ic_mean / ic_std if ic_std > 0 else 0
            hit = sum(1 for x in ic_arr if x > 0) / len(ic_arr)

            results.append({
                "A_col": a, "B_col": b,
                "ic_mean": round(ic_mean, 6), "ic_std": round(ic_std, 6),
                "icir": round(icir, 4), "hit_rate": round(hit, 4),
                "n_months": len(ic_arr),
                "monthly_ics": {k: round(v, 6) for k, v in sorted(avg.items())},
            })

    if not results:
        return None

    detail = results
    summary_rows = [{k: v for k, v in r.items() if k != "monthly_ics"} for r in results]
    return pd.DataFrame(summary_rows).sort_values("icir", ascending=False).reset_index(drop=True), detail


# ==================== 结果输出 ====================

def save_rank_ic(out_dir, factor_name, df):
    path = os.path.join(out_dir, "rank_ic_results.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"因子: {factor_name}\n")
        f.write(f"{'=' * 120}\n")
        f.write("Daily Rank IC (逐日 Spearman, per-horizon 尾盘截断防未来信息泄漏) — A组(X) vs B组(Y)\n")
        f.write(f"{'=' * 120}\n\n")
        f.write(df.to_string(index=False))
        f.write(f"\n\n共 {len(df)} 对\n")
        f.write(f"|Daily Rank IC| 均值: {df['|daily_rank_ic|'].mean():.6f}\n")
        f.write(f"|Daily Rank IC| 最大: {df['|daily_rank_ic|'].max():.6f}\n")
        f.write(f"逐日 ICIR 最大: {df['daily_icir'].abs().max():.4f}  hit_rate 最高: {df['hit_rate'].max():.4f}\n")
    return path


def save_bucket_analysis(out_dir, factor_name, summary_df, detail):
    path = os.path.join(out_dir, "bucket_analysis_results.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"因子: {factor_name}\n")
        f.write(f"{'=' * 120}\n")
        f.write(f"条件收益分析 — {int(summary_df['n_days'].iloc[0] if len(summary_df) else 0)} 天 五分位条件收益分析\n")
        f.write(f"{'=' * 120}\n\n")
        f.write("【摘要排名】(按 annualized_sharpe 降序)\n\n")
        f.write(summary_df.to_string(index=False))
        f.write("\n\n")
        f.write(f"{'=' * 120}\n")
        f.write("【逐对详情】\n")
        f.write(f"{'=' * 120}\n\n")

        for _, row in summary_df.iterrows():
            a, b = row["A_col"], row["B_col"]
            key = f"{a} vs {b}"
            d = detail.get(key, {})
            f.write(f"--- {a}  vs  {b} ---\n")
            f.write(f"  Annualized Sharpe:      {row['annualized_sharpe']}\n")
            f.write(f"  Annualized Spread IR:   {row['annualized_spread_ir']}\n")
            f.write(f"  Daily spread mean:      {row['daily_spread_mean']}\n")
            f.write(f"  Daily spread std:       {row['daily_spread_std']}\n")
            f.write(f"  Cumulative return:      {row['cum_ret_%']}%\n")
            f.write(f"  Cumulative spread:      {row['cumulative_spread']}\n")
            f.write(f"  Max drawdown:           {row['max_dd_%']}%\n")
            f.write(f"  Spread drawdown:        {row['spread_drawdown']}\n")
            f.write(f"  Monotonicity:           {row['monotonic']}\n")
            f.write(f"  交易天数:               {row['n_days']}\n")
            avg_grp = d.get("avg_group", {})
            if avg_grp:
                f.write(f"\n  分组平均条件收益:\n")
                for gk, gv in sorted(avg_grp.items(), key=lambda x: int(x[0])):
                    bar = "#" * max(1, min(40, int(abs(gv) * 1e6)))
                    f.write(f"    Group {int(gk)+1}: {gv:+.8f}  {bar}\n")
            f.write("\n")
    return path


def save_signal_stability(out_dir, factor_name, df):
    path = os.path.join(out_dir, "signal_stability_results.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"因子: {factor_name}\n")
        f.write(f"{'=' * 120}\n")
        f.write("信号稳定性分析 — 因子排名日间自相关\n")
        f.write("avg_rank_autocorr 高 → 排名稳定 → 信号稳定性好\n")
        f.write(f"{'=' * 120}\n\n")
        f.write(df.to_string(index=False))
        f.write(f"\n\n平均信号不稳定性: {df['signal_instability_%'].mean():.2f}%\n")
    return path


def save_daily_ic(out_dir, factor_name, summary_df, detail):
    path = os.path.join(out_dir, "daily_ic_results.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"因子: {factor_name}\n")
        f.write(f"{'=' * 120}\n")
        f.write("Daily IC — 逐天 Spearman IC 统计\n")
        f.write(f"{'=' * 120}\n\n")
        f.write("【摘要排名】(按 |t-stat| 降序)\n\n")
        f.write(summary_df.to_string(index=False))
        f.write("\n\n")
        f.write(f"{'=' * 120}\n")
        f.write("【逐对日度明细】\n")
        f.write(f"{'=' * 120}\n\n")
        for _, row in summary_df.iterrows():
            a, b = row["A_col"], row["B_col"]
            key = f"{a} vs {b}"
            daily_ics = detail.get(key, {})
            f.write(f"--- {key} ---\n")
            f.write(f"  IC均值:          {row['ic_mean']:+.6f}\n")
            f.write(f"  IC标准差:         {row['ic_std']:.6f}\n")
            f.write(f"  ICIR:            {row['icir']:.4f}\n")
            f.write(f"  胜率:            {row['hit_rate']*100:.1f}% ({row['ic_positive_days']}/{row['n_days']} 天正IC)\n")
            f.write(f"  t统计量:          {row['t_stat']:.4f}\n")
            f.write(f"  p值:             {row['p_value']:.6f}\n")
            f.write(f"  95%置信区间:      [{row['ci_95_lower']:+.6f}, {row['ci_95_upper']:+.6f}]\n")
            f.write(f"  正IC天数:         {row['ic_positive_days']}  负IC天数: {row['ic_negative_days']}\n")
            if not np.isnan(row.get('nonzero_ic_mean', np.nan)):
                f.write(f"  非零率:           {row['nonzero_rate']:.4f}\n")
                f.write(f"  非零IC均值:       {row['nonzero_ic_mean']:+.6f}\n")
                f.write(f"  非零IC标准差:     {row['nonzero_ic_std']:.6f}\n")
                f.write(f"  非零ICIR:         {row['nonzero_icir']:.4f} ({row['nonzero_n_days']} 天)\n")
            f.write(f"  日度 IC:\n")
            for d, ic in sorted(daily_ics.items()):
                bar_len = max(1, min(40, int(abs(ic) * 500)))
                bar = "#" * bar_len if ic >= 0 else "-" * bar_len
                f.write(f"    {d}: {ic:+.6f}  {bar}\n")
            f.write("\n")
    return path


def save_monthly_ic(out_dir, factor_name, summary_df, detail):
    path = os.path.join(out_dir, "monthly_ic_results.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"因子: {factor_name}\n")
        f.write(f"{'=' * 120}\n")
        f.write("月度 IC 稳定性 — Spearman IC 月度统计\n")
        f.write(f"{'=' * 120}\n\n")
        f.write("【摘要排名】(按 ICIR 降序)\n\n")
        f.write(summary_df.to_string(index=False))
        f.write("\n\n")
        f.write(f"{'=' * 120}\n")
        f.write("【逐对月度明细】\n")
        f.write(f"{'=' * 120}\n\n")
        for d in detail:
            a, b = d["A_col"], d["B_col"]
            mic = d["monthly_ics"]
            f.write(f"--- {a}  vs  {b} ---\n")
            f.write(f"  IC均值:   {d['ic_mean']:+.6f}\n")
            f.write(f"  IC标准差:  {d['ic_std']:.6f}\n")
            f.write(f"  ICIR:     {d['icir']:.4f}\n")
            f.write(f"  胜率:     {d['hit_rate']*100:.1f}% ({d['n_months']} 个月)\n")
            f.write(f"  月度 IC:\n")
            for mk, mv in sorted(mic.items()):
                bar = "#" * max(1, min(40, int(abs(mv) * 500)))
                f.write(f"    {mk}: {mv:+.6f}  {bar}\n")
            f.write("\n")
    return path


# ==================== IC 衰减提取 & 自动结论 ====================

def _extract_ic_decay(csv_rows: list, best_x_col: str) -> dict:
    """从 Pearson CSV 行中提取最佳 X 列对各时间尺度 Y 的 IC 衰减曲线。

    Y 列名格式: Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@<N>
    其中 <N> 是时间尺度 (1, 5, 10, 60, 300 等)
    """
    horizon_re = re.compile(r'\.(\w+-\w+)@(\d+)$')
    decay = {}
    for row in csv_rows:
        if row.get("A_col", "") != best_x_col:
            continue
        b_col = row.get("B_col", "")
        m = horizon_re.search(b_col)
        if m:
            horizon = int(m.group(2))
            decay[f"{horizon}s"] = row["correlation"]
    return decay


def _auto_conclusion(ic_decay: dict, best_x_col: str) -> str:
    """基于 IC 衰减曲线自动生成一句话结论。"""
    if not ic_decay:
        return ""

    # 提取因子短名 (去掉品种前缀)
    short = best_x_col.split("@")[-1] if "@" in best_x_col else best_x_col

    # 取最短和最长 horizon 的 IC
    sorted_horizons = sorted(ic_decay.keys(), key=lambda h: int(h.rstrip('s')))
    ic_short = ic_decay.get(sorted_horizons[0], 0)
    ic_long = ic_decay.get(sorted_horizons[-1]) if len(sorted_horizons) > 1 else None

    parts = []

    # 信号强度 (用最短 horizon 的 IC)
    abs_short = abs(ic_short)
    if abs_short >= 0.15:
        parts.append(f"{short}信号强(IC={ic_short:+.3f})")
    elif abs_short >= 0.10:
        parts.append(f"{short}信号中等(IC={ic_short:+.3f})")
    elif abs_short >= 0.05:
        parts.append(f"{short}信号偏弱(IC={ic_short:+.3f})")
    else:
        parts.append(f"{short}信号弱(IC={ic_short:+.3f})")

    # 衰减特征
    if ic_long is not None and abs_short > 1e-6:
        retention = abs(ic_long / ic_short) * 100
        long_label = sorted_horizons[-1]
        if retention >= 25:
            parts.append(f"{long_label}保留率{retention:.0f}% (持久)")
        elif retention >= 10:
            parts.append(f"{long_label}保留率{retention:.0f}%")
        elif retention >= 5:
            parts.append(f"衰减快, {long_label}保留率{retention:.0f}%")
        else:
            parts.append(f"衰减极快, {long_label}仅{retention:.0f}%")

        # 符号翻转检测
        if ic_short * ic_long < 0:
            parts.append("注意: 长周期符号翻转")

    return ", ".join(parts)


# ==================== 统一批量分析入口 ====================

DEEP_SUBS = {"rank_ic", "backtest", "turnover", "monthly_ic", "daily_ic"}
DEEP_SUB_LABELS = {
    "rank_ic": ("Rank IC", "[1/5]"),
    "backtest": ("条件收益", "[2/5]"),
    "turnover": ("信号稳定性", "[3/5]"),
    "monthly_ic": ("月度IC", "[4/5]"),
    "daily_ic": ("日频IC", "[5/5]"),
}


def run_analysis_batch(base_dir, mode, start_col, highlight_last_n,
                       start_date, end_date, n_groups, feval_path,
                       force=False, deep_subs=None):
    """统一批量分析: 扫描因子 → 按需执行 pearson / deep。

    这是 pearson 和 deep 两种统计分析的共享入口。
    feval 走独立的 run_feval_batch()（由调用方在 mode='full'/'feval' 时额外调用）。

    deep_subs: 当 mode='deep' 时可选的子分析集合，如 {'rank_ic', 'daily_ic'}。
               None 表示全部执行。
    """
    factors = scan_factors(base_dir)
    if not factors:
        print(f"未在 {base_dir} 中找到任何因子文件夹")
        return

    mode_label = mode.upper() if mode != "full" else "FULL"
    print(f"\n找到 {len(factors)} 个因子 ({mode_label}):\n")
    for f in factors:
        print(f"  - {f['factor_name']} ({f['data_count']} 个数据文件)")

    date_list = generate_date_list(start_date, end_date)
    need_pearson = mode in ("pearson", "full")
    need_deep = mode in ("deep", "full")
    all_csv_rows = []
    all_summary_rows = []

    # 缓存已加载数据，pearson 和 deep 共享（避免同一因子加载两次）
    data_cache = {}

    for fac in factors:
        fname = fac["factor_name"]
        folder_path = fac["folder_path"]
        dpath = fac["dailyx_path"]

        # ---- 判断是否跳过 ----
        skip = True
        if need_pearson:
            pearson_dir = os.path.join(dpath, f"{fname}_pearson")
            if not os.path.exists(pearson_dir) or force:
                skip = False
        if skip and need_deep:
            deep_dir = os.path.join(dpath, f"{fname}_deep")
            if not os.path.exists(deep_dir) or force:
                skip = False
        if skip:
            print(f"\n跳过 {fname}: 已存在结果 (使用 --force 重新计算)")

            # 仍需解析已有 pearson 结果纳入汇总 CSV
            if need_pearson:
                pearson_txt = os.path.join(dpath, f"{fname}_pearson/correlation_results.txt")
                if os.path.exists(pearson_txt):
                    try:
                        with open(pearson_txt, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                        in_summary = False
                        for line in lines:
                            if "A组<->B组交叉统计汇总" in line:
                                in_summary = True
                                continue
                            if in_summary and line.strip().startswith("---"):
                                continue
                            if in_summary and line.strip() and not line.strip().startswith("A组") and not line.strip().startswith("共"):
                                parts = line.split()
                                if len(parts) >= 5:
                                    try:
                                        float(parts[2])
                                        float(parts[3])
                                        all_csv_rows.append({
                                            "factor_name": fname,
                                            "A_col": parts[0], "B_col": parts[1],
                                            "correlation": round(float(parts[2]), 6),
                                            "p_value": round(float(parts[3]), 6),
                                            "significant": "Yes" if parts[4].startswith("Yes") else "No"
                                        })
                                    except (ValueError, IndexError):
                                        pass
                            if in_summary and line.strip().startswith("共"):
                                in_summary = False
                    except Exception:
                        pass
            continue

        print(f"\n{'=' * 60}")
        print(f"分析: {fname}")
        print(f"{'=' * 60}")

        # ---- 加载数据（pearson 和 deep 共享） ----
        daily_dfs, ga, gb, daily_rt, err = load_factor_data(dpath, date_list, start_col, highlight_last_n)
        if err:
            print(f"  跳过: {err}")
            continue

        total_rows = sum(len(df) for df in daily_dfs.values())
        print(f"  数据: {total_rows} 行, {len(ga)} X列, {len(gb)} Y列, {len(daily_dfs)} 天")

        # ---- Pearson IC ----
        if need_pearson:
            combined_df = pd.concat(list(daily_dfs.values()), ignore_index=True)
            n_total_cols = len(combined_df.columns)

            corr_matrix = np.full((n_total_cols, n_total_cols), np.nan)
            pval_matrix = np.full((n_total_cols, n_total_cols), np.nan)
            column_names = list(combined_df.columns)

            # Extract feed group for each column to avoid cross-feed X-X pairs
            def _feed_group(col):
                """Extract base product (e.g., SHFE-AG) from column name."""
                if col.startswith('X.'):
                    m = re.match(r'X\.(.+?)@', col)
                    if m:
                        return re.sub(r'@\d+$', '', m.group(1))  # SHFE-AG@1 → SHFE-AG
                elif col.startswith('Y.'):
                    m = re.search(r'\.(\w+-\w+)@', col)
                    if m:
                        return m.group(1)
                return col

            col_feed = [_feed_group(c) for c in column_names]
            col_is_x = [c.startswith('X.') for c in column_names]
            col_is_y = [c.startswith('Y.') for c in column_names]

            # Pre-extract numpy arrays for faster access
            col_arrays = [combined_df.iloc[:, i].values for i in range(n_total_cols)]

            for i in range(n_total_cols):
                for j in range(i, n_total_cols):  # upper triangle only
                    # Skip Y vs Y
                    if col_is_y[i] and col_is_y[j]:
                        continue
                    # X vs X: only same feed
                    if col_is_x[i] and col_is_x[j]:
                        if col_feed[i] != col_feed[j]:
                            continue
                    # X vs Y: always compute

                    s1 = col_arrays[i]
                    s2 = col_arrays[j]
                    mask = np.isfinite(s1) & np.isfinite(s2)
                    n_valid = mask.sum()
                    if n_valid >= 2:
                        c, p = stats.pearsonr(s1[mask], s2[mask])
                        corr_matrix[i, j] = c
                        pval_matrix[i, j] = p
                        if i != j:  # mirror to lower triangle
                            corr_matrix[j, i] = c
                            pval_matrix[j, i] = p

            corr_df = pd.DataFrame(corr_matrix, index=column_names, columns=column_names)
            pval_df = pd.DataFrame(pval_matrix, index=column_names, columns=column_names)

            pval_display = pval_df.astype(object)  # object dtype: 允许下方 setitem 带 '*' 的显著性标记字符串(如 "0.0000*"), 避免 pandas coerce_to_target_dtype 把 float64 列强转时崩溃
            for i in range(len(pval_df.index)):
                for j in range(len(pval_df.columns)):
                    val = pval_df.iloc[i, j]
                    pval_display.iloc[i, j] = "----" if pd.isna(val) else f"{val:.4f}{'*' if val < 0.05 else ''}"

            sig_count = 0
            cross_results = []
            for a_col in ga:
                for b_col in gb:
                    cv = corr_df.loc[a_col, b_col]
                    pv = pval_df.loc[a_col, b_col]
                    if pd.isna(cv) or pd.isna(pv):
                        continue
                    if pv < 0.05:
                        sig_count += 1

                    # Non-zero rate and nonzero correlation
                    x_vals = combined_df[a_col]
                    y_vals = combined_df[b_col]
                    valid_mask = x_vals.notna() & y_vals.notna()
                    nz_mask = valid_mask & (x_vals != 0)
                    nz_rate = nz_mask.sum() / valid_mask.sum() if valid_mask.sum() > 0 else 0
                    if nz_mask.sum() >= 10:
                        nz_cv, nz_pv = stats.pearsonr(x_vals[nz_mask], y_vals[nz_mask])
                    else:
                        nz_cv, nz_pv = np.nan, np.nan

                    cross_results.append({
                        "factor_name": fname, "A_col": a_col, "B_col": b_col,
                        "correlation": round(cv, 6), "p_value": round(pv, 6),
                        "significant": "Yes" if pv < 0.05 else "No",
                        "nonzero_rate": round(nz_rate, 4),
                        "nonzero_correlation": round(nz_cv, 6) if not np.isnan(nz_cv) else np.nan,
                        "nonzero_n": int(nz_mask.sum()),
                    })

            pearson_dir = os.path.join(dpath, f"{fname}_pearson")
            os.makedirs(pearson_dir, exist_ok=True)
            txt_path = os.path.join(pearson_dir, "correlation_results.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"因子名称: {fname}\n")
                f.write(f"数据量: {len(combined_df)}行 x {n_total_cols}列\n")
                f.write(f"分组: A组（前{n_total_cols - highlight_last_n}列）与B组（最后{highlight_last_n}列）\n")
                f.write(f"显著相关对数: {sig_count}\n\n")
                f.write("=" * 150 + "\n所有列间相关性矩阵（Pearson Correlation）\n" + "=" * 150 + "\n")
                f.write(corr_df.round(4).to_string() + "\n\n")
                f.write("=" * 150 + "\n所有列间p值矩阵（*表示p<0.05）\n" + "=" * 150 + "\n")
                f.write(pval_display.to_string() + "\n\n")
                f.write("=" * 160 + "\nA组<->B组交叉统计汇总\n" + "=" * 160 + "\n")
                # Dynamic column width based on actual column names
                all_a = [r["A_col"] for r in cross_results]
                all_b = [r["B_col"] for r in cross_results]
                w_a = max(len("A组列名"), max((len(x) for x in all_a), default=10)) + 2
                w_b = max(len("B组列名"), max((len(x) for x in all_b), default=10)) + 2
                w_c = len("相关系数") + 4
                w_p = len("p值") + 6
                w_s = len("显著性") + 2
                w_nr = len("非零率") + 4
                w_nc = len("非零IC") + 4
                f.write(f"{'A组列名':<{w_a}} {'B组列名':<{w_b}} {'相关系数':>{w_c}} {'p值':>{w_p}} {'显著性':>{w_s}} {'非零率':>{w_nr}} {'非零IC':>{w_nc}}\n")
                f.write("-" * (w_a + w_b + w_c + w_p + w_s + w_nr + w_nc + 6) + "\n")
                for r in cross_results:
                    if r["p_value"] < 0.001:
                        ss = "Yes ***"
                    elif r["p_value"] < 0.01:
                        ss = "Yes **"
                    elif r["p_value"] < 0.05:
                        ss = "Yes *"
                    else:
                        ss = "No"
                    nz_ic_str = f"{r['nonzero_correlation']:.6f}" if not np.isnan(r.get('nonzero_correlation', np.nan)) else "N/A"
                    f.write(f"{r['A_col']:<{w_a}} {r['B_col']:<{w_b}} {r['correlation']:>{w_c}.6f} {r['p_value']:>{w_p}.6f} {ss:>{w_s}} {r['nonzero_rate']:>{w_nr}.4f} {nz_ic_str:>{w_nc}}\n")
                f.write("-" * 120 + "\n")
                f.write(f"共 {sig_count} 对显著相关（p<0.05）\n")

            print(f"  Pearson IC: {len(combined_df)}行 x {n_total_cols}列, {sig_count}对显著相关")
            all_csv_rows.extend(cross_results)

        # ---- 深度分析 ----
        if need_deep:
            active_subs = deep_subs if deep_subs else DEEP_SUBS
            out_dir = os.path.join(dpath, f"{fname}_deep")
            os.makedirs(out_dir, exist_ok=True)
            files = {}

            dic_df, dic_detail = None, None
            rank_df = None
            ba_df, ba_detail = None, None
            ss_df = None
            mi_df, mi_detail = None, None

            if "daily_ic" in active_subs:
                label, idx = DEEP_SUB_LABELS["daily_ic"]
                print(f"  {idx} {label}...", end=" ", flush=True)
                dic_result = compute_daily_ic(daily_dfs, ga, gb, daily_rt)
                if dic_result:
                    dic_df, dic_detail = dic_result
                    print(f"{len(dic_df)} 对")
                else:
                    print("0 对 (天数不足)")

            if "rank_ic" in active_subs:
                label, idx = DEEP_SUB_LABELS["rank_ic"]
                print(f"  {idx} {label}...", end=" ", flush=True)
                rank_df = compute_rank_ic(daily_dfs, ga, gb, daily_rt)
                print(f"{len(rank_df) if rank_df is not None else 0} 对")

            if "backtest" in active_subs:
                label, idx = DEEP_SUB_LABELS["backtest"]
                print(f"  {idx} {label}...", end=" ", flush=True)
                ba_df, ba_detail = compute_bucket_analysis(daily_dfs, ga, gb, n_groups)
                print(f"{len(ba_df) if ba_df is not None else 0} 对")

            if "turnover" in active_subs:
                label, idx = DEEP_SUB_LABELS["turnover"]
                print(f"  {idx} {label}...", end=" ", flush=True)
                ss_df = compute_signal_rank_stability(daily_dfs, ga, n_groups)
                print(f"{len(ss_df) if ss_df is not None else 0} 个因子")

            if "monthly_ic" in active_subs:
                label, idx = DEEP_SUB_LABELS["monthly_ic"]
                print(f"  {idx} {label}...", end=" ", flush=True)
                mi_result = compute_monthly_ic(daily_dfs, ga, gb)
                if mi_result:
                    mi_df, mi_detail = mi_result
                    print(f"{len(mi_df)} 对")
                else:
                    print("0 对 (月份不足)")

            if dic_df is not None:
                files["Daily IC"] = save_daily_ic(out_dir, fname, dic_df, dic_detail)
                dic_df.to_csv(os.path.join(out_dir, "daily_ic_summary.csv"), index=False)
                best_dic = dic_df.iloc[0]
                all_summary_rows.append({"factor": fname, "analysis": "Daily IC", "metric": "best_daily_ic_tstat", "value": best_dic["t_stat"], "pair": f"{best_dic['A_col']} vs {best_dic['B_col']}"})

            if rank_df is not None:
                files["Rank IC"] = save_rank_ic(out_dir, fname, rank_df)
                rank_df.to_csv(os.path.join(out_dir, "rank_ic_summary.csv"), index=False)
                all_summary_rows.append({"factor": fname, "analysis": "Rank IC", "metric": "|daily_rank_ic|_max", "value": rank_df["|daily_rank_ic|"].max()})
                all_summary_rows.append({"factor": fname, "analysis": "Rank IC", "metric": "daily_icir_max", "value": rank_df["daily_icir"].abs().max()})

            if ba_df is not None:
                files["Conditional Return"] = save_bucket_analysis(out_dir, fname, ba_df, ba_detail)
                ba_df.to_csv(os.path.join(out_dir, "bucket_analysis_summary.csv"), index=False)
                best = ba_df.iloc[0]
                all_summary_rows.extend([
                    {"factor": fname, "analysis": "Conditional Return", "metric": "best_annualized_sharpe", "value": best["annualized_sharpe"], "pair": f"{best['A_col']} vs {best['B_col']}"},
                    {"factor": fname, "analysis": "Conditional Return", "metric": "best_cum_ret_%", "value": best["cum_ret_%"], "pair": f"{best['A_col']} vs {best['B_col']}"},
                ])

            if ss_df is not None:
                files["Signal Stability"] = save_signal_stability(out_dir, fname, ss_df)
                ss_df.to_csv(os.path.join(out_dir, "signal_stability_summary.csv"), index=False)
                all_summary_rows.append({"factor": fname, "analysis": "Signal Stability", "metric": "avg_signal_instability_%", "value": ss_df["signal_instability_%"].mean()})

            if mi_df is not None:
                files["Monthly IC"] = save_monthly_ic(out_dir, fname, mi_df, mi_detail)
                mi_df.to_csv(os.path.join(out_dir, "monthly_ic_summary.csv"), index=False)
                best_mi = mi_df.iloc[0]
                all_summary_rows.extend([
                    {"factor": fname, "analysis": "Monthly IC", "metric": "best_icir", "value": best_mi["icir"], "pair": f"{best_mi['A_col']} vs {best_mi['B_col']}"},
                    {"factor": fname, "analysis": "Monthly IC", "metric": "best_ic_mean", "value": best_mi["ic_mean"], "pair": f"{best_mi['A_col']} vs {best_mi['B_col']}"},
                ])

            for label, fp in files.items():
                print(f"  {label}: {fp}")

        # ---- 重命名文件夹 ----
        new_folder = os.path.join(base_dir, fname)
        if folder_path != new_folder:
            try:
                os.rename(folder_path, new_folder)
                print(f"  重命名: {os.path.basename(folder_path)} -> {fname}")
            except Exception as e:
                print(f"  重命名失败: {e}")

    # ---- 汇总 CSV ----
    if all_csv_rows:
        csv_path = os.path.join(base_dir, "all_factors_pearson_summary.csv")
        if os.path.exists(csv_path):
            existing = pd.read_csv(csv_path)
            combined = pd.concat([existing, pd.DataFrame(all_csv_rows)], ignore_index=True)
            combined = combined.drop_duplicates(subset=["factor_name", "A_col", "B_col"], keep="last")
        else:
            combined = pd.DataFrame(all_csv_rows)
        try:
            combined.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"\n汇总CSV: {csv_path} ({len(combined)} 行)")
        except PermissionError:
            alt_path = os.path.join(base_dir, "all_factors_correlation_results_new.csv")
            combined.to_csv(alt_path, index=False, encoding="utf-8-sig")
            print(f"\n汇总CSV: {alt_path} ({len(combined)} 行)")

    if all_summary_rows:
        csv_path = os.path.join(base_dir, "all_factors_deep_summary.csv")
        pd.DataFrame(all_summary_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"汇总CSV: {csv_path} ({len(all_summary_rows)} 行)")

    # ---- 日志 ----
    try:
        from factor_logger import append_submission_log, append_experiment_log
        factor_names = [f["factor_name"] for f in factors]
        append_submission_log("factor-check", mode, {
            "因子": ", ".join(factor_names) if len(factor_names) <= 5 else f"{len(factor_names)} 个",
            "输出": base_dir,
        })
        # 实验日志: pearson 最佳相关系数 + IC 衰减自动结论
        if need_pearson and all_csv_rows:
            best = max(all_csv_rows, key=lambda r: abs(r.get("correlation", 0)))
            append_experiment_log(
                best["factor_name"],
                f"r={best['correlation']:.4f} (p={best['p_value']:.4f})",
                f"{best['factor_name']}/dailyX/{best['factor_name']}_pearson/",
                base_dir,
            )
            # 逐因子提取 IC 衰减曲线并生成自动结论
            for fac in factors:
                fname = fac["factor_name"]
                fac_rows = [r for r in all_csv_rows if r["factor_name"] == fname]
                if not fac_rows:
                    continue
                best_row = max(fac_rows, key=lambda r: abs(r.get("correlation", 0)))
                best_x_col = best_row.get("A_col", "")
                ic_decay = _extract_ic_decay(fac_rows, best_x_col)
                if not ic_decay:
                    continue
                conclusion = _auto_conclusion(ic_decay, best_x_col)
                append_rich_experiment_log(
                    factor_name=fname,
                    result_path=f"{fname}/dailyX/{fname}_pearson/",
                    output_dir=base_dir,
                    ic_decay=ic_decay,
                    conclusion=conclusion,
                )
        # 实验日志: deep 最佳指标
        if need_deep and all_summary_rows:
            best_sharpe = max(
                [r for r in all_summary_rows if r.get("metric") == "best_annualized_sharpe"],
                key=lambda r: abs(r.get("value", 0)),
                default=None,
            )
            if best_sharpe:
                append_experiment_log(
                    best_sharpe["factor"],
                    f"Sharpe={best_sharpe['value']:.2f}",
                    f"{best_sharpe['factor']}/dailyX/{best_sharpe['factor']}_deep/",
                    base_dir,
                )
    except Exception:
        pass


def run_feval_batch(output_dir, feval_path, force=False):
    """feval 批量评估: 扫描因子目录 → 内存合并 xy → 调用 FeatureEvaluator（不写盘）

    输出到 {factor}/dailyX/{factor}_feval/，汇总到 all_factors_feval_summary.csv。
    """
    factors = scan_factors(output_dir)
    if not factors:
        print("  未找到 dailyX 数据目录")
        return

    all_summary_rows = []

    for fac in factors:
        factor_name = fac["factor_name"]
        dailyx_dir = fac["dailyx_path"]
        report_dir = os.path.join(dailyx_dir, f"{factor_name}_feval")

        # 跳过已存在
        if os.path.exists(report_dir) and not force:
            print(f"  {factor_name}: 跳过 (feval 已存在，使用 --force 重新计算)")
            continue

        combined, _ = merge_daily_xy(dailyx_dir)
        if combined is None or combined.empty:
            print(f"  {factor_name}: 无 daily-*.xy 文件，跳过")
            continue

        print(f"  合并: {len(combined):,} 行（内存）")
        result = run_feval_eval(combined, report_dir, factor_name, feval_path)

        # 汇总: 从 screening_df 提取 Top 指标
        sd = result.screening_df
        if not sd.empty:
            sd = sd.copy()
            sd['factor'] = factor_name
            # 取每对 x_col, y_col 的核心指标
            for _, row in sd.iterrows():
                all_summary_rows.append({
                    "factor": factor_name,
                    "x_col": row.get("x_col", ""),
                    "y_col": row.get("y_col", ""),
                    "ic_mean": row.get("ic_mean", 0),
                    "icir": row.get("ic_ir", 0),               # feval screening_df 真实列名 ic_ir(原 'icir' 取不到恒为 0, 掩盖因子质量)
                    "spearman": row.get("spearman_r", 0),      # feval 列名 spearman_r
                    "sign_match": row.get("sign_match_rate", 0),  # feval 列名 sign_match_rate
                })

        # Train/Test Decay 汇总
        td = result.train_test_df
        if not td.empty:
            n_robust = (td['ic_decay'].abs() > 0.7).sum()
            n_severe = (td['ic_decay'].abs() <= 0.3).sum()
            all_summary_rows.append({
                "factor": factor_name,
                "x_col": "", "y_col": "",
                "ic_mean": 0, "icir": 0,
                "spearman": 0, "sign_match": 0,
                "decay_robust": n_robust, "decay_severe": n_severe,
            })

    # 汇总 CSV
    if all_summary_rows:
        csv_path = os.path.join(output_dir, "all_factors_feval_summary.csv")
        pd.DataFrame(all_summary_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\n汇总CSV: {csv_path} ({len(all_summary_rows)} 行)")

    # ---- 日志 ----
    try:
        from factor_logger import append_submission_log, append_experiment_log
        factor_names = [f["factor_name"] for f in factors]
        append_submission_log("factor-check", "feval评估", {
            "因子": ", ".join(factor_names) if len(factor_names) <= 5 else f"{len(factor_names)} 个",
            "输出": output_dir,
        })
        # 实验日志: 每个因子的最佳 screening IC
        for fac in factors:
            fname = fac["factor_name"]
            fac_rows = [r for r in all_summary_rows
                        if r.get("factor") == fname and r.get("ic_mean") != 0]
            if fac_rows:
                best = max(fac_rows, key=lambda r: abs(r.get("ic_mean", 0)))
                append_experiment_log(
                    fname,
                    f"IC={best['ic_mean']:.4f}, ICIR={best['icir']:.2f}",
                    f"{fname}/dailyX/{fname}_feval/",
                    output_dir,
                )
    except Exception:
        pass


# ==================== HTML 总结报告 ====================

def _generate_html_report(output_dir):
    """生成 HTML 总结报告（full mode 完成后调用）。"""
    try:
        from html_summary import generate_summary_report
        generate_summary_report(output_dir)
    except ImportError:
        print("  html_summary.py 未找到，跳过 HTML 报告")
    except Exception as e:
        print(f"  HTML 报告生成失败: {e}")


# ==================== 核心流程 ====================

def cmd_status(args):
    """查看因子状态"""
    cookie = ensure_cookie(args.cookie)
    if not cookie:
        print("错误: 未提供 cookie。用 --cookie 或先 save-cookie")
        sys.exit(1)
    username, factors = fetch_factors(cookie)
    print(f"用户: {username}  |  共 {len(factors)} 个因子任务\n")
    print(f"{'#':<4} {'Feature':<35} {'State':<10} {'DownloadOK'}")
    print("-" * 75)
    for i, f in enumerate(factors, 1):
        state = "OK" if f["state"] == "success" else f["state"]
        dl_ok = "Yes" if f["download_url"] else "No"
        print(f"{i:<4} {f['feature']:<35} {state:<10} {dl_ok}")


def cmd_run(args):
    """一键全流程: 提交 → 等待 → 下载 → 解压 → 评估"""
    cookie = ensure_cookie(args.cookie)
    if not cookie:
        print("错误: 未提供 cookie。用 --cookie 或先 save-cookie")
        sys.exit(1)

    output_dir = os.path.abspath(args.dir)
    os.makedirs(output_dir, exist_ok=True)

    feeds = args.feeds or "SHFE-AG,SHFE-AG@1,SHFE-CU,SHFE-CU@1"
    start_date = args.start_date or DEFAULT_START_DATE
    end_date = args.end_date or DEFAULT_END_DATE
    feval_path = os.path.abspath(args.feval or DEFAULT_FEVAL_PATH)
    mode = args.mode or "feval"

    target_names = []

    # ========== Phase 1: 提交 ==========
    if not args.skip_submit and args.h_dir:
        h_dir = os.path.abspath(args.h_dir)
        h_files = sorted(glob.glob(os.path.join(h_dir, "*.h")))
        if not h_files:
            print(f"错误: 在 {h_dir} 中未找到 .h 文件")
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"Phase 1: 提交因子 ({len(h_files)} 个)")
        print(f"{'='*60}")

        for h_file in h_files:
            cls, is_template, template_args = extract_class_name(h_file)
            if not cls:
                print(f"  跳过 {h_file}: 无法提取类名")
                continue
            factor_name = Path(h_file).stem
            submit_factor(cookie, h_file, cls, is_template, template_args, feeds, start_date, end_date)
            target_names.append(factor_name)
    elif args.names:
        target_names = [n.strip() for n in args.names.split(",")]
    else:
        print("未指定 --h-dir 或 --names，将下载所有成功的因子")

    # ========== Phase 2: 等待完成 ==========
    if target_names and not args.skip_wait:
        print(f"\n{'='*60}")
        print(f"Phase 2: 等待因子计算完成")
        print(f"{'='*60}")

        # 平台排队(queued/running)一直等：超时放弃没意义——重 submit 新 job 照样排队。
        # 只在全部到终态(success/failed)才退出。极端(平台挂死 state 永不变)需 Ctrl-C 手动介入。
        interval = 60
        elapsed = 0
        while True:
            time.sleep(interval)
            elapsed += interval
            _, factors = fetch_factors(cookie)
            factor_map = {f["feature"]: f for f in factors}

            pending = []
            for name in target_names:
                f = factor_map.get(name)
                if f:
                    if f["state"] == "success":
                        pass
                    elif f["state"] == "failed":
                        print(f"  {name}: 失败!")
                    else:
                        pending.append(name)
                else:
                    pending.append(name)

            if not pending:
                print(f"  全部完成! (等待 {elapsed}s)")
                break
            print(f"  [{elapsed}s] 等待中... 剩余 {len(pending)}: {', '.join(pending[:3])}{'...' if len(pending) > 3 else ''}")

    # ========== Phase 3: 下载 ==========
    if not args.skip_download:
        print(f"\n{'='*60}")
        print(f"Phase 3: 下载因子数据")
        print(f"{'='*60}")

        _, factors = fetch_factors(cookie)

        if target_names:
            to_download = [f for f in factors if f["feature"] in target_names and f["download_url"]]
        else:
            to_download = [f for f in factors if f["state"] == "success" and f["download_url"]]

        if not to_download:
            print("  没有可下载的因子")
            sys.exit(1)

        processes = []
        for f in to_download:
            fname = f["feature"]
            dl_url = f"{HOST}{f['download_url']}"
            tar_path = os.path.join(output_dir, f"{fname}.tar.gz")
            print(f"  下载: {fname} ...", end="", flush=True)

            p = subprocess.Popen(
                ["curl", "-s", "-L", "-k", "--max-time", "600", "-o", tar_path,
                 "-b", f"{COOKIE_NAME}={cookie}", dl_url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            processes.append((p, fname, tar_path))

        for p, fname, tar_path in processes:
            p.wait()
            if os.path.exists(tar_path) and os.path.getsize(tar_path) > 1000:
                size_mb = os.path.getsize(tar_path) / 1024 / 1024
                print(f" OK ({size_mb:.0f}MB)")
            else:
                print(f" 失败 (文件大小异常)")

        # ========== Phase 4: 解压 ==========
        print(f"\n{'='*60}")
        print(f"Phase 4: 解压并清理")
        print(f"{'='*60}")

        tar_files = sorted(glob.glob(os.path.join(output_dir, "*.tar.gz")))
        for tar_path in tar_files:
            fname = Path(tar_path).stem
            extract_dir = os.path.join(output_dir, fname)
            print(f"  解压: {fname}/")
            try:
                os.makedirs(extract_dir, exist_ok=True)
                with tarfile.open(tar_path, "r:gz") as tar:
                    tar.extractall(path=extract_dir)
                os.remove(tar_path)
                file_count = sum(len(files) for _, _, files in os.walk(extract_dir))
                print(f"    OK ({file_count} 个文件, 已删除压缩包)")
            except Exception as e:
                print(f"    失败: {e}")

    # ========== Phase 5: 评估 ==========
    if not args.skip_analyze:
        print(f"\n{'='*60}")
        print(f"Phase 5: 因子评估 (mode={mode})")
        print(f"{'='*60}")

        if mode in ("feval", "full"):
            run_feval_batch(output_dir, feval_path)

        if mode in ("pearson", "deep", "full"):
            run_analysis_batch(output_dir, mode, DEFAULT_START_COL, DEFAULT_HIGHLIGHT_LAST_N,
                               start_date, end_date, DEFAULT_N_GROUPS, feval_path, force=args.force)

    # ========== Phase 6: HTML 总结报告 ==========
    if not args.skip_analyze and mode == "full":
        print(f"\n{'='*60}")
        print("Phase 6: 生成 HTML 总结报告")
        print(f"{'='*60}")
        _generate_html_report(output_dir)

    print(f"\n{'='*60}")
    print(f"全部完成! 输出目录: {output_dir}")
    print(f"{'='*60}")


def cmd_analyze(args):
    """仅运行评估（已下载的数据）"""
    output_dir = os.path.abspath(args.dir)
    if not os.path.isdir(output_dir):
        print(f"错误: 目录不存在 {output_dir}")
        sys.exit(1)

    feval_path = os.path.abspath(args.feval or DEFAULT_FEVAL_PATH)
    mode = args.mode or "feval"
    if args.start_date or args.end_date:
        start_date = args.start_date or DEFAULT_START_DATE
        end_date = args.end_date or DEFAULT_END_DATE
    else:
        start_date, end_date = detect_date_range(output_dir)
        if start_date is None:
            start_date, end_date = DEFAULT_START_DATE, DEFAULT_END_DATE
        else:
            print(f"  自动检测日期范围: {start_date} ~ {end_date}")

    if mode in ("feval", "full"):
        run_feval_batch(output_dir, feval_path)

    if mode in ("pearson", "deep", "full"):
        run_analysis_batch(output_dir, mode, DEFAULT_START_COL, DEFAULT_HIGHLIGHT_LAST_N,
                           start_date, end_date, DEFAULT_N_GROUPS, feval_path, force=args.force)

    if mode == "full" and not getattr(args, 'skip_html', False):
        _generate_html_report(output_dir)


# ==================== 入口 ====================

def main():
    parser = argparse.ArgumentParser(
        prog="factor_evaluate",
        description="因子评估一键脚本 (submit → download → evaluate)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
评估模式 (--mode):
  feval    feval 7维评估（含可视化报告）       [默认]
  pearson  Pearson IC 相关系数批量分析
  deep     因子信息诊断: Daily IC / Rank IC / 条件收益 / 信号稳定性 / 月度IC
  full     以上全部

示例:
  # 一键全流程（提交 + 下载 + feval 评估）
  python3 factor_evaluate.py run --dir ./out --h-dir ./factors --cookie <cookie>

  # 一键全流程 + 全部评估模式
  python3 factor_evaluate.py run --dir ./out --h-dir ./factors --mode full

  # 已下载数据，仅跑深度分析
  python3 factor_evaluate.py analyze --dir ./out --mode deep

  # 已下载数据，跑全部评估
  python3 factor_evaluate.py analyze --dir ./out --mode full

  # 查看因子状态
  python3 factor_evaluate.py status --cookie <cookie>
"""
    )
    parser.add_argument("--cookie", help="session cookie 值")

    sub = parser.add_subparsers(dest="command")

    # run
    run_parser = sub.add_parser("run", help="一键全流程: 提交 → 等待 → 下载 → 解压 → 评估")
    run_parser.add_argument("--dir", "-d", required=True, help="输出目录")
    run_parser.add_argument("--h-dir", help=".h 文件所在目录（自动提取类名并提交）")
    run_parser.add_argument("--names", help="因子名列表，逗号分隔（跳过提交）")
    run_parser.add_argument("--cookie", help="session cookie")
    run_parser.add_argument("--feeds", help="交易品种（默认 SHFE-AG,SHFE-AG@1,SHFE-CU,SHFE-CU@1）")
    run_parser.add_argument("--start-date", help="起始日期 YYYY-MM-DD（默认 2024-01-02）")
    run_parser.add_argument("--end-date", help="结束日期 YYYY-MM-DD（默认 2024-06-30）")
    run_parser.add_argument("--mode", choices=["feval", "pearson", "deep", "full"], default="feval",
                            help="评估模式（默认 feval）")
    run_parser.add_argument("--skip-submit", action="store_true", help="跳过提交步骤")
    run_parser.add_argument("--skip-wait", action="store_true",
                            help="跳过等待平台计算完成（默认会等待；与 --skip-submit 正交）")
    run_parser.add_argument("--skip-download", action="store_true", help="跳过下载步骤")
    run_parser.add_argument("--skip-analyze", action="store_true", help="跳过评估步骤")
    run_parser.add_argument("--max-wait", type=int, default=7200, help="等待因子完成的最大秒数（默认 7200=2h，覆盖平台积压）")
    run_parser.add_argument("--feval", help=f"feval 包路径（默认 {DEFAULT_FEVAL_PATH}）")
    run_parser.add_argument("--force", action="store_true", help="强制重新计算（覆盖已有结果）")

    # analyze
    analyze_parser = sub.add_parser("analyze", help="仅运行因子评估（已下载的数据）")
    analyze_parser.add_argument("--dir", "-d", required=True, help="数据目录")
    analyze_parser.add_argument("--mode", choices=["feval", "pearson", "deep", "full"], default="feval",
                                help="评估模式（默认 feval）")
    analyze_parser.add_argument("--start-date", help="起始日期 YYYY-MM-DD")
    analyze_parser.add_argument("--end-date", help="结束日期 YYYY-MM-DD")
    analyze_parser.add_argument("--feval", help=f"feval 包路径（默认 {DEFAULT_FEVAL_PATH}）")
    analyze_parser.add_argument("--force", action="store_true", help="强制重新计算（覆盖已有结果）")
    analyze_parser.add_argument("--skip-html", action="store_true", help="跳过 HTML 报告生成（由 Claude 单独调用）")

    # status
    status_parser = sub.add_parser("status", help="查看 featuretool 因子状态")
    status_parser.add_argument("--cookie", help="session cookie")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "status":
        cmd_status(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "analyze":
        cmd_analyze(args)


if __name__ == "__main__":
    main()
