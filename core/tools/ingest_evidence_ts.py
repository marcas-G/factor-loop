#!/usr/bin/env python3
"""从 evidence_file(P6 外存 JSON)或 check_output 导 daily_ts → factor_ic_daily。

assess 步骤4 用。解决卡点③:P6 外存后 daily_ts 在 evidence_file(JSON),
但 csv_ic_adapter.ingest_daily_ts 只吃 CSV 文件路径。

用法:
    python core/tools/ingest_evidence_ts.py --evidence-file <path> --xname <xname>
    python core/tools/ingest_evidence_ts.py --csv <csv_ic_ts.csv> --xname <xname>
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.tools.csv_ic_adapter import ingest_daily_ts


def ingest_from_evidence_file(evidence_file: str, xname: str) -> dict:
    """从 evidence_file JSON 读 daily_ts → 转 CSV in-memory → ingest。"""
    data = json.loads(Path(evidence_file).read_text(encoding="utf-8"))
    daily_ts = data.get("daily_ts")
    if not daily_ts:
        return {"ok": False, "error": "evidence_file 无 daily_ts 字段"}
    # list of dict → CSV in-memory
    buf = io.StringIO()
    if isinstance(daily_ts, list) and daily_ts:
        writer = csv.DictWriter(buf, fieldnames=daily_ts[0].keys())
        writer.writeheader()
        writer.writerows(daily_ts)
    elif isinstance(daily_ts, str):
        buf.write(daily_ts)
    else:
        return {"ok": False, "error": f"daily_ts 格式不支持: {type(daily_ts)}"}
    # 写临时 CSV 再 ingest
    tmp_csv = Path("/tmp") / f"{xname}_daily_ts_export.csv"
    tmp_csv.write_text(buf.getvalue(), encoding="utf-8")
    return ingest_daily_ts(str(tmp_csv), xname)


def main():
    ap = argparse.ArgumentParser(description="从 evidence_file 或 CSV 导 daily_ts → factor_ic_daily")
    ap.add_argument("--evidence-file", help="P6 外存的 evidence JSON 路径(含 daily_ts)")
    ap.add_argument("--csv", help="csv_ic_ts.csv 路径(check_output 目录)")
    ap.add_argument("--xname", required=True, help="因子 xname")
    args = ap.parse_args()

    if args.evidence_file:
        r = ingest_from_evidence_file(args.evidence_file, args.xname)
    elif args.csv:
        r = ingest_daily_ts(args.csv, args.xname)
    else:
        ap.error("需 --evidence-file 或 --csv")

    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
