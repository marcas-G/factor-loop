"""YAML-in-// frontmatter 解析与序列化。

格式（D19）:
    // ---
    // xname: Foo_w21
    // class_name: Foo
    // formula: |
    //   alpha = ...
    // tags: [a, b]
    // ---
    #pragma once
    ...

规则:
- frontmatter 必须出现在文件开头（前若干行，允许前面有 license 空行）
- `// ---` 是边界标志，第一个 `// ---` 到下一个 `// ---` 之间为 YAML 内容
- 每行去掉 `//` 前缀（+ 可选空格）后用 yaml.safe_load 解析
- 无 frontmatter 返回 None
"""

from __future__ import annotations

import re
from typing import Any

import yaml

_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\s*[:{]", re.MULTILINE)
_TEMPLATE_PARAM_RE = re.compile(r"template\s*<[^>]*>\s*$", re.MULTILINE)
_FM_BORDER_RE = re.compile(r"^//\s*-{3,}\s*$")


def _strip_comment_prefix(line: str) -> str:
    """去掉 `//` 前缀和最多 1 个空格。"""
    s = line.lstrip()
    if s.startswith("//"):
        rest = s[2:]
        if rest.startswith(" "):
            rest = rest[1:]
        return rest
    return s


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    """解析 .h 文本，返回 frontmatter dict 或 None。

    frontmatter 必须出现在文件头部，第一个 `// ---` 行之前允许有少量空行
    或非 `//` 注释行（视为 license/header），但不能有代码。
    """
    lines = text.splitlines()
    start_idx: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "":
            continue
        # 第一段非空行：必须是注释
        if not (stripped.startswith("//") or stripped.startswith("/*")):
            return None
        if _FM_BORDER_RE.match(line):
            start_idx = i
            break
        # 是普通注释（license/header），继续往下扫
        # 但只容忍前 30 行还没遇到 ---，视为无 frontmatter
        if i >= 30:
            return None

    if start_idx is None:
        return None

    # 找结束边界
    end_idx: int | None = None
    for j in range(start_idx + 1, len(lines)):
        if _FM_BORDER_RE.match(lines[j]):
            end_idx = j
            break
    if end_idx is None:
        return None

    yaml_lines = [_strip_comment_prefix(lines[k]) for k in range(start_idx + 1, end_idx)]
    yaml_text = "\n".join(yaml_lines)
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def extract_class_name(text: str) -> str | None:
    """regex 提取第一个 `class Foo :` 或 `class Foo {` 的类名。"""
    m = _CLASS_RE.search(text)
    return m.group(1) if m else None


def extract_template_default_param(text: str) -> dict[str, Any] | None:
    """从 `template <unsigned int WindowSize = 21>` 提取默认参数。

    用于老因子导入时生成 xname 后缀（如 _w21）。
    返回 dict 如 {"window": 21} 或 None。
    """
    m = re.search(
        r"template\s*<\s*([^>]*?\bunsigned\s+int\s+(\w+)\s*=\s*(\d+))",
        text,
    )
    if not m:
        return None
    param_name = m.group(2).lower()
    # 常见映射：WindowSize -> window
    name_map = {"windowsize": "window", "period": "period", "lookback": "lookback"}
    key = name_map.get(param_name, param_name)
    return {key: int(m.group(3))}


def param_suffix(params: dict[str, Any] | None) -> str:
    """根据 params dict 生成 xname 后缀。

    约定：
    - 无参数 → ""
    - 单参数 window=21 → "_w21"
    - 多参数 → "_w21_t0.5"（k=首字母 + 值）
    """
    if not params:
        return ""
    parts = []
    for k, v in params.items():
        # window -> w, threshold -> t, period -> p
        prefix = k[0] if k else "x"
        # 浮点转字符串：去掉小数点歧义
        if isinstance(v, float):
            sv = f"{v}".replace(".", "p")
        else:
            sv = str(v)
        parts.append(f"{prefix}{sv}")
    return "_" + "_".join(parts) if parts else ""


def make_xname(class_name: str, params: dict[str, Any] | None) -> str:
    return f"{class_name}{param_suffix(params)}"


def serialize_frontmatter(meta: dict[str, Any]) -> str:
    """把 dict 序列化为 // YAML 注释块文本（不含前后空行）。

    多行字符串用 YAML `|` 块标量；每行加 `// ` 前缀。
    """
    # 强制字段顺序（可读性）
    ordered_keys = [
        "xname", "class_name", "file", "category",
        "formula", "description",
        "tags", "params",
        "parent_xname", "idea_id",
        "status", "created_ts",
    ]
    other_keys = [k for k in meta if k not in ordered_keys]
    keys = [k for k in ordered_keys if k in meta] + other_keys

    out_lines: list[str] = ["// ---"]
    for k in keys:
        v = meta[k]
        if v is None:
            out_lines.append(f"// {k}: null")
        elif isinstance(v, str) and "\n" in v:
            out_lines.append(f"// {k}: |")
            for ln in v.splitlines():
                out_lines.append(f"//   {ln}")
        elif isinstance(v, list):
            if not v:
                out_lines.append(f"// {k}: []")
            else:
                items = ", ".join(str(x) for x in v)
                out_lines.append(f"// {k}: [{items}]")
        elif isinstance(v, dict):
            if not v:
                out_lines.append(f"// {k}: {{}}")
            else:
                items = ", ".join(f"{dk}: {dv}" for dk, dv in v.items())
                out_lines.append(f"// {k}: {{{items}}}")
        else:
            out_lines.append(f"// {k}: {v}")
    out_lines.append("// ---")
    return "\n".join(out_lines)


def has_frontmatter(text: str) -> bool:
    return parse_frontmatter(text) is not None


def inject_frontmatter(text: str, meta: dict[str, Any]) -> str:
    """在 `#pragma once` 之前插入 frontmatter。

    如果文件已有 frontmatter（头部 // --- 块），先剥离旧的再插新的。
    """
    lines = text.splitlines()
    # 剥离已有 frontmatter
    if has_frontmatter(text):
        start_idx: int | None = None
        end_idx: int | None = None
        for i, line in enumerate(lines):
            if _FM_BORDER_RE.match(line):
                if start_idx is None:
                    start_idx = i
                else:
                    end_idx = i
                    break
                if i >= 30:
                    break
        if start_idx is not None and end_idx is not None:
            del lines[start_idx:end_idx + 1]
            # 同时去掉紧跟的空行（避免多次注入堆积空行）
            while start_idx < len(lines) and lines[start_idx].strip() == "":
                del lines[start_idx]

    fm_block = serialize_frontmatter(meta)
    # 找 #pragma once 行插入到它之前
    insert_at = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("#pragma"):
            insert_at = i
            break
    else:
        insert_at = 0

    new_lines = lines[:insert_at] + fm_block.splitlines() + [""] + lines[insert_at:]
    return "\n".join(new_lines)
