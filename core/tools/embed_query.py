"""为任意文本算归一化 embedding，输出 JSON。

用法：
    python3 core/tools/embed_query.py --text "查询文本"

输出（stdout 末尾一行 JSON）：
    {"embedding": [...], "dim": 512}

供 MCP factor_semantic_search 工具调用。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 避免 sentence-transformers 启动时去 huggingface hub 检查模型版本导致 hang
# 模型已缓存在 ~/.cache/huggingface/hub/，离线模式足够
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools.gen_embeddings import get_embedder, DEFAULT_MODEL


def main() -> None:
    ap = argparse.ArgumentParser(description="为 query 文本算归一化 embedding")
    ap.add_argument("--text", required=True, help="查询文本（idea / formula / 任意自然语言）")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    embedder = get_embedder(args.model)
    emb = embedder.encode(args.text, normalize_embeddings=True).tolist()
    print(json.dumps({"embedding": emb, "dim": len(emb)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
