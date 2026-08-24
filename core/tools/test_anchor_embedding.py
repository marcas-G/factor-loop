"""anchor_text/embedding 链路测试。

- build_text 直接用 anchor_text(不再 intuition/降级)
- update_embedding DELETE+INSERT 幂等(vec0 不支持 INSERT OR REPLACE)

用法: /home/lgao/quant-venv/bin/python core/tools/test_anchor_embedding.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.db import db  # noqa: E402
from core.tools.gen_embeddings import build_text  # noqa: E402
from core.db import init_db  # noqa: E402


def test_build_text_uses_anchor_text():
    """build_text 直接返回 anchor_text,不依赖其他因子字段。"""
    assert build_text({"anchor_text": "机制:X\n利润来源:Y"}) == "机制:X\n利润来源:Y"
    assert build_text({"anchor_text": None}) == ""
    assert build_text({"anchor_text": ""}) == ""
    # 旧字段存在也不读(只用 anchor_text)
    row = {"anchor_text": "A", "intuition": "B", "formula_text": "C"}
    assert build_text(row) == "A"


def test_build_text_strips_whitespace():
    assert build_text({"anchor_text": "  X\n"}) == "X"


def test_update_embedding_idempotent():
    """vec0 不支持 INSERT OR REPLACE;update_embedding 用 DELETE+INSERT,重复写不报 UNIQUE。"""
    tmp = tempfile.mktemp(suffix=".db")
    init_db.init_db(Path(tmp))
    try:
        with db.get_conn(tmp) as c:
            c.execute("INSERT INTO factors (xname, status) VALUES (?, 'draft')", ["TestEmb"])
            db.update_embedding(c, "TestEmb", [0.1] * 512)   # INSERT
            db.update_embedding(c, "TestEmb", [0.2] * 512)   # DELETE+INSERT,不报 UNIQUE
            row = c.execute("SELECT xname FROM factors_vec WHERE xname=?", ["TestEmb"]).fetchone()
            assert row is not None, "factors_vec 未写入"
            c.commit()
    finally:
        Path(tmp).unlink(missing_ok=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print(f"✓ {t.__name__}")
    print(f"\n全部 {len(tests)} 项 anchor_text/embedding 测试通过。")


if __name__ == "__main__":
    main()
