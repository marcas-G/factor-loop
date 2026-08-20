#!/usr/bin/env python3
"""从 factor_ic_daily 表刷新 factor_ic_vec（绕过 dailyX 下载）。

ingest_daily_ts（csv_ic_adapter）已把 csv_ic_ts 写入 factor_ic_daily。
本脚本从 factor_ic_daily 读 → z-score + L2 归一化 → 写 factor_ic_vec + factor_ic_vec_meta。

替代 refresh_factor_ic_vectors.py 的 download_factor（default_test 无 dailyX）。
用 numpy（不依赖 pandas）。
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from datetime import datetime, timezone
from core.db import db

MIN_SAMPLES = 30
WINDOW_SIZE = 250


def refresh_from_daily(xname):
    """从 factor_ic_daily 读 IC → 归一化 → 写 factor_ic_vec。返回 {ok, written, scenes}。"""
    with db.get_conn() as conn:
        scenes = conn.execute(
            "SELECT DISTINCT symbol, freq, y_horizon FROM factor_ic_daily WHERE factor_xname=?",
            (xname,)
        ).fetchall()

        if not scenes:
            return {'ok': False, 'error': f'{xname} 在 factor_ic_daily 无数据（先 ingest_daily_ts）'}

        # 清旧 vec
        conn.execute("DELETE FROM factor_ic_vec WHERE factor_xname=?", (xname,))
        conn.execute("DELETE FROM factor_ic_vec_meta WHERE factor_xname=?", (xname,))

        written = 0
        now = datetime.now(timezone.utc).isoformat(timespec='milliseconds') + 'Z'

        for symbol, freq, y_horizon in scenes:
            rows = conn.execute(
                "SELECT date, ic FROM factor_ic_daily WHERE factor_xname=? AND symbol=? AND y_horizon=? ORDER BY date",
                (xname, symbol, y_horizon)
            ).fetchall()

            if len(rows) < MIN_SAMPLES:
                continue

            values = np.array([r[1] for r in rows], dtype=np.float64)
            n = len(values)
            mean, std = float(values.mean()), float(values.std())
            if std < 1e-10:
                continue

            z = (values - mean) / std

            # pad/truncate to WINDOW_SIZE
            if n < WINDOW_SIZE:
                pad = np.zeros(WINDOW_SIZE - n, dtype=np.float32)
                vec = np.concatenate([pad, z.astype(np.float32)])
            else:
                vec = z[-WINDOW_SIZE:].astype(np.float32)

            # L2 归一化
            norm = float(np.linalg.norm(vec))
            if norm > 1e-10:
                vec = vec / norm

            blob = vec.tobytes()
            conn.execute(
                "INSERT INTO factor_ic_vec (factor_xname, symbol, freq, y_horizon, embedding) VALUES (?,?,?,?,?)",
                (xname, symbol, freq, y_horizon, blob)
            )
            icir = mean / std if std > 1e-10 else 0.0
            conn.execute(
                "INSERT OR REPLACE INTO factor_ic_vec_meta "
                "(factor_xname, symbol, freq, y_horizon, n_samples, start_date, end_date, mean_ic, std_ic, icir, computed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (xname, symbol, freq, y_horizon, n, rows[0][0], rows[-1][0], mean, std, icir, now)
            )
            written += 1

        return {'ok': True, 'written': written, 'scenes': len(scenes)}


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='从 factor_ic_daily 刷新 factor_ic_vec（绕过 dailyX）')
    ap.add_argument('xname', help='因子 xname')
    args = ap.parse_args()
    result = refresh_from_daily(args.xname)
    print(result)
    if result.get('ok'):
        print(f"✓ {args.xname}: {result['written']}/{result['scenes']} 场景写入 factor_ic_vec", file=sys.stderr)
