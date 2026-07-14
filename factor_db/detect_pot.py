"""通用 POT detector(双尾 + 多指标 + 事件后路径模式)。

对任何指标(原始 level/delta/波动率)做双尾 POT(上尾 95% + 下尾 5%),只提取尾部尖峰
(1% × 2 尾 = 10% 数据,仍降 90%),识别尖峰后收益路径模式:
  pos>=0.55 → post_event_path(延续)  pos<=0.45 → sign_flip(反转)  else → normal
入库 pattern_cards(status=raw,detected_by=pot)。

用法:
  python factor_db/detect_pot.py --files 1            # 测 1 文件(打印,不入库)
  python factor_db/detect_pot.py --store              # 全量 117 + 入库
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = Path("/home/lgao/work/quant/factor-evaluate-tmp/BookSnapshotInfo_raw/BookSnapshotInfo/dailyX")
DB_PATH = ROOT / "factors.db"
Y_HORIZONS = [1, 5, 10, 60, 300]
POT_Q = 0.95
MIN_PEAKS = 30


def parse_field(col):
    return col[2:][col[2:].rfind("@") + 1:]

def parse_y(col):
    return int(col.rsplit("@", 1)[-1])

def read_xy(f):
    with f.open() as fh:
        r = csv.reader(fh)
        header = next(r)
        rows = [row for row in r]
    data = np.array(rows, dtype=np.float64)
    x, y = {}, {}
    for i, h in enumerate(header):
        if h.startswith("X."):
            x[parse_field(h)] = data[:, i]
        elif h.startswith("Y."):
            y[parse_y(h)] = data[:, i]
    return x, y

def compute_indicators(x):
    ind = {}
    for feat, arr in x.items():
        ind[(feat, "level")] = arr
        ind[(feat, "delta")] = np.diff(arr, prepend=arr[0])
    for pfeat in ["bsi_bid_price_0", "bsi_ask_price_0"]:
        if pfeat in x:
            price = x[pfeat]
            w = 60
            wins = [price[max(0, i - w):i + 1] for i in range(len(price))]
            ind[(pfeat, "volatility")] = np.array([a.std() for a in wins])
            ind[(pfeat, "skew")] = np.array([(((a - a.mean()) / a.std()) ** 3).mean() if a.std() > 1e-10 else 0 for a in wins])
            ind[(pfeat, "kurtosis")] = np.array([(((a - a.mean()) / a.std()) ** 4).mean() - 3 if a.std() > 1e-10 else 0 for a in wins])
    return ind

def pot_peaks(series):
    """双尾 POT:上尾(高值)+ 下尾(低值)。返回 [(idx, tail, thr)]。"""
    s = np.nan_to_num(series)
    thr_hi = np.quantile(s, POT_Q)
    thr_lo = np.quantile(s, 1 - POT_Q)
    return [(np.where(s > thr_hi)[0], "upper", thr_hi),
            (np.where(s < thr_lo)[0], "lower", thr_lo)]

def path_mode(y_h, peak_idx):
    if len(peak_idx) < MIN_PEAKS:
        return None, None, None
    post = y_h[peak_idx]
    mean_ret = float(post.mean())
    pos = float((post > 0).mean())
    if pos >= 0.55:
        s = "post_event_path"
    elif pos <= 0.45:
        s = "sign_flip"
    else:
        s = "normal"
    return s, mean_ret, pos

def detect_file(f):
    x, y = read_xy(f)
    indicators = compute_indicators(x)
    cards = []
    date = f.stem.replace("daily-", "")
    for (feat, t), series in indicators.items():
        for idx, tail, thr in pot_peaks(series):
            if len(idx) < MIN_PEAKS:
                continue
            for h in Y_HORIZONS:
                if h not in y:
                    continue
                s, mean_ret, pos = path_mode(y[h], idx)
                if s is None:
                    continue
                cards.append({
                    "f_feature": feat, "t_transform": t,
                    "c_condition": json.dumps({"tail": tail, "pot_q": POT_Q, "thr": round(float(thr), 4)}, ensure_ascii=False),
                    "s_structure": s, "y_target": "raw_return", "h_horizon": h, "r_reference": "self_history",
                    "strength": round(abs(mean_ret), 6), "significance": round(pos, 3),
                    "n_samples": int(len(idx)), "stability": None,
                    "evidence": json.dumps({"mean_ret": round(mean_ret, 6), "pos_ratio": round(pos, 3),
                                            "n_peaks": len(idx), "tail": tail, "date": date}),
                    "detected_by": "pot",
                })
    return cards

def store_cards(cards):
    conn = sqlite3.connect(str(DB_PATH))
    ins = conn.execute
    n = 0
    for c in cards:
        exists = conn.execute(
            "SELECT id FROM pattern_cards WHERE f_feature=? AND t_transform=? AND s_structure=? AND y_target=? AND h_horizon=? AND c_condition=?",
            (c["f_feature"], c["t_transform"], c["s_structure"], c["y_target"], c["h_horizon"], c["c_condition"])
        ).fetchone()
        if exists:
            continue
        ins("""INSERT INTO pattern_cards
               (f_feature,t_transform,c_condition,s_structure,y_target,h_horizon,r_reference,
                strength,significance,n_samples,stability,evidence,status,detected_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'raw', ?)""",
            (c["f_feature"], c["t_transform"], c["c_condition"], c["s_structure"], c["y_target"],
             c["h_horizon"], c["r_reference"], c["strength"], c["significance"], c["n_samples"],
             c["stability"], c["evidence"], c["detected_by"]))
        n += 1
    conn.commit()
    conn.close()
    return n

def main():
    ap = argparse.ArgumentParser(description="通用 POT detector(双尾多指标)")
    ap.add_argument("--files", type=int, default=0, help="前 N 文件(0=全量 117)")
    ap.add_argument("--store", action="store_true", help="入库 pattern_cards(否则只打印)")
    args = ap.parse_args()

    files = sorted(DATA_DIR.glob("daily-*.xy"))
    files = files[:args.files] if args.files > 0 else files

    all_cards = []
    for i, f in enumerate(files, 1):
        cards = detect_file(f)
        all_cards.extend(cards)
        if i % 10 == 0 or i == len(files):
            print(f"[{i}/{len(files)}] {f.name}: 累计 {len(all_cards)} 卡", flush=True)

    # 跨文件合并(同坐标:取 mean strength,合并 evidence)
    by_key = {}
    for c in all_cards:
        k = (c["f_feature"], c["t_transform"], c["s_structure"], c["h_horizon"], c["c_condition"])
        if k not in by_key:
            by_key[k] = c
        else:
            by_key[k]["strength"] = round((by_key[k]["strength"] + c["strength"]) / 2, 6)
            by_key[k]["n_samples"] += c["n_samples"]
    merged = list(by_key.values())

    s_dist = Counter(c["s_structure"] for c in merged)
    print(f"\n合并后 {len(merged)} 模式卡(去重跨文件)。S 分布: {dict(s_dist)}")

    if args.store:
        n = store_cards(merged)
        print(f"入库 {n} 新模式卡(detected_by=pot)")
    else:
        print("\n样本(前 10):")
        for c in merged[:10]:
            ev = json.loads(c["evidence"])
            print(f"  {c['f_feature']:22} {c['t_transform']:10} {c['s_structure']:18} h={c['h_horizon']:>3}s "
                  f"tail={ev.get('tail')} pos={c['significance']} strength={c['strength']:.6f}")

if __name__ == "__main__":
    main()
