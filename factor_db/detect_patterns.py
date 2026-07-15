"""归纳引擎扫描器:detect patterns → raw 模式卡入库。

框架(为后续 detector 扩展):
  每个 detector 是 detect_<structure>(source) -> [pattern_card_dict]。
  pattern_card_dict 含 7 维坐标(F/T/C/S/Y/H/R)+ 统计证据(strength/significance/n_samples/...)+ detected_by。
  store_cards() 统一写 pattern_cards + 运行时扩展 pattern_dims(F 若新则加)+ 幂等(同坐标跳过)。
  update_coverage() 从 pattern_cards 聚合 pattern_coverage(模式空间覆盖地图)。

最简 detector:detect_upper_tail —— 读 data-lens lens_predictive 产出的 ic_matrix.csv,
  挑 |spearman| 在上尾的 (field, horizon),产 upper_tail 模式卡(F=field 特征名, T=level,
  S=upper_tail, Y=raw_return, H=horizon, R=self_history)。

用法:
  python factor_db/detect_patterns.py                       # upper_tail, 默认 ic_matrix
  python factor_db/detect_patterns.py --top-frac 0.15       # 上尾比例
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_db import db

DATA_LENS_OUT = Path("/home/lgao/work/quant/data-lens-mcp/out")


def parse_field(field_col: str) -> tuple[str, str]:
    """X.SHFE-AG@bsi_bid_price_0 → ('SHFE-AG', 'bsi_bid_price_0')"""
    body = field_col[2:]                      # 去 X.
    idx = body.rfind("@")
    symbol = body[:idx].split("@")[0]         # SHFE-AG@1 → SHFE-AG
    feature = body[idx + 1:]                  # bsi_bid_price_0
    return symbol, feature


def detect_upper_tail(ic_csv: Path, top_frac: float = 0.1, min_abs_spearman: float = 0.02) -> list[dict]:
    """读 ic_matrix.csv,挑 |spearman| 上尾的 (field,horizon) 产 upper_tail 模式卡。"""
    with ic_csv.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_abs_sp"] = abs(float(r["spearman"]))
    rows.sort(key=lambda r: r["_abs_sp"], reverse=True)
    n_top = max(1, int(len(rows) * top_frac))
    cards = []
    for r in rows[:n_top]:
        if r["_abs_sp"] < min_abs_spearman:
            continue
        _, feature = parse_field(r["field"])
        cards.append({
            "f_feature": feature,
            "t_transform": "level",
            "c_condition": None,
            "s_structure": "upper_tail",
            "y_target": "raw_return",
            "h_horizon": int(r["y_sec"]),
            "r_reference": "self_history",
            "strength": float(r["spearman"]),
            "significance": float(r["icir"]),
            "n_samples": int(r["n"]),
            "stability": None,
            "evidence": json.dumps({
                "pearson": float(r["pearson"]), "mi": float(r["mi"]),
                "daily_ic_mean": float(r["daily_ic_mean"]), "daily_ic_std": float(r["daily_ic_std"]),
                "n_days": int(r["n_days"]), "field": r["field"],
            }, ensure_ascii=False),
            "detected_by": "predictive_tail",
        })
    return cards


def detect_monotonic(ic_csv: Path, min_swing: float = 0.03) -> list[dict]:
    """同字段跨 horizon |IC| 严格单调(递增/递减)——信号随 horizon 稳定衰减/增强,无反转。"""
    with ic_csv.open() as f:
        rows = list(csv.DictReader(f))
    by_field = {}
    for r in rows:
        by_field.setdefault(parse_field(r["field"])[1], {})[int(r["y_sec"])] = float(r["spearman"])
    cards = []
    for feat, hs_map in by_field.items():
        if len(hs_map) < 3:
            continue
        hs = sorted(hs_map)
        vals = [abs(hs_map[h]) for h in hs]
        swing = max(vals) - min(vals)
        if swing < min_swing:
            continue
        inc = all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
        dec = all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
        if inc or dec:
            cards.append({
                "f_feature": feat, "t_transform": "level", "c_condition": None,
                "s_structure": "monotonic", "y_target": "raw_return",
                "h_horizon": hs[-1] if inc else hs[0], "r_reference": "self_history",
                "strength": max(vals), "significance": None, "n_samples": None, "stability": None,
                "evidence": json.dumps({"horizons": {str(h): hs_map[h] for h in hs}, "dir": "inc" if inc else "dec"}),
                "detected_by": "monotonic",
            })
    return cards


def detect_threshold_break(ic_csv: Path, min_jump: float = 0.03) -> list[dict]:
    """同字段相邻 horizon |IC| 跳变 > min_jump——某 horizon 信号突变(阈值断裂)。"""
    with ic_csv.open() as f:
        rows = list(csv.DictReader(f))
    by_field = {}
    for r in rows:
        by_field.setdefault(parse_field(r["field"])[1], {})[int(r["y_sec"])] = float(r["spearman"])
    cards = []
    for feat, hs_map in by_field.items():
        hs = sorted(hs_map)
        best = (0, None)
        for i in range(1, len(hs)):
            jump = abs(abs(hs_map[hs[i]]) - abs(hs_map[hs[i - 1]]))
            if jump > best[0]:
                best = (jump, i)
        if best[0] >= min_jump:
            i = best[1]
            cards.append({
                "f_feature": feat, "t_transform": "level", "c_condition": None,
                "s_structure": "threshold_break", "y_target": "raw_return",
                "h_horizon": hs[i], "r_reference": "self_history",
                "strength": best[0], "significance": None, "n_samples": None, "stability": None,
                "evidence": json.dumps({"from_h": hs[i - 1], "to_h": hs[i],
                                        "from_ic": hs_map[hs[i - 1]], "to_ic": hs_map[hs[i]], "jump": round(best[0], 4)}),
                "detected_by": "threshold_break",
            })
    return cards


def detect_lower_tail(ic_csv: Path, bot_frac: float = 0.1, max_abs_spearman: float = 0.01) -> list[dict]:
    """|spearman| 下尾(最弱预测字段)——几乎无预测力,但记入覆盖(避雷:这片挖过无信号)。"""
    with ic_csv.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_abs_sp"] = abs(float(r["spearman"]))
    rows.sort(key=lambda r: r["_abs_sp"])
    n_bot = max(1, int(len(rows) * bot_frac))
    cards = []
    for r in rows[:n_bot]:
        if r["_abs_sp"] > max_abs_spearman:
            continue
        _, feat = parse_field(r["field"])
        cards.append({
            "f_feature": feat, "t_transform": "level", "c_condition": None,
            "s_structure": "lower_tail", "y_target": "raw_return",
            "h_horizon": int(r["y_sec"]), "r_reference": "self_history",
            "strength": float(r["spearman"]), "significance": float(r["icir"]),
            "n_samples": int(r["n"]), "stability": None,
            "evidence": json.dumps({"spearman": float(r["spearman"]), "field": r["field"]}),
            "detected_by": "lower_tail",
        })
    return cards


def detect_sign_flip(ic_csv: Path, min_abs_spearman: float = 0.05) -> list[dict]:
    """同族 bid/ask 字段,同 horizon IC 符号相反 → sign_flip(方向不对称耦合,如 lever effect)。
    bsi_bid_size(正) vs bsi_ask_size(负) 这类——upper_tail 把它俩都标上尾,没识别符号耦合。"""
    import re
    with ic_csv.open() as f:
        rows = list(csv.DictReader(f))
    by_key = {}
    for r in rows:
        feat = parse_field(r["field"])[1]
        m = re.search(r"(bid|ask)", feat)
        if not m:
            continue
        side = m.group(1)
        base = feat.replace(side, "", 1).replace("__", "_").strip("_")
        by_key.setdefault((base, int(r["y_sec"])), {})[side] = float(r["spearman"])
    cards = []
    for (base, h), sides in by_key.items():
        if "bid" in sides and "ask" in sides and sides["bid"] * sides["ask"] < 0:
            bid_ic, ask_ic = sides["bid"], sides["ask"]
            if abs(bid_ic) >= min_abs_spearman and abs(ask_ic) >= min_abs_spearman:
                cards.append({
                    "f_feature": base, "t_transform": "level",
                    "c_condition": json.dumps({"pair": "bid_vs_ask"}, ensure_ascii=False),
                    "s_structure": "sign_flip", "y_target": "raw_return", "h_horizon": h, "r_reference": "self_history",
                    "strength": (abs(bid_ic) + abs(ask_ic)) / 2, "significance": None,
                    "n_samples": None, "stability": None,
                    "evidence": json.dumps({"bid_spearman": bid_ic, "ask_spearman": ask_ic}),
                    "detected_by": "sign_flip",
                })
    return cards


def detect_cross_horizon(ic_csv: Path, min_swing: float = 0.03) -> list[dict]:
    """同字段跨 horizon |IC| 非单调(有峰谷)→ cross_horizon_nonmonotonic。
    IC 跨 horizon 应单调衰减,非单调=异常(某 horizon 信号反常强/弱)。"""
    with ic_csv.open() as f:
        rows = list(csv.DictReader(f))
    by_field = {}
    for r in rows:
        by_field.setdefault(parse_field(r["field"])[1], {})[int(r["y_sec"])] = float(r["spearman"])
    cards = []
    for feat, hs_map in by_field.items():
        if len(hs_map) < 3:
            continue
        hs = sorted(hs_map)
        vals = [abs(hs_map[h]) for h in hs]
        nonmonotonic = any(
            (vals[i] > vals[i - 1] and vals[i] > vals[i + 1]) or
            (vals[i] < vals[i - 1] and vals[i] < vals[i + 1])
            for i in range(1, len(vals) - 1)
        )
        swing = max(vals) - min(vals)
        if nonmonotonic and swing >= min_swing:
            peak_h = hs[vals.index(max(vals))]
            cards.append({
                "f_feature": feat, "t_transform": "level", "c_condition": None,
                "s_structure": "cross_horizon_nonmonotonic", "y_target": "raw_return",
                "h_horizon": peak_h, "r_reference": "self_history",
                "strength": max(vals), "significance": None, "n_samples": None, "stability": None,
                "evidence": json.dumps({"horizons": {str(h): hs_map[h] for h in hs}, "swing": round(swing, 4)}),
                "detected_by": "cross_horizon",
            })
    return cards


def store_cards(conn, cards: list[dict]) -> int:
    """写 pattern_cards + 运行时扩展 pattern_dims(F 若新)。幂等:同 (f,t,s,y,h,r) 已存在则跳过。"""
    written = 0
    for c in cards:
        conn.execute(
            "INSERT OR IGNORE INTO pattern_dims (dim, value, description) VALUES ('F', ?, ?)",
            (c["f_feature"], "(运行时扩展,待族化)"),
        )
        exists = conn.execute(
            """SELECT id FROM pattern_cards
               WHERE f_feature=? AND t_transform=? AND s_structure=? AND y_target=?
                 AND h_horizon=? AND r_reference IS ?""",
            (c["f_feature"], c["t_transform"], c["s_structure"], c["y_target"],
             c["h_horizon"], c["r_reference"]),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO pattern_cards
               (f_feature,t_transform,c_condition,s_structure,y_target,h_horizon,r_reference,
                strength,significance,n_samples,stability,evidence,status,detected_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'raw', ?)""",
            (c["f_feature"], c["t_transform"], c["c_condition"], c["s_structure"],
             c["y_target"], c["h_horizon"], c["r_reference"], c["strength"],
             c["significance"], c["n_samples"], c["stability"], c["evidence"],
             c["detected_by"]),
        )
        written += 1
    return written


