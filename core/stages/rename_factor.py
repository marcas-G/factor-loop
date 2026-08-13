#!/usr/bin/env python3
"""因子 .h 换名工具(吸收 runtime/stages/rename-factor.mjs)。

DAG 缓存陷阱自愈:同 xname 重提交命中缓存 → 换 xname 强制重跑。
PascalCase↔snake_case + 唯一新名 + 复制 .h 改名(class/xname frontmatter/names stem)。
"""
from __future__ import annotations

import re
from pathlib import Path

from core.stages.write_factor import extract_class_name_from_h


def to_snake(s: str) -> str:
    """PascalCase → snake_case。含缩写词处理:
    BPDiff → bp_diff(缩写 BP + Diff,规则1 拆边界)
    BHHI → bhhi(全大写缩写不拆,无 [A-Z][a-z] 锚点)
    TradeRunVolAccel2 → trade_run_vol_accel2
    """
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)  # 缩写词边界: BPDiff→BP_Diff
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)      # 常规: eR→e_R
    return s.lower()


def next_unique_xname(old_xname: str, factors_dir: str | Path, exists_in_db=None) -> str:
    """生成唯一新 xname:剥离数字尾缀后递增(OldName→OldName2→OldName3...)。"""
    base = re.sub(r"\d+$", "", old_xname) or old_xname
    n = 2
    factors_dir = Path(factors_dir)
    while n < 1000:
        candidate = f"{base}{n}"
        file_exists = (factors_dir / f"{candidate}.h").exists() if factors_dir else False
        db_exists = bool(exists_in_db(candidate)) if exists_in_db else False
        if not file_exists and not db_exists:
            return candidate
        n += 1
    raise RuntimeError(f"next_unique_xname: {base}{n}+ 全被占用,换名失败")


def rename_factor_h(old_xname: str, old_file: str | Path, factors_dir: str | Path, exists_in_db=None) -> dict:
    """复制 .h 并改名:class 名 + xname/class_name frontmatter(PascalCase)+ names() stem(snake_case)。
    返回 {newXname, newFile}。"""
    old_file = Path(old_file)
    factors_dir = Path(factors_dir)
    if not old_file.exists():
        raise RuntimeError(f"renameFactorH: 源 .h 不存在: {old_file}")

    new_xname = next_unique_xname(old_xname, factors_dir, exists_in_db)
    old_snake = to_snake(old_xname)
    new_snake = to_snake(new_xname)
    content = old_file.read_text(encoding="utf-8")

    # 先 snake(names stem + 任意 snake 出现),再 Pascal(class/frontmatter)。字符集不重叠(_ vs 大写)。
    if old_snake and old_snake != new_snake:
        content = content.replace(old_snake, new_snake)
    if old_xname != new_xname:
        content = content.replace(old_xname, new_xname)

    new_file = factors_dir / f"{new_xname}.h"
    new_file.write_text(content, encoding="utf-8")

    new_class = extract_class_name_from_h(new_file)
    if new_class != new_xname:
        raise RuntimeError(
            f"renameFactorH: 改名后 class={new_class!r} 期望={new_xname!r}(旧 token 残留或 .h 结构非标准)"
        )
    return {"newXname": new_xname, "newFile": str(new_file)}
