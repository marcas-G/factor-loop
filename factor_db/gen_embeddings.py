"""阶段 C：为每个因子生成 384 维语义 embedding，写入 factors_vec。

- 模型：BAAI/bge-small-zh-v1.5（CPU 推理，单条 10-30ms）
- 输入：纯语义文本 = intuition(主体) / 缺失降级 formula 中文注释 + angle 信息源后缀
  formula 代码 / tags / class_name 不进 embedding(形式噪声,扭曲语义空间)
- 归一化后写入（cosine = 内积）
- 幂等：emb_generated_at 非空则跳过；--force 强制重算

用法:
    python factor_db/gen_embeddings.py
    python factor_db/gen_embeddings.py --force
    python factor_db/gen_embeddings.py --xname Foo_w21

依赖:
    pip install sentence-transformers
    首次运行会下载 bge-small-zh-v1.5 模型（~100MB）
"""

from __future__ import annotations

import os

# 避免 sentence-transformers 启动时去 huggingface hub 检查模型版本导致 hang/网络错误
# 模型已缓存在 ~/.cache/huggingface/hub/，离线模式足够（与 embed_query.py 一致）
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_db import db

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


def get_embedder(model_name: str):
    """延迟加载模型（避免 --help 时拉依赖）。"""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit(
            "[ERROR] 缺少 sentence-transformers。\n"
            "  pip install sentence-transformers\n"
            "  首次运行会自动下载模型 (~100MB)"
        )
    return SentenceTransformer(model_name, device="cpu")


def build_text(row) -> str:
    """锚定文本 = factors.anchor_text(固定四要素模板生成,统一风格,检索稳定)。
    由 ai_generate_anchor.py 按固定 prompt 生成(机制/利润来源/信息源/预测),
    所有因子风格一致——这是 embedding 检索稳定的根基。"""
    return (row["anchor_text"] or "").strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="阶段 C：批量生成 embedding")
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--xname", help="只跑指定 xname")
    ap.add_argument("--force", action="store_true", help="已有 emb 也重算")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    embedder = get_embedder(args.model)

    with db.get_conn(args.db) as conn:
        # 取 factors + 串接 tag（聚合到一行）
        sql = """
            SELECT f.xname, f.anchor_text
            FROM factors f
        """
        where = []
        params: list = []
        if args.xname:
            where.append("f.xname = ?")
            params.append(args.xname)
        if not args.force:
            where.append("f.emb_generated_at IS NULL")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY f.xname ORDER BY f.xname"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"

        rows = conn.execute(sql, params).fetchall()
        print(f"[INFO] 待 embed: {len(rows)} 个因子，model={args.model}")

        ok = 0
        for i, r in enumerate(rows, 1):
            xname = r["xname"]
            text = build_text(r)
            try:
                emb = embedder.encode(text, normalize_embeddings=True).tolist()
            except Exception as e:
                print(f"[{i}/{len(rows)}] {xname}: ERROR {e}")
                continue
            db.update_embedding(conn, xname, emb)
            ok += 1
            if i % 10 == 0 or i == len(rows):
                print(f"[{i}/{len(rows)}] {xname}: OK ({len(emb)}d)")

        print(f"\n[RESULT] embedded={ok}/{len(rows)}")


if __name__ == "__main__":
    main()