def update_coverage(conn) -> None:
    """从 pattern_cards 聚合 pattern_coverage(模式空间覆盖地图)。全量重建(模式卡是源头)。"""
    conn.execute("DELETE FROM pattern_coverage")
    conn.execute(
        """INSERT INTO pattern_coverage
           (f_feature,s_structure,y_target,h_horizon,searched_count,archived_count,
            explained_count,avg_strength,last_searched_at)
           SELECT f_feature,s_structure,y_target,h_horizon,
                  COUNT(*), 0, 0, AVG(strength), MAX(detected_at)
           FROM pattern_cards
           GROUP BY f_feature,s_structure,y_target,h_horizon"""
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="归纳引擎扫描器(最简:upper_tail)")
    ap.add_argument("--ic-matrix", default=str(DATA_LENS_OUT / "ic_matrix.csv"))
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--structure", default="upper_tail", choices=["upper_tail"])
    ap.add_argument("--top-frac", type=float, default=0.1, help="上尾比例")
    args = ap.parse_args()

    ic_csv = Path(args.ic_matrix)
    if not ic_csv.exists():
        print(f"ic_matrix 不存在: {ic_csv}(先跑 data-lens lens_predictive 产出)", file=sys.stderr)
        sys.exit(1)

    detectors = [("upper_tail", detect_upper_tail), ("sign_flip", detect_sign_flip), ("cross_horizon", detect_cross_horizon),
                 ("monotonic", detect_monotonic), ("threshold_break", detect_threshold_break), ("lower_tail", detect_lower_tail)]
    all_cards = []
    for name, fn in detectors:
        cards = fn(ic_csv)
        print(f"  detect_{name}: {len(cards)} 候选")
        all_cards.extend(cards)
    with db.get_conn(args.db) as conn:
        n = store_cards(conn, all_cards)
        update_coverage(conn)
        total = conn.execute("SELECT COUNT(*) FROM pattern_cards").fetchone()[0]
        cov = conn.execute("SELECT COUNT(*) FROM pattern_coverage").fetchone()[0]
        s_dist = conn.execute("SELECT s_structure, COUNT(*) FROM pattern_cards GROUP BY s_structure ORDER BY 2 DESC").fetchall()
    print(f"共 {len(all_cards)} 候选 → 入库 {n} 新 | pattern_cards 总 {total} | pattern_coverage 格 {cov}")
    print("  S 结构分布(横向饱满度):", [(r[0], r[1]) for r in s_dist])


if __name__ == "__main__":
    main()
