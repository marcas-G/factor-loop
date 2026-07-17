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


def _extract_chinese(formula_text: str) -> str:
    """从 formula 提取中文注释行(// 或 # 后的中文),作 intuition 缺失时的语义降级。
    纯英文代码/符号丢弃——那是形式不是语义。"""
    if not formula_text:
        return ""
    out = []
    for line in formula_text.splitlines():
        comment = line
        for marker in ("//", "#"):
            if marker in comment:
                comment = comment.split(marker, 1)[1]
                break
        cn = "".join(ch for ch in comment if "一" <= ch <= "鿿" or ch in "，。、：；（）")
        cn = cn.strip()
        if len(cn) >= 4:  # 至少 4 个汉字才算语义,过滤变量名拼音碎片
            out.append(cn)
    return " ".join(out)


def build_text(row, angle_map: dict) -> str:
    """构造 emb 输入:纯语义。

    主体 = intuition(语义意图描述);缺失则降级 formula 中文注释。
    后缀 = angle 信息源(结构化维度,让同信息源因子适度聚合)。
    formula 代码 / tags / class_name 不进 embedding——形式相似 ≠ 语义相似。
    """
    sem = (row["intuition"] or "").strip() or _extract_chinese(row["formula_text"])
    parts = []
    if sem:
        parts.append(sem)
    ac = row["angle_code"]
    if ac and ac in angle_map:
        a = angle_map[ac]
        desc = " ".join(x for x in (a["name"], a["signal_target"]) if x)
        if desc:
            parts.append(f"信息源:{desc}")
    return "\n".join(parts).strip()


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
            SELECT f.xname, f.class_name, f.formula_text, f.intuition, f.angle_code
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
        angle_map = {r["code"]: {"name": r["name"], "signal_target": r["signal_target"] or ""}
                     for r in conn.execute("SELECT code, name, signal_target FROM angle_ontology")}
        print(f"[INFO] 待 embed: {len(rows)} 个因子，model={args.model}，angle 本体 {len(angle_map)} 个")

        ok = 0
        for i, r in enumerate(rows, 1):
            xname = r["xname"]
            text = build_text(r, angle_map)
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
