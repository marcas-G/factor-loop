"""初始化因子库：建 9 张表 + 3 个虚拟表 + triggers。幂等。

用法:
    python factor_db/init_db.py                 # 默认 ../factors.db
    python factor_db/init_db.py --db /tmp/t.db

依赖:
    pip install sqlite-vec    # 加载 vec0 虚拟表
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB = Path(__file__).resolve().parent.parent / "factors.db"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import migrations  # noqa: E402  同目录;init 后调 migrate 记录版本链
import seed_axioms  # noqa: E402  新库建后预填 23 条 axiom


def load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """加载 sqlite-vec 扩展。失败时给出明确错误。"""
    try:
        import sqlite_vec
    except ImportError as e:
        sys.exit(
            f"[ERROR] 缺少 sqlite-vec。\n"
            f"  pip install sqlite-vec\n"
            f"  原始错误: {e}"
        )
    sqlite_vec.load(conn)


def init_db(db_path: Path = DEFAULT_DB) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row  # db.py 函数按名取列,需 Row factory(对齐 get_conn 契约)
    try:
        load_sqlite_vec(conn)
        conn.executescript(schema_sql)
        # 新库已由 schema.sql 直建到最新结构;migrate 幂等记录版本链(结构补齐为 noop)。
        migrations.migrate(conn)
        conn.commit()
    finally:
        conn.close()

    seed_axioms.seed(db_path)  # 新库建后预填 axiom(23 条理论公理,可复现)
    print(f"[OK] 初始化完成: {db_path}")
    print(f"     schema: {SCHEMA_PATH}")
    print(f"     schema_version: {migrations.CURRENT_VERSION}")


def main() -> None:
    ap = argparse.ArgumentParser(description="初始化因子库 SQLite schema")
    ap.add_argument("--db", default=str(DEFAULT_DB), help=f"DB 路径，默认 {DEFAULT_DB}")
    args = ap.parse_args()
    init_db(Path(args.db))


if __name__ == "__main__":
    main()
