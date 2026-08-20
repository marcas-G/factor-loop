#!/usr/bin/env python3
"""csv_ic 适配器：解析平台 csv_ic_ts/xcorr 产物，桥接到 ic_correlate/residual。

补 assess 正交检查的 gap:
- parse_xcorr_md: 解析 csv_ic_xcorr.md(因子间相关性矩阵), 提取因子对 + |r| + 冗余标记(>0.7)
- ingest_daily_ts: 把 csv_ic_ts.csv(逐日 IC) 写入 factor_ic_daily 表, 供 ic_correlate/residual 查

⚠️ 格式基于平台公告假设(2026-07-29), 未实测——待平台产物验证列名/结构。
   parse_xcorr_md 支持 markdown 表格格式(最可能); ingest_daily_ts 尝试常见列名。

用法:
    python3 csv_ic_adapter.py parse_xcorr <xcorr_md_file>
    python3 csv_ic_adapter.py ingest_daily_ts <daily_ts_csv> <factor_xname> [--symbol SHFE-AG] [--horizon 1]
    python3 csv_ic_adapter.py parse_xcorr_from_evidence <xcorr_md_text>  # 从 evidence JSON 直接传文本
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_xcorr_md(text):
    """解析 csv_ic_xcorr.md 的因子间相关性矩阵。

    支持格式（markdown 表格，最可能）:
        | | FactorA | FactorB |
        |---|---|---|
        | FactorA | - | **0.85** |
        | FactorB | **0.85** | - |

    也支持逐行格式:
        FactorA vs FactorB: **0.85**
        FactorA vs FactorC: 0.32

    返回 [{factor_a, factor_b, r, is_redundant}], 去重(factor_a/factor_b 不分顺序)。
    """
    pairs = {}
    lines = text.strip().split('\n')

    # 尝试 markdown 表格格式
    headers = []
    for line in lines:
        line = line.strip()
        if not line or not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|')]
        # 去首尾空 cell(首尾 | 产生), 保留中间(行标签空 cell + 对角线 '-')
        # 不用 cells != '' 去空——会破坏表头行标签与数据列的对齐
        if cells and cells[0] == '':
            cells = cells[1:]
        if cells and cells[-1] == '':
            cells = cells[:-1]

        if '---' in line:
            continue  # 分隔行

        if not headers and len(cells) > 1:
            # 第一行数据: 表头(第一个是行标签, 后面是因子名)
            headers = cells[1:]
            continue

        if headers and len(cells) > 1:
            factor_a = cells[0]
            for i, cell in enumerate(cells[1:]):
                if i >= len(headers):
                    break
                factor_b = headers[i]
                if factor_a == factor_b:
                    continue  # 对角线
                # 解析 |r|, 识别加粗(** ** 表示 >0.7)
                is_bold = '**' in cell
                r_str = cell.replace('**', '').replace('*', '').replace('`', '').strip()
                # 跳过分隔符/空值
                if r_str in ('-', '', '—', 'N/A'):
                    continue
                try:
                    r = float(r_str)
                except ValueError:
                    continue
                key = tuple(sorted([factor_a, factor_b]))
                if key not in pairs:
                    pairs[key] = {
                        'factor_a': key[0],
                        'factor_b': key[1],
                        'r': r,
                        'is_redundant': is_bold or abs(r) >= 0.7,
                    }

    # 如果表格没解析到, 尝试逐行格式
    if not pairs:
        pattern = re.compile(r'(\S+)\s*vs\s*(\S+)\s*:?\s*\**(-?[\d.]+)\**')
        for line in lines:
            m = pattern.search(line)
            if m:
                fa, fb, r_str = m.group(1), m.group(2), m.group(3)
                is_bold = '**' in line
                try:
                    r = float(r_str)
                except ValueError:
                    continue
                key = tuple(sorted([fa, fb]))
                if key not in pairs and fa != fb:
                    pairs[key] = {
                        'factor_a': key[0], 'factor_b': key[1],
                        'r': r, 'is_redundant': is_bold or abs(r) >= 0.7,
                    }

    return list(pairs.values())


def find_redundant(parsed, target_factor, threshold=0.6):
    """从解析结果找 target_factor 的冗余对（|r| >= threshold）。"""
    redundant = []
    for p in parsed:
        if target_factor in (p['factor_a'], p['factor_b']):
            if abs(p['r']) >= threshold:
                other = p['factor_b'] if p['factor_a'] == target_factor else p['factor_a']
                redundant.append({'vs': other, 'r': p['r']})
    redundant.sort(key=lambda x: -abs(x['r']))
    return redundant


def ingest_daily_ts(csv_path, factor_xname, symbol='SHFE-AG', freq='default', y_horizon=None):
    """把 csv_ic_ts.csv(逐日 IC) 写入 factor_ic_daily 表。

    实际格式(2026-07-30 验证): date, factor, x_col, horizon, y_col, rank_ic, pearson_day
    - horizon 列: 多 horizon(1/5/10/60/300), 每 date×horizon 一行
    - x_col 含 symbol(X.SHFE-AG@...), 自动提取; 或用 symbol 参数兜底

    返回 {ok, written}。
    """
    import csv
    import re
    from core.db import db

    with open(csv_path, 'r', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        date_col = next((c for c in ['date', 'Date', 'trade_date'] if c in cols), None)
        ic_col = next((c for c in ['rank_ic', 'ic', 'ic_mean', 'rank_ic_mean'] if c in cols), None)
        horizon_col = next((c for c in ['horizon', 'Horizon', 'h'] if c in cols), None)
        xcol_col = next((c for c in ['x_col', 'factor', 'X'] if c in cols), None)
        if not date_col or not ic_col:
            return {'ok': False, 'error': f'列名不匹配: date={date_col}, ic={ic_col}, 实际={cols}'}
        rows = list(reader)

    written = 0
    with db.get_conn() as conn:
        conn.execute("DELETE FROM factor_ic_daily WHERE factor_xname = ?", (factor_xname,))
        for row in rows:
            date = str(row[date_col])
            ic_str = (row.get(ic_col) or '').strip()
            if not ic_str or ic_str.lower() == 'nan':
                continue
            try:
                ic = float(ic_str)
            except ValueError:
                continue
            h_str = (row.get(horizon_col) or '').strip() if horizon_col else ''
            try:
                h = int(h_str) if h_str else (y_horizon or 1)
            except ValueError:
                h = y_horizon or 1
            sym = symbol
            freq_contract = freq
            xcol_val = (row.get(xcol_col) or '') if xcol_col else ''
            if xcol_val:
                m = re.search(r'X\.(SHFE-\w+?)[@\.]', xcol_val)
                if m:
                    sym = m.group(1)
                # 合约分流: x_col 含 @N@(如 X.SHFE-AG@1@sqy0_xxx) 是次主力, 否则主力。
                # 主力/次主力共用 symbol, 靠 freq 区分, 避免 INSERT OR REPLACE 同 date 互覆盖。
                freq_contract = freq + (':sub' if re.search(r'@\d+@', xcol_val) else ':main')
            conn.execute(
                "INSERT OR REPLACE INTO factor_ic_daily "
                "(factor_xname, symbol, freq, y_horizon, date, ic) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (factor_xname, sym, freq_contract, h, date, ic)
            )
            written += 1

    return {'ok': True, 'written': written}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='csv_ic 适配器')
    sub = ap.add_subparsers(dest='cmd')

    p1 = sub.add_parser('parse_xcorr', help='解析 csv_ic_xcorr.md')
    p1.add_argument('file', help='xcorr.md 文件路径')

    p2 = sub.add_parser('parse_xcorr_from_evidence', help='从 evidence 文本解析')
    p2.add_argument('text', help='xcorr_md 文本')

    p3 = sub.add_parser('ingest_daily_ts', help='逐日 IC 写入 factor_ic_daily')
    p3.add_argument('csv', help='csv_ic_ts.csv 路径')
    p3.add_argument('xname', help='因子 xname')
    p3.add_argument('--symbol', default='SHFE-AG')
    p3.add_argument('--horizon', type=int, default=1)

    p4 = sub.add_parser('find_redundant', help='找 target 因子的冗余对')
    p4.add_argument('file', help='xcorr.md 文件路径')
    p4.add_argument('target', help='目标因子名')
    p4.add_argument('--threshold', type=float, default=0.6)

    args = ap.parse_args()

    if args.cmd == 'parse_xcorr':
        text = Path(args.file).read_text(encoding='utf-8')
        result = parse_xcorr_md(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == 'parse_xcorr_from_evidence':
        result = parse_xcorr_md(args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == 'ingest_daily_ts':
        result = ingest_daily_ts(args.csv, args.xname, args.symbol, y_horizon=args.horizon)
        print(json.dumps(result, ensure_ascii=False))

    elif args.cmd == 'find_redundant':
        text = Path(args.file).read_text(encoding='utf-8')
        parsed = parse_xcorr_md(text)
        redundant = find_redundant(parsed, args.target, args.threshold)
        print(json.dumps(redundant, ensure_ascii=False, indent=2))
        if redundant:
            print(f"\n⚠️ {args.target} 有 {len(redundant)} 个冗余对 (|r|≥{args.threshold})", file=sys.stderr)

    else:
        ap.print_help()
