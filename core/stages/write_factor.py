#!/usr/bin/env python3
"""write-factor 纯函数(吸收 runtime/stages/write-factor.mjs)。

新 pipeline 里 .h 生成由 write-factor skill(Claude)做,这里只提供 submit 阶段需要的辅助函数。
"""
from __future__ import annotations

import re
from pathlib import Path


def extract_class_name_from_h(h_file: str | Path) -> str | None:
    """从 .h 提取 class 名(正则 \bclass\s+([A-Z][A-Za-z0-9_]*)\s*[:{])。"""
    p = Path(h_file)
    if not p.exists():
        return None
    m = re.search(r"\bclass\s+([A-Z][A-Za-z0-9_]*)\s*[:{]", p.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def is_template_class(h_file: str | Path) -> bool:
    """检测是否 template 类。文件不存在 → True(保守,按 template 处理)。"""
    p = Path(h_file)
    if not p.exists():
        return True
    return bool(re.search(r"\btemplate\s*<", p.read_text(encoding="utf-8", errors="replace")))
