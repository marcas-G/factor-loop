"""阶段 A：扫描 factors/*.h 并导入 SQLite。

- 有 frontmatter 的因子：解析后用完整字段入库
- 无 frontmatter 的老因子：提取 class_name + template 默认参数 → 入库
  formula_text=NULL, status=draft（待阶段 B AI 回填）

幂等：xname 已存在则跳过。

用法:
    python factor_db/import_factors.py
    python factor_db/import_factors.py --factors-dir ../factors --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

# 支持直接运行（无包）和模块运行两种方式
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_db import db
from factor_db.parse_frontmatter import (
    extract_class_name,
    extract_template_default_param,
    has_frontmatter,
    make_xname,
    parse_frontmatter,
)

DEFAULT_FACTORS_DIR = ROOT / "factors"


def import_one(conn, file_path: Path, dry_run: bool = False) -> dict:
    """导入单个 .h。返回统计 dict。"""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    rel_path = file_path.name
    today = dt.date.today().isoformat()

    info: dict = {
        "file": rel_path,
        "had_frontmatter": False,
        "xname": None,
        "action": None,  # inserted / skipped / error
        "error": None,
    }

    fm = parse_frontmatter(text)
    if fm:
        info["had_frontmatter"] = True
        xname = fm.get("xname")
        class_name = fm.get("class_name") or extract_class_name(text)
        formula = fm.get("formula")
        if isinstance(formula, str):
            formula = formula.strip()
        params = fm.get("params") if isinstance(fm.get("params"), dict) else None
        tags = fm.get("tags") or []
        if not isinstance(tags, list):
            tags = [tags]
        status = fm.get("status") or "draft"
        created_ts = fm.get("created_ts") or today

        if not xname:
            xname = make_xname(class_name or rel_path.stem, params)
        info["xname"] = xname
        info["action"] = "skipped" if dry_run else "inserted"

        if not dry_run:
            inserted = db.add_factor(
                conn,
                xname=xname,
                class_name=class_name,
                file_path=rel_path,
                formula_text=formula,
                params=params,
                status=status,
                created_ts=created_ts,
                tags=tags,
            )
            info["action"] = "inserted" if inserted else "skipped"
            if inserted and tags:
                db.update_factor_formula(
                    conn, xname=xname, formula_text=formula or "", tags=tags
                )
    else:
        # 老因子：无 frontmatter
        class_name = extract_class_name(text)
        if not class_name:
            info["action"] = "error"
            info["error"] = "无法提取 class_name"
            return info
        params = extract_template_default_param(text)
        xname = make_xname(class_name, params)
        info["xname"] = xname
        info["action"] = "skipped" if dry_run else "inserted"

        if not dry_run:
            inserted = db.add_factor(
                conn,
                xname=xname,
                class_name=class_name,
                file_path=rel_path,
                formula_text=None,
                params=params,
                status="draft",
                created_ts=today,
            )
            info["action"] = "inserted" if inserted else "skipped"

    return info


def main() -> None:
    ap = argparse.ArgumentParser(description="阶段 A：扫描 .h 导入因子库")
    ap.add_argument("--factors-dir", default=str(DEFAULT_FACTORS_DIR))
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = ap.parse_args()

    factors_dir = Path(args.factors_dir)
    if not factors_dir.is_dir():
        sys.exit(f"[ERROR] factors 目录不存在: {factors_dir}")

    files = sorted(factors_dir.glob("*.h"))
    print(f"[INFO] 扫描到 {len(files)} 个 .h 文件")

    results = []
    if args.dry_run:
        for f in files:
            results.append(import_one(None, f, dry_run=True))
    else:
        with db.get_conn(args.db) as conn:
            for f in files:
                results.append(import_one(conn, f, dry_run=False))

    # 统计
    inserted = sum(1 for r in results if r["action"] == "inserted")
    skipped = sum(1 for r in results if r["action"] == "skipped")
    errors = [r for r in results if r["action"] == "error"]
    no_fm = sum(1 for r in results if not r["had_frontmatter"])

    print(f"\n[RESULT] inserted={inserted} skipped={skipped} errors={len(errors)}")
    print(f"[RESULT] 无 frontmatter（待 AI 回填）: {no_fm}")
    if errors:
        print("[ERRORS]")
        for r in errors:
            print(f"  {r['file']}: {r['error']}")


if __name__ == "__main__":
    main()
