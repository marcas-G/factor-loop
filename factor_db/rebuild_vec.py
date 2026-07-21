"""高效重建 factors_vec:batch encode + 一次性 DELETE ALL + 批量 INSERT。
替代 gen_embeddings --force 的逐条 DELETE+INSERT(vec0 事务累积慢)。

用法: python factor_db/rebuild_vec.py
"""
import sys
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from factor_db.gen_embeddings import get_embedder, build_text
from factor_db.db import get_conn

model = get_embedder("BAAI/bge-small-zh-v1.5")

with get_conn("factors.db") as c:
    rows = c.execute("SELECT xname, anchor_text FROM factors").fetchall()
    texts = [build_text(r) for r in rows]
    print(f"[INFO] {len(rows)} 个因子,batch encode...", flush=True)

    embs = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)

    # 一次性清空 + 批量 INSERT(避免逐条 vec0 DELETE 开销)
    c.execute("DELETE FROM factors_vec")
    for r, emb in zip(rows, embs):
        blob = struct.pack(f"{len(emb)}f", *emb)
        c.execute("INSERT INTO factors_vec (xname, embedding) VALUES (?, ?)", (r["xname"], blob))
        c.execute("UPDATE factors SET emb_generated_at = CURRENT_TIMESTAMP WHERE xname = ?", (r["xname"],))
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM factors_vec").fetchone()[0]
    print(f"[RESULT] rebuilt factors_vec: {n} (纯语义向量)", flush=True)
