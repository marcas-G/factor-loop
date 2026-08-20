"""阶段 D'：刷新因子日级 IC 序列向量（替代值序列向量）。

核心改动 vs refresh_factor_vectors.py：
  - 不存因子"值"序列，存"预测能力"序列（IC）
  - 每个 (factor, symbol, freq, y_horizon) 一条向量
  - 业务语义：IC 序列相似的因子 = 预测行为同涨同跌 = 真冗余

IC 定义：
  对每个交易日 t，算该日所有 tick 的 corr(X_t, Y_h_t)
  → 单日一个 IC 值，范围 [-1, 1]
  → 拼成 N 日 IC 序列

数学保证：
  - IC 序列做 z-score + L2 归一化后，L2 距离 → cos → Pearson
  - 两个因子 IC 序列的 Pearson 高 = 它们的预测能力同涨同跌
  - 这比"值序列相似"更贴近业务冗余定义

流程：
  1. featuretool 下载因子（dailyX/*.xy）
  2. 解析 xy，对每个 (X 列, Y horizon) 按日算 IC，得到 IC 序列
  3. 取最近 250 日，z-score + L2 归一化
  4. 写入 factor_ic_vec + factor_ic_vec_meta

用法:
    python core/tools/refresh_factor_ic_vectors.py                # 全量 evaluated
    python core/tools/refresh_factor_ic_vectors.py --xname Foo    # 单个
    python core/tools/refresh_factor_ic_vectors.py --force        # 强制重算
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import db

from core.config import CACHE_ROOT as CACHE_DIR  # noqa: E402  持久缓存(89% 命中)
CACHE_MAX = 20  # 缓存上限(LRU):超限删最旧 dailyX,控制磁盘(~6G);factor_ic_daily 不受影响
WINDOW_SIZE = 250
MIN_SAMPLES = 30               # 至少 30 日 IC 才存向量
MIN_TICKS_PER_DAY = 30         # 单日至少 30 个有效 tick 才算 IC


def parse_x_column(col: str) -> tuple[str, str]:
    """X.SHFE-AG@1@kyle_lambda_volatility_w20_min50 → ('SHFE-AG@1', 'kyle_lambda_volatility_w20_min50')"""
    body = col[2:]
    idx = body.rfind("@")
    return body[:idx], body[idx + 1:]


def x_symbol_root(x_symbol: str) -> str:
    """SHFE-AG@1 → SHFE-AG；SHFE-AG → SHFE-AG"""
    return x_symbol.split("@")[0]


def parse_y_column(col: str) -> tuple[str, int]:
    """Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1 → ('SHFE-AG', 1)"""
    m = re.match(r"Y\..*?\.(.+?)@(\d+)$", col)
    if not m:
        return "", 0
    return m.group(1), int(m.group(2))


def prune_cache(cache_dir: Path, max_n: int = CACHE_MAX) -> None:
    """LRU:缓存因子目录超 max_n,删最旧(by mtime)。控制磁盘——删的只是 dailyX 原始数据,
    factor_ic_daily(IC 结果)在数据库,不受影响;重算被删的因子要重新下载。"""
    if not cache_dir.exists():
        return
    dirs = [d for d in cache_dir.iterdir() if d.is_dir()]
    if len(dirs) <= max_n:
        return
    dirs.sort(key=lambda d: d.stat().st_mtime)  # 旧→新
    for d in dirs[: len(dirs) - max_n]:
        shutil.rmtree(d, ignore_errors=True)
        print(f"  [cache LRU] 删旧缓存: {d.name}")


def download_factor(xname: str, cache_dir: Path) -> Path | None:
    target_dir = cache_dir / xname
    dailyx_dir = target_dir / "dailyX"

    if dailyx_dir.exists() and any(dailyx_dir.iterdir()):
        return dailyx_dir

    prune_cache(cache_dir)  # 下载前 LRU:超 20 删最旧

    if target_dir.exists():
        shutil.rmtree(target_dir)

    cli = ROOT / "featuretool-tmp" / "skills" / "featuretool" / "featuretool.py"
    if not cli.exists():
        cli = Path("/home/lgao/work/quant/featuretool-tmp/skills/featuretool/featuretool.py")

    result = subprocess.run(
        ["python3", str(cli), "download", "--names", xname, "-o", str(cache_dir)],
        capture_output=True, text=True, timeout=900,
    )
    if result.returncode != 0 or not dailyx_dir.exists():
        print(f"  [下载失败] {xname}: {result.stderr[:200]}")
        return None
    return dailyx_dir


def load_ic_series(dailyx_dir: Path) -> dict[tuple[str, str, int], pd.Series]:
    """读 xy，对每个 (x_col, freq, y_horizon) 按日算 IC。

    返回 {(x_symbol, freq, y_horizon): pd.Series[date -> ic]}。

    一个 (x_symbol, freq, y_horizon) 可能有多个 X 列映射到同一个（比如 @1 合约和主力
    合约可能都映射到同一个 x_symbol_root），这里把每个 X 列当作独立条目，不合并。
    """
    xy_files = sorted(dailyx_dir.glob("daily-*.xy"))
    if not xy_files:
        return {}

    ic_per_key: dict[tuple, dict] = {}

    for f in xy_files:
        try:
            df = pd.read_csv(f)
        except Exception as e:
            print(f"    [skip] {f.name}: {e}")
            continue

        df["date"] = pd.to_datetime(df["receive_time"], unit="ns").dt.date

        x_cols = [c for c in df.columns if c.startswith("X.")]
        y_cols = [c for c in df.columns if c.startswith("Y.")]
        if not x_cols or not y_cols:
            continue

        # 预解析 Y 列
        y_parsed = [(c, *parse_y_column(c)) for c in y_cols]
        y_by_root: dict[str, list[tuple[str, int]]] = {}
        for yc, y_root, y_h in y_parsed:
            y_by_root.setdefault(y_root, []).append((yc, y_h))

        for x_col in x_cols:
            x_symbol, freq = parse_x_column(x_col)
            x_root = x_symbol_root(x_symbol)
            if x_root not in y_by_root:
                continue

            for y_col, y_h in y_by_root[x_root]:
                key = (x_symbol, freq, y_h)

                # 按日算 IC
                for date, day_df in df.groupby("date"):
                    xv = day_df[x_col].to_numpy(dtype=np.float64)
                    yv = day_df[y_col].to_numpy(dtype=np.float64)
                    mask = np.isfinite(xv) & np.isfinite(yv)
                    if mask.sum() < MIN_TICKS_PER_DAY:
                        continue
                    xc, yc_ = xv[mask], yv[mask]
                    if xc.std() < 1e-10 or yc_.std() < 1e-10:
                        continue
                    ic = float(np.corrcoef(xc, yc_)[0, 1])
                    if not np.isfinite(ic):
                        continue
                    ic_per_key.setdefault(key, {})[date] = ic

    return {
        k: pd.Series(v).sort_index()
        for k, v in ic_per_key.items() if v
    }


def standardize_ic(ic_series: pd.Series) -> tuple[np.ndarray | None, dict]:
    """IC 序列取最近 N 日，z-score + L2 归一化。

    IC 本身在 [-1, 1] 区间，不需要 winsorize（极端值往往是信号）。
    """
    n_total = len(ic_series)
    if n_total < MIN_SAMPLES:
        return None, {"n_samples": n_total, "reason": f"样本不足 (<{MIN_SAMPLES})"}

    recent = ic_series.tail(WINDOW_SIZE)
    values = recent.to_numpy(dtype=np.float64)
    n = len(values)

    mean, std = float(values.mean()), float(values.std())
    if std < 1e-10:
        return None, {"n_samples": n, "reason": "IC 方差为 0"}

    z = (values - mean) / std

    if n < WINDOW_SIZE:
        pad = np.zeros(WINDOW_SIZE - n, dtype=np.float32)
        vec = np.concatenate([pad, z.astype(np.float32)])
    else:
        vec = z.astype(np.float32)

    norm = float(np.linalg.norm(vec))
    if norm > 1e-10:
        vec = vec / norm

    return vec, {
        "n_samples": n,
        "start_date": str(recent.index[0]),
        "end_date": str(recent.index[-1]),
        "mean_ic": mean,
        "std_ic": std,
        "icir": mean / std if std > 1e-10 else 0.0,
    }


def clear_existing(conn, factor_xname: str | None) -> None:
    if factor_xname:
        conn.execute(
            "DELETE FROM factor_ic_vec WHERE factor_xname = ?",
            (factor_xname,),
        )
        conn.execute(
            "DELETE FROM factor_ic_vec_meta WHERE factor_xname = ?",
            (factor_xname,),
        )
        conn.execute(
            "DELETE FROM factor_ic_daily WHERE factor_xname = ?",
            (factor_xname,),
        )
    else:
        conn.execute("DELETE FROM factor_ic_vec")
        conn.execute("DELETE FROM factor_ic_vec_meta")
        conn.execute("DELETE FROM factor_ic_daily")


def write_vectors(conn, factor_xname: str, items: list[dict]) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds") + "Z"
    written = 0
    for it in items:
        if it.get("vec") is None:
            continue
        blob = it["vec"].tobytes()
        conn.execute(
            """
            INSERT INTO factor_ic_vec
                (factor_xname, symbol, freq, y_horizon, embedding)
            VALUES (?, ?, ?, ?, ?)
            """,
            (factor_xname, it["symbol"], it["freq"], it["y_horizon"], blob),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO factor_ic_vec_meta
                (factor_xname, symbol, freq, y_horizon, n_samples,
                 start_date, end_date, mean_ic, std_ic, icir, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                factor_xname, it["symbol"], it["freq"], it["y_horizon"],
                it["n_samples"], it["start_date"], it["end_date"],
                it["mean_ic"], it["std_ic"], it["icir"], now,
            ),
        )
        written += 1
    return written


def write_daily_ic(conn, factor_xname: str, items: list[dict]) -> int:
    """把原始日级 IC 序列(归一化前)写入 factor_ic_daily,供 residual_ic_strength 正交用。

    与 write_vectors 同因子级调用(clear_existing 已按因子清表)。样本不足被 standardize_ic
    跳过的项(vec is None)不写——这些也进不了 ANN 检索,口径一致。
    """
    written = 0
    for it in items:
        if it.get("vec") is None or it.get("ic_series") is None:
            continue
        rows = [
            (factor_xname, it["symbol"], it["freq"], it["y_horizon"], str(d), float(ic))
            for d, ic in it["ic_series"].items()
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO factor_ic_daily
               (factor_xname, symbol, freq, y_horizon, date, ic)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        written += len(rows)
    return written


def process_factor(conn, xname: str, cache_dir: Path, force: bool) -> list[dict]:
    exists = conn.execute(
        "SELECT 1 FROM factors WHERE xname = ?", (xname,)
    ).fetchone()
    if not exists:
        print(
            f"  [skip] {xname} 不在 factors 表，请先跑 core/tools/import_factors.py 登记元信息",
            file=sys.stderr,
        )
        return []

    if not force:
        existing = conn.execute(
            "SELECT 1 FROM factor_ic_vec_meta WHERE factor_xname = ? LIMIT 1",
            (xname,),
        ).fetchone()
        if existing:
            print(f"  [skip] {xname} 已有 IC 向量（--force 强制重算）")
            return []

    # 平台 feature 名 = .h file stem（download --names 要用 file stem, 不是 xname;
    # xname≠file_stem 时如 BHHI vs book_HHI 会下载失败）
    fp_row = conn.execute("SELECT file_path FROM factors WHERE xname = ?", (xname,)).fetchone()
    dl_name = Path(fp_row[0]).stem if fp_row and fp_row[0] else xname
    print(f"  [下载] {xname} (平台名 {dl_name}) ...")
    dailyx_dir = download_factor(dl_name, cache_dir)
    if not dailyx_dir:
        return []

    print(f"  [解析] {dailyx_dir}")
    ic_map = load_ic_series(dailyx_dir)
    if not ic_map:
        print(f"  [空] {xname} 无可算 IC 的 (X, Y) 对")
        return []

    items = []
    for (symbol, freq, y_horizon), ic_series in ic_map.items():
        vec, meta = standardize_ic(ic_series)
        if vec is None:
            print(f"    [skip] ({symbol}, {freq}, h={y_horizon}): "
                  f"{meta['reason']} (n={meta['n_samples']})")
            continue
        items.append({
            "symbol": symbol,
            "freq": freq,
            "y_horizon": y_horizon,
            "vec": vec,
            "ic_series": ic_series,   # 原始日级 IC,供 write_daily_ic 入库(残差 Miner 用)
            **meta,
        })
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description="刷新因子日级 IC 序列向量")
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--cache", default=str(CACHE_DIR))
    ap.add_argument("--xname", help="只跑指定因子")
    ap.add_argument("--force", action="store_true", help="已有也重算")
    args = ap.parse_args()

    cache_dir = Path(args.cache)
    cache_dir.mkdir(parents=True, exist_ok=True)

    with db.get_conn(args.db) as conn:
        if args.xname:
            xnames = [args.xname]
        else:
            xnames = [
                r[0] for r in conn.execute(
                    "SELECT xname FROM factors WHERE status = 'evaluated' "
                    "AND deprecated_at IS NULL ORDER BY xname"
                ).fetchall()
            ]

        print(f"待处理: {len(xnames)} 个因子")
        all_items_by_factor: dict[str, list[dict]] = {}

        for i, xname in enumerate(xnames, 1):
            print(f"\n[{i}/{len(xnames)}] {xname}")
            items = process_factor(conn, xname, cache_dir, args.force)
            if items:
                all_items_by_factor[xname] = items

        if not all_items_by_factor:
            print("\n无新数据写入。")
            return

        # 按因子级 clear + write（避免一次性清空影响其他因子）
        total = 0
        for xname, items in all_items_by_factor.items():
            clear_existing(conn, xname)
            n = write_vectors(conn, xname, items)
            nd = write_daily_ic(conn, xname, items)
            total += n
            print(f"  [daily] {xname}: {nd} 条日级 IC 入 factor_ic_daily")
            print(f"\n[{xname}] 写入 {n} 条 IC 向量：")
            for it in items:
                if it.get("vec") is None:
                    continue
                print(f"  {it['symbol']:14} {it['freq'][:30]:30} "
                      f"h={it['y_horizon']:>3}  n={it['n_samples']:3}  "
                      f"IC={it['mean_ic']:+.4f}  ICIR={it['icir']:+.3f}  "
                      f"{it['start_date']} ~ {it['end_date']}")

        print(f"\n总计写入 {total} 条 IC 向量")


if __name__ == "__main__":
    main()
