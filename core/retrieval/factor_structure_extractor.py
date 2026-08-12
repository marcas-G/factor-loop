#!/usr/bin/env python3
"""Factor Structure Extractor — 双源提取因子结构指纹(R3 查重主体)。

避免 C++ 完整 AST 成本黑洞(313 个含 template 元编程 + ring buffer + 双钩子),
改双源提取:

源1 frontmatter formula 伪代码归一化(查重主力):
  - 提取 YAML `formula:` 块
  - 字段名归一(bid_size[0]/bidSize(0)/bid0 → SIZE_B0 等,跨因子对齐)
  - template_hash: 在 canonical 基础上参数占位化(数字 → <N>),换参也能撞
  - canonical_hash: 不占位,严格精确撞
  - 去注释/去空白/去中文标点后 sha1

源2 C++ 静态扫描(辅助交叉验证):
  - field_signature: 扫 feed()/data() 调用 → 归一名 + 频次
  - operator_primitives: 扫 std::数学 + 自定义算法结构(ring/ewma/rank/gate/zscore)
  - tree_depth/node_count: 主输出表达式运算符嵌套粗估
  - complexity: 按 primitives 种类 + node_count 粗档

输出 dict,直接 upsert factor_structure 表。
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path


# ── frontmatter 提取 ────────────────────────────────────────────────────────
_FM_RE = re.compile(r"^//\s*---\s*$", re.MULTILINE)


def parse_frontmatter(text: str) -> dict:
    """从 .h 顶部 `// ---` 围栏里提取 frontmatter(YAML-lite)。

    返回 {raw: 全文注释行去 prefix 后的文本, xname, class_name, formula, tags, params}。
    formula 是多行 YAML(`formula: |`),保留缩进内容。
    """
    lines = text.splitlines()
    # 找首尾 // ---
    start = None
    end = None
    for i, ln in enumerate(lines):
        if ln.strip() == "// ---":
            if start is None:
                start = i
            else:
                end = i
                break
    if start is None or end is None:
        return {}
    fm_lines = []
    for ln in lines[start + 1:end]:
        # 去 `// ` 前缀
        m = re.match(r"^\s*//\s?(.*)$", ln)
        fm_lines.append(m.group(1) if m else ln)
    fm_text = "\n".join(fm_lines)

    out = {"raw": fm_text}
    # 单行字段
    for key in ("xname", "class_name", "purpose"):
        m = re.search(rf"^{key}:\s*(.*)$", fm_text, re.MULTILINE)
        if m:
            out[key] = m.group(1).strip()
    # formula 多行块 (`formula: |` 到下一个顶层 key)
    fm = re.search(r"^formula:\s*\|\s*\n((?:[ \t]+.*\n?)+)", fm_text, re.MULTILINE)
    if fm:
        out["formula"] = fm.group(1)
    elif re.search(r"^formula:\s*(\S.*)$", fm_text, re.MULTILINE):
        # 单行 formula
        out["formula"] = re.search(r"^formula:\s*(\S.*)$", fm_text, re.MULTILINE).group(1)
    # tags
    tm = re.search(r"^tags:\s*\[(.*)\]", fm_text, re.MULTILINE)
    if tm:
        out["tags"] = [t.strip() for t in tm.group(1).split(",") if t.strip()]
    # params
    pm = re.search(r"^params:\s*(\{.*\})", fm_text, re.MULTILINE)
    if pm:
        out["params"] = pm.group(1)
    return out


# ── 字段归一表(源1 + 源2 共用)────────────────────────────────────────────
# 目标:不同写法(bid_size[0]/bidSize(0)/bid0/feed().bidSize(0))→ 同一归一名 SIZE_B0
FIELD_NORMALIZE = [
    # 价格族
    (r"midPrice\w*|mid_price|bestBid|bestAsk", "PRICE_MID"),
    (r"bidPrice\(0\)|bid_price\[0\]|feed\(\)\.bid\((?!.*Mantissa)", "PRICE_B0"),
    (r"askPrice\(0\)|ask_price\[0\]|feed\(\)\.ask\((?!.*Mantissa)", "PRICE_A0"),
    # 挂单族(bid0/ask0/bidSize(0)/bid_size[0] 全归一)
    (r"bid_?size\[?0?\]?|bidSize\((?:0|static_cast<int>\(0\)|int\(0\))\)|\bbid0\b", "SIZE_B0"),
    (r"ask_?size\[?0?\]?|askSize\((?:0|static_cast<int>\(0\)|int\(0\))\)|\bask0\b", "SIZE_A0"),
    (r"bid_?size\[?1?\]?|bidSize\((?:1|static_cast<int>\(1\)|int\(1\))\)|\bbid1\b", "SIZE_B1"),
    (r"ask_?size\[?1?\]?|askSize\((?:1|static_cast<int>\(1\)|int\(1\))\)|\bask1\b", "SIZE_A1"),
    (r"bid_?size\[?[iIkK]\]?|bidSize\((?:i|k|static_cast<int>\(i\)|int\(i\))\)", "SIZE_B_N"),
    (r"ask_?size\[?[iIkK]\]?|askSize\((?:i|k|static_cast<int>\(i\)|int\(i\))\)", "SIZE_A_N"),
    # OI / Volume
    (r"open_?[Ii]nterest|openInterest|\booi\b|\boi\b|d_?oi", "OI"),
    (r"total_?[Vv]olume|totalVolume|\bvolume\b|d_?volume", "VOLUME"),
    (r"last_?[Tt]rade_?[Pp]rice|lastTradePrice|last_trade", "TRADE"),
    (r"turnover", "TURNOVER"),
    (r"bidNumLevels|askNumLevels|numLevels", "LEVELS"),
]


def normalize_fields(text: str) -> str:
    """按 FIELD_NORMALIZE 表把字段调用归一成 SIZE_B0/OI 等。"""
    out = text
    for pat, repl in FIELD_NORMALIZE:
        out = re.sub(pat, repl, out)
    return out


# ── 源1 formula 归一化 → canonical/template hash ──────────────────────────
def _strip_for_hash(text: str) -> str:
    """去注释/去空白/去中文标点/小写,使 hash 稳定。"""
    # 去 // 注释(行内 + 整行)
    text = re.sub(r"//[^\n]*", "", text)
    # 去 /* */ 块注释
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # 去中文标点 + 全角
    text = re.sub(r"[，。；：（）/「」『』]", "", text)
    # 去所有空白
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _parameterize(text: str) -> str:
    """数字常量 → <N>(template_hash 用,换参也能撞)。
    保留字段归一名(SIZE_B0 等无数字),只替换裸数字。"""
    # 1e-12 / 0.5 / 60 等数字 → <N>(但不替换归一名里的 B0/A0 — 那是大写字母+数字,
    # 归一名本身无小写数字,故先归一后占位安全)
    return re.sub(r"\d+\.?\d*(?:e-?\d+)?", "<N>", text)


def formula_hashes(formula: str) -> tuple[str, str, str]:
    """返回 (canonical_text, canonical_hash, template_hash)。

    canonical_text: 字段归一 + 去 hash 噪声(不占位,可读审计)
    canonical_hash: sha1(canonical_text 进一步 strip)
    template_hash: sha1(canonical_text 占位化后 strip)
    """
    if not formula:
        return ("", "", "")
    norm = normalize_fields(formula)
    canonical_text = norm.strip()
    stripped = _strip_for_hash(norm)
    canonical_hash = hashlib.sha1(stripped.encode()).hexdigest()[:16]
    templated = _parameterize(stripped)
    template_hash = hashlib.sha1(templated.encode()).hexdigest()[:16]
    return (canonical_text, canonical_hash, template_hash)


# ── 源2 C++ 静态扫描 ────────────────────────────────────────────────────────
# field_signature: feed()/data() 调用 → 归一名
_CALL_RE = re.compile(
    r"(?:feed\(\)|data)\.([a-zA-Z_]+)\s*\(([^)]*)\)"
)


def scan_field_signature(code: str) -> dict:
    """扫 C++ 代码里所有 feed()/data() 调用,归一成 field 名 + 频次。"""
    counts = Counter()
    for m in _CALL_RE.finditer(code):
        method = m.group(1)
        arg = m.group(2).strip()
        # 映射到归一名
        key = _method_to_field(method, arg)
        if key:
            counts[key] += 1
    return dict(counts)


def _method_to_field(method: str, arg: str) -> str | None:
    """feed().method(arg) → 归一字段名。"""
    # arg 归一:0/1/具体数 → _0/_1/_N;i/k/变量 → _N
    if arg == "":
        tag = ""
    elif re.fullmatch(r"0|static_cast<int>\(0\)|int\(0\)", arg):
        tag = "_0"
    elif re.fullmatch(r"1|static_cast<int>\(1\)|int\(1\)", arg):
        tag = "_1"
    elif re.fullmatch(r"\d+", arg):
        tag = "_" + arg
    else:
        tag = "_N"
    table = {
        "bidSize": "SIZE_B", "askSize": "SIZE_A",
        "bidPrice": "PRICE_B", "askPrice": "PRICE_A",
        "bid": "PRICE_B", "ask": "PRICE_A",  # feed().bid(0) 是价格
        "midPriceMantissa": "PRICE_MID", "midPrice": "PRICE_MID",
        "openInterest": "OI", "totalVolume": "VOLUME", "turnover": "TURNOVER",
        "lastTradePrice": "TRADE",
        "bidNumLevels": "LEVELS_B", "askNumLevels": "LEVELS_A",
        "isValid": None, "tickDouble": None, "trade": None,
        "mantissaToPriceFactor": None,
    }
    base = table.get(method)
    if base is None:
        return None
    return base + tag


# operator_primitives: std::数学 + 自定义算法结构
_MATH_PRIM_RE = re.compile(
    r"std::(log1p|log|tanh|sigmoid|sqrt|fabs|abs|exp|max|min|clamp|pow)\b"
)
# 自定义算法结构(变量名/函数名/类名线索)
_STRUCT_PRIM_PATTERNS = [
    (r"percentile_?[Rr]ank|percentileRankInRing", "rank"),
    (r"_ring|pushRun|pushMid|环形缓冲", "ring"),
    (r"_?ewma|EWMA|_decay|Decay", "ewma"),
    (r"z_?score|zscore|runZ|_std\b", "zscore"),
    (r"sigmoid\(", "sigmoid"),
    (r"gate|_gate|Gate", "gate"),
    (r"runLen|runSign|streak|run_?length", "runlen"),
    (r"\babs_?diff|d_?imb|d_?mid|d_?oi|first_?diff|_delta\b", "diff"),
    (r"sum\b|\.sum|_sum\b", "sum"),
    (r"mean\b|_mean\b|average", "mean"),
    (r"entropy|shannon", "entropy"),
    (r"correlation|corr\b|pearson", "corr"),
    (r"hawkes|Hawkes", "hawkes"),
    (r"phase|episode", "phase"),
]


def scan_operator_primitives(code: str) -> dict:
    """扫数学原语 + 算法结构原语,返回 {primitive: count}。"""
    counts = Counter()
    for m in _MATH_PRIM_RE.finditer(code):
        counts[m.group(1)] += 1
    for pat, name in _STRUCT_PRIM_PATTERNS:
        n = len(re.findall(pat, code))
        if n:
            counts[name] += n
    return dict(counts)


def estimate_depth_nodecount(code: str, formula: str) -> tuple[int, int]:
    """粗估主输出表达式的运算符嵌套深度 + 节点数。

    不做真 AST,只数运算符密度作为复杂度代理:
      - node_count: 运算符(+ - * / ?: && || 等)+ 函数调用数(主输出行)
      - tree_depth: 嵌套括号深度(主输出表达式)
    优先用 formula 伪代码(更干净),fallback 到 C++ onEndBook。
    """
    src = formula or _extract_onendbook(code)
    if not src:
        return (0, 0)
    # 找 output = / _output = / setXValue 行(主输出表达式)
    out_line = None
    for ln in src.splitlines():
        if re.search(r"output\s*=|setXValue|_output\s*=", ln) and "if" not in ln:
            out_line = ln
            break
    expr = out_line or src
    # node_count: 运算符 + 函数调用
    ops = len(re.findall(r"[+\-*/%]|&&|\|\||\?|:|,|<|>|<=|>=|==|!=", expr))
    calls = len(re.findall(r"[a-zA-Z_]\w*\s*\(", expr))
    node_count = ops + calls
    # tree_depth: 最大括号嵌套
    depth = 0
    cur = 0
    for ch in expr:
        if ch == "(":
            cur += 1
            depth = max(depth, cur)
        elif ch == ")":
            cur = max(0, cur - 1)
    return (depth, node_count)


def _extract_onendbook(code: str) -> str:
    """提取 onEndBook 方法体(粗,正则)。"""
    m = re.search(r"void\s+onEndBook\s*\(\)\s*\{(.*?)^\s*\}", code, re.DOTALL | re.MULTILINE)
    return m.group(1) if m else code


# 状态原语(有时序累积/序列结构,不算 trivial)
_STATE_PRIMS = {"ring", "ewma", "runlen", "phase", "hawkes"}
# 复合算法结构原语(非纯数学变换)
_STRUCT_PRIMS = {"rank", "gate", "corr", "entropy"}


def complexity_bucket(primitives: dict, field_sig: dict, node_count: int) -> str:
    """按 state/结构原语 + field 族数 + node_count 粗分档。

    trivial: 无 state + 无结构复合 + field 单族(纯单步基底如 ImbalanceBase)
    moderate: 有非线性变换(log/tanh/sigmoid)但无 state,或 field 多族单步
    complex: 有 state 原语(ring/ewma/runlen/phase/hawkes)或多结构原语叠加
    """
    prims = set(primitives)
    has_state = bool(prims & _STATE_PRIMS)
    has_struct = bool(prims & _STRUCT_PRIMS)
    has_nonlinear = bool(prims & {"log", "log1p", "tanh", "sigmoid", "exp", "pow"})
    # field 族:从 SIZE_B0/PRICE_MID/OI 等提取大类
    field_families = set()
    for k in field_sig:
        fam = k.split("_")[0]
        field_families.add(fam)

    if has_state or (has_struct and len(prims) >= 3):
        return "complex"
    if has_nonlinear or len(field_families) >= 2 or has_struct:
        return "moderate"
    return "trivial"


# ── 主入口 ──────────────────────────────────────────────────────────────────
def extract_structure(h_path: str | Path) -> dict | None:
    """提取单个 .h 的结构指纹。返回 dict(None 表示无 frontmatter/formula)。"""
    h_path = Path(h_path)
    text = h_path.read_text(encoding="utf-8", errors="replace")
    fm = parse_frontmatter(text)
    if not fm or "formula" not in fm:
        return None

    formula = fm.get("formula", "")
    xname = fm.get("xname", h_path.stem)

    canonical_text, canonical_hash, template_hash = formula_hashes(formula)
    field_sig = scan_field_signature(text)
    primitives = scan_operator_primitives(text)
    depth, node_count = estimate_depth_nodecount(text, formula)
    complexity = complexity_bucket(primitives, field_sig, node_count)

    return {
        "xname": xname,
        "canonical_text": canonical_text,
        "canonical_hash": canonical_hash,
        "template_hash": template_hash,
        "tree_depth": depth,
        "node_count": node_count,
        "field_signature": field_sig,
        "operator_primitives": primitives,
        "complexity": complexity,
        "source_formula": formula.strip(),
        "source_file": str(h_path),
    }


def upsert_structure(conn, rec: dict) -> None:
    """写入 factor_structure 表(UPSERT by xname)。"""
    import json
    conn.execute("""
        INSERT INTO factor_structure
            (xname, canonical_text, canonical_hash, template_hash,
             tree_depth, node_count, field_signature, operator_primitives,
             complexity, source_formula, source_file)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(xname) DO UPDATE SET
            canonical_text=excluded.canonical_text,
            canonical_hash=excluded.canonical_hash,
            template_hash=excluded.template_hash,
            tree_depth=excluded.tree_depth,
            node_count=excluded.node_count,
            field_signature=excluded.field_signature,
            operator_primitives=excluded.operator_primitives,
            complexity=excluded.complexity,
            source_formula=excluded.source_formula,
            source_file=excluded.source_file,
            extracted_at=CURRENT_TIMESTAMP
    """, (
        rec["xname"], rec["canonical_text"], rec["canonical_hash"], rec["template_hash"],
        rec["tree_depth"], rec["node_count"],
        json.dumps(rec["field_signature"], ensure_ascii=False),
        json.dumps(rec["operator_primitives"], ensure_ascii=False),
        rec["complexity"], rec["source_formula"], rec["source_file"],
    ))


if __name__ == "__main__":
    import sys
    import json
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        rec = extract_structure(target)
        if rec is None:
            print(f"NO FRONTMATTER/FORMULA: {target}")
            sys.exit(1)
        # 不打 canonical_text(长),分项打印
        rec_show = {k: v for k, v in rec.items() if k != "source_formula"}
        print(json.dumps(rec_show, ensure_ascii=False, indent=2))
    else:
        print("usage: factor_structure_extractor.py <factor.h>")
