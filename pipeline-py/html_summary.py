#!/usr/bin/env python3
"""
因子评估 HTML 总结报告。

在 factor-evaluate --mode full 完成后自动调用，
汇总 feval / pearson / deep 结果生成简洁的 HTML 总结报告。

输出的 HTML 放在 <output_dir>/<factor_name>_summary.html，
每个因子一份，直接用浏览器打开即可阅读。
"""

import base64
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

import numpy as np
import pandas as pd


# ─── CSS ────────────────────────────────────────────────────────────────────

_CSS = """
body {
  font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  margin: 0; padding: 24px; background: #f5f6f7; color: #1d1d1f; line-height: 1.65;
}
.wrap {
  max-width: 1080px; margin: 0 auto; background: #fff;
  padding: 36px 44px; border-radius: 10px; box-shadow: 0 1px 6px rgba(0,0,0,.07);
}
h1 { font-size: 1.4em; margin: 0 0 4px; }
h2 { font-size: 1.1em; margin: 18px 0 8px; padding-bottom: 6px; border-bottom: 1.5px solid #e5e5e7; }
h3 { font-size: .95em; margin: 20px 0 8px; color: #48484a; }
.m { color: #86868b; font-size: .83em; margin: 0 0 20px; }
table { width: 100%; border-collapse: collapse; margin: 6px 0 18px; font-size: .83em; }
th, td { padding: 6px 10px; text-align: center; border-bottom: 1px solid #f0f0f0; }
th { background: #fafafa; font-weight: 600; color: #6e6e73; font-size: .9em; }
td:first-child, th:first-child { text-align: left; }
.g { color: #34c759; font-weight: 600; }
.b { color: #ff3b30; font-weight: 600; }
.p { font-family: SFMono-Regular, Consolas, monospace; font-size: .82em; color: #6e6e73; }
.ch { text-align: center; margin: 20px 0; padding: 12px; background: #fafbfc; border-radius: 8px; border: 1px solid #eee; }
.ch img { max-width: 96%; height: auto; display: block; border-radius: 6px; margin: 0 auto; }
.ch .cap { color: #86868b; font-size: .8em; margin-top: 6px; }
.ch.wide { overflow-x: auto; }
.ch.wide img { max-width: 120%; min-width: 800px; }
.logic { background: #f8f9fa; padding: 14px 18px; border-radius: 6px; margin: 8px 0 16px; line-height: 1.8; }
.logic h3, .logic h4 { margin: 10px 0 6px; }
.logic p { margin: 4px 0; font-size: .88em; }
.formula { font-family: SFMono-Regular, Consolas, monospace; font-size: .84em; background: #eef1f5; padding: 4px 10px; border-radius: 4px; margin: 3px 0; color: #1d1d1f; }
.code { background: #1e1e2e; color: #cdd6f4; padding: 14px 18px; border-radius: 6px; overflow-x: auto; font-size: .82em; line-height: 1.5; margin: 8px 0 16px; white-space: pre-wrap; }
.eval { background: #f0f7ff; border-left: 4px solid #007aff; padding: 14px 18px; border-radius: 4px; margin: 16px 0; line-height: 1.8; }
.eval p { margin: 2px 0; font-size: .88em; }
"""


# ─── Helpers ────────────────────────────────────────────────────────────────

def _csv(path) -> Optional[pd.DataFrame]:
    return pd.read_csv(path) if os.path.exists(path) else None


def _b64(path) -> Optional[str]:
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _f(v, n=4):
    if pd.isna(v):
        return "—"
    return f"{v:.{n}f}"


def _td(cls, text):
    return f"<td class='{cls}'>{text}</td>" if cls else f"<td>{text}</td>"


def _ic_cls(v):
    a = abs(v) if not pd.isna(v) else 0
    return "g" if a >= 0.08 else ("b" if a < 0.03 else "")


def _decay_cls(v):
    return "g" if v >= 0.7 else ("b" if v < 0.4 else "")



# ─── Factor Discovery ──────────────────────────────────────────────────────

def _find_factors(root: Path) -> List[Dict]:
    factors = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        dailyx = entry / "dailyX"
        if not dailyx.is_dir():
            continue
        h_files = list(dailyx.glob("*.h"))
        name = h_files[0].stem if h_files else entry.name
        factors.append({"name": name, "dailyx": dailyx})
    return factors


# ─── Table Builders ─────────────────────────────────────────────────────────


def _tbl_screening(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.head(30).iterrows():
        ic = r.get("ic_mean", np.nan)
        ir = r.get("ic_ir", np.nan)
        rows.append(
            f"<tr><td class='p'>{r.get('x_col','')}</td><td class='p'>{r.get('y_col','')}</td>"
            f"{_td(_ic_cls(ic), _f(ic))}"
            f"{_td(_ic_cls(ir), _f(ir))}"
            f"<td>{_f(r.get('spearman_r',np.nan))}</td>"
            f"<td>{_f(r.get('sign_match_rate',np.nan),2)}</td>"
            f"<td>{int(r.get('nonzero_count',0)):,}</td></tr>"
        )
    hdr = "<tr><th>X</th><th>Y</th><th>IC</th><th>IR</th><th>Spearman</th><th>Sign%</th><th>N</th></tr>"
    return f"<table>{hdr}{''.join(rows)}</table>"


def _tbl_tt(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.head(30).iterrows():
        decay = r.get("ic_decay", np.nan)
        sign = "Y" if r.get("same_sign", False) else "N"
        s_cls = "g" if r.get("same_sign", False) else "b"
        rows.append(
            f"<tr><td class='p'>{r.get('x_col','')}</td><td class='p'>{r.get('y_col','')}</td>"
            f"<td>{_f(r.get('train_ic',np.nan))}</td>"
            f"<td>{_f(r.get('test_ic',np.nan))}</td>"
            f"{_td(_decay_cls(decay), _f(decay))}"
            f"<td class='{s_cls}'>{sign}</td></tr>"
        )
    hdr = "<tr><th>X</th><th>Y</th><th>Train IC</th><th>Test IC</th><th>Decay</th><th>Sign</th></tr>"
    return f"<table>{hdr}{''.join(rows)}</table>"


def _tbl_session(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.head(30).iterrows():
        std = r.get("ic_std_across_sessions", np.nan)
        std_cls = "g" if not pd.isna(std) and std < 0.02 else ""
        rows.append(
            f"<tr><td class='p'>{r.get('x_col','')}</td><td class='p'>{r.get('y_col','')}</td>"
            f"<td>{_f(r.get('morning_ic',np.nan))}</td>"
            f"<td>{_f(r.get('midday_ic',np.nan))}</td>"
            f"<td>{_f(r.get('afternoon_ic',np.nan))}</td>"
            f"<td>{_f(r.get('night_ic',np.nan))}</td>"
            f"{_td(std_cls, _f(std))}</tr>"
        )
    hdr = "<tr><th>X</th><th>Y</th><th>早盘</th><th>午盘</th><th>下午</th><th>夜盘</th><th>std</th></tr>"
    return f"<table>{hdr}{''.join(rows)}</table>"


def _tbl_zero(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.head(30).iterrows():
        pv = r.get("p_value", 1.0)
        p_cls = "g" if pv < 0.05 else ""
        rows.append(
            f"<tr><td class='p'>{r.get('x_col','')}</td><td class='p'>{r.get('y_col','')}</td>"
            f"<td>{_f(r.get('zero_ratio',np.nan),2)}</td>"
            f"<td>{_f(r.get('y_mean_x0',np.nan))}</td>"
            f"<td>{_f(r.get('y_mean_xnz',np.nan))}</td>"
            f"<td>{_f(r.get('t_stat',np.nan),2)}</td>"
            f"{_td(p_cls, f'{pv:.4g}')}</tr>"
        )
    hdr = "<tr><th>X</th><th>Y</th><th>零值率</th><th>Y(0)</th><th>Y(!0)</th><th>t-stat</th><th>p-value</th></tr>"
    return f"<table>{hdr}{''.join(rows)}</table>"


def _tbl_generic(df: pd.DataFrame) -> str:
    if df.empty:
        return "<p class='m'>no data</p>"
    hdr = "".join(f"<th>{c}</th>" for c in df.columns)
    rows = []
    for _, r in df.head(30).iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            cells.append(f"<td>{_f(v) if isinstance(v, (float, np.floating)) else v}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><tr>{hdr}</tr>{''.join(rows)}</table>"


# ─── Section Renderers ─────────────────────────────────────────────────────

def _extract_h_docblock(h_path: Path) -> str:
    """Extract the top /** ... */ doc-comment block from a .h file."""
    import re
    try:
        text = h_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    m = re.search(r'/\*\*(.*?)\*/', text, re.DOTALL)
    if not m:
        return ""
    raw = m.group(1)
    # Strip leading * from each line
    lines = [re.sub(r'^\s*\*\s?', '', line) for line in raw.splitlines()]
    return "\n".join(lines).strip()


def _docblock_to_overview_html(doc: str) -> str:
    """Convert a .h doc-comment block into a compact HTML overview.

    Renders:
      - @brief → factor name badge
      - 核心思想 → summary paragraph
      - Formula lines (contain =) → <code> block for readability
      - 输出因子 → output factor table
    """
    import re
    if not doc:
        return ""

    sections = []
    lines = doc.splitlines()
    buf = []           # running paragraph buffer
    current_heading = ""
    in_outputs = False
    output_rows = []

    def flush_buf():
        nonlocal current_heading
        if not buf:
            return
        text = " ".join(buf).strip()
        buf.clear()
        if not text:
            return
        text = _escape_html(text)
        if current_heading:
            sections.append(f"<h4>{current_heading}</h4>")
            current_heading = ""
        sections.append(f"<p>{text}</p>")

    for line in lines:
        stripped = line.strip()

        # @brief → skip (title is already in <h1>)
        if stripped.startswith("@brief"):
            continue
        if stripped.startswith("@author") or stripped.startswith("@date"):
            continue

        # 输出因子 table
        m_out = re.match(r'^\s*(\d+)\s*:\s*(\S+)\s*(.*)', stripped)
        if m_out and in_outputs:
            idx, fname, desc = m_out.groups()
            output_rows.append((idx, fname, desc))
            continue

        if stripped.startswith("输出因子"):
            flush_buf()
            in_outputs = True
            current_heading = "输出因子"
            continue

        # Blank line → paragraph break
        if not stripped:
            flush_buf()
            continue

        # Detect heading-like lines (short, no trailing period, often end with :)
        # Exclude lines containing '=' (those are formulas, not headings)
        if (len(stripped) < 30
                and not stripped.endswith(('.', ','))
                and not stripped.startswith('-')
                and '=' not in stripped):
            flush_buf()
            current_heading = stripped.rstrip(':')
            continue

        in_outputs = False

        # Formula lines: contain '=' and at least one math-like symbol
        # Render them as standalone <code> for readability
        math_chars = set('Σσμεραβγδθλπω·×±∈√∫')
        has_math = any(c in math_chars for c in stripped)
        has_equals = ('=' in stripped
                      and not stripped.startswith('注意')
                      and not stripped.startswith('不同')
                      and not stripped.startswith('>=')
                      and not stripped.startswith('<='))
        # Also match short lines with math symbols (even without =)
        is_formula = has_equals and (has_math or len(stripped) < 60)
        if has_math and not has_equals and len(stripped) < 80:
            is_formula = True
        if is_formula:
            flush_buf()
            sections.append(f"<p class='formula'>{_escape_html(stripped)}</p>")
        else:
            buf.append(stripped)

    flush_buf()

    # Render output factor table
    if output_rows:
        rows_html = "".join(
            f"<tr><td>{i}</td><td><code>{n}</code></td><td>{d}</td></tr>"
            for i, n, d in output_rows
        )
        sections.append(
            "<table><tr><th>#</th><th>因子</th><th>说明</th></tr>"
            f"{rows_html}</table>"
        )

    return "\n".join(sections)


def _escape_html(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _add_factor_logic(parts: list, fac: Dict, root: Path):
    """Add factor logic description section — looks for desc.md or auto-extract from .h."""
    name = fac["name"]
    dailyx = fac["dailyx"]

    # Look for user-provided description file
    desc_sources = [
        root / f"{name}_desc.md",
        dailyx / f"{name}_desc.md",
    ]
    for desc_path in desc_sources:
        if desc_path.exists():
            with open(desc_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                parts.append("<h2>因子逻辑</h2>")
                parts.append(f"<div class='logic'>{_md_to_html(content)}</div>")
                return

    # Auto-extract from .h doc-comment block
    h_files = list(dailyx.glob("*.h"))
    if h_files:
        doc = _extract_h_docblock(h_files[0])
        if doc:
            overview = _docblock_to_overview_html(doc)
            if overview:
                parts.append("<h2>因子逻辑</h2>")
                parts.append(f"<div class='logic'>{overview}</div>")
                return

        # Final fallback: embed raw .h source (truncated)
        with open(h_files[0], "r", encoding="utf-8", errors="ignore") as f:
            code = f.read().strip()
        if code:
            if len(code) > 4000:
                code = code[:4000] + "\n... (truncated)"
            parts.append("<h2>因子逻辑</h2>")
            parts.append(f"<pre class='code'>{code}</pre>")


def _add_feval(parts: list, feval_dir: Path, x_filter: str = ""):
    # Screening
    screening = _apply_x_filter(_csv(feval_dir / "screening.csv"), x_filter)
    if screening is not None and not screening.empty:
        parts.append("<h2>feval Core Metrics</h2>")
        n = int(screening.iloc[0].get("n_samples", 0)) if "n_samples" in screening.columns else 0
        if n:
            parts.append(f"<p class='m'>samples: {n:,} rows / {len(screening)} pairs</p>")
        show = [c for c in ["x_col", "y_col", "ic_mean", "ic_ir", "spearman_r",
                             "sign_match_rate", "nonzero_count"] if c in screening.columns]
        parts.append(_tbl_screening(screening[show]))

    # Train/Test
    tt = _apply_x_filter(_csv(feval_dir / "train_test.csv"), x_filter)
    if tt is not None and not tt.empty:
        parts.append("<h3>Train / Test Stability</h3>")
        cols = [c for c in ["x_col", "y_col", "train_ic", "test_ic", "ic_decay", "same_sign"]
                if c in tt.columns]
        parts.append(_tbl_tt(tt[cols]))

    # Session IC
    si = _apply_x_filter(_csv(feval_dir / "session_ic.csv"), x_filter)
    if si is not None and not si.empty:
        parts.append("<h3>Session IC</h3>")
        cols = [c for c in ["x_col", "y_col", "morning_ic", "midday_ic",
                             "afternoon_ic", "night_ic", "ic_std_across_sessions"]
                if c in si.columns]
        parts.append(_tbl_session(si[cols]))

    # Zero Analysis
    za = _apply_x_filter(_csv(feval_dir / "zero_analysis.csv"), x_filter)
    if za is not None and not za.empty:
        parts.append("<h3>Zero Analysis</h3>")
        cols = [c for c in ["x_col", "y_col", "zero_ratio", "y_mean_x0",
                             "y_mean_xnz", "t_stat", "p_value"] if c in za.columns]
        parts.append(_tbl_zero(za[cols]))


def _add_pearson(parts: list, root: Path, name: str, pearson_dir: Optional[Path],
                 x_filter: str = ""):
    # Try batch summary CSV first, fallback to per-factor txt
    summary_csv = root / "all_factors_pearson_summary.csv"
    if summary_csv.exists():
        df = pd.read_csv(summary_csv)
        df = df[df["factor_name"] == name].copy()
    elif pearson_dir and pearson_dir.exists():
        df = _parse_pearson_txt(pearson_dir / "correlation_results.txt", name)
    else:
        return

    if df is None or df.empty:
        return

    df = _apply_x_filter(df, x_filter, col="A_col")
    if df is None or df.empty:
        return

    parts.append("<h2>Pearson Correlation</h2>")

    # Top 10 significant pairs by |correlation|
    sig = df[df["significant"] == "Yes"] if "significant" in df.columns else df
    if sig.empty:
        sig = df
    top = sig.nlargest(min(10, len(sig)), "correlation", keep="all") \
        if "correlation" in sig.columns else sig.head(10)
    cols = [c for c in ["A_col", "B_col", "correlation", "p_value", "significant"]
            if c in top.columns]
    parts.append(_tbl_generic(top[cols].reset_index(drop=True)))


def _add_deep(parts: list, root: Path, name: str, x_filter: str = ""):
    """Parse deep analysis TXT files, show detailed tables + evaluation summary."""
    deep_dir = root / name / "dailyX" / f"{name}_deep"
    if not deep_dir.exists():
        return

    # Parse all 5 deep analysis files
    dic = _apply_x_filter(_parse_deep_table(deep_dir / "daily_ic_results.txt"), x_filter, "A_col")
    ba = _apply_x_filter(_parse_deep_table(deep_dir / "bucket_analysis_results.txt"), x_filter, "A_col")
    ss = _apply_x_filter(_parse_deep_table(deep_dir / "signal_stability_results.txt"), x_filter, "A_col")
    mi = _apply_x_filter(_parse_deep_table(deep_dir / "monthly_ic_results.txt"), x_filter, "A_col")
    ri = _apply_x_filter(_parse_deep_table(deep_dir / "rank_ic_results.txt"), x_filter, "A_col")

    has_any = any(d is not None and not d.empty for d in [dic, ba, ss, mi, ri])
    if not has_any:
        return

    parts.append("<h2>Deep Analysis</h2>")

    # --- Daily IC ---
    if dic is not None and not dic.empty:
        parts.append("<h3>Daily IC Stability (Top 10)</h3>")
        short = _shorten_deep_df(dic.head(10))
        parts.append(_tbl_generic(short))

    # --- Conditional Return ---
    if ba is not None and not ba.empty:
        parts.append("<h3>Conditional Return (Top 10 by Spread IR)</h3>")
        short = _shorten_deep_df(ba.head(10))
        parts.append(_tbl_generic(short))

    # --- Signal Stability ---
    if ss is not None and not ss.empty:
        parts.append("<h3>Signal Rank Stability</h3>")
        short = _shorten_deep_df(ss)
        parts.append(_tbl_generic(short))

    # --- Monthly IC ---
    if mi is not None and not mi.empty:
        parts.append("<h3>Monthly IC (Top 10 by ICIR)</h3>")
        short = _shorten_deep_df(mi.head(10))
        parts.append(_tbl_generic(short))

    # --- Rank IC ---
    if ri is not None and not ri.empty:
        parts.append("<h3>Rank IC (Top 10)</h3>")
        short = _shorten_deep_df(ri.head(10))
        parts.append(_tbl_generic(short))

    # --- Evaluation Summary ---
    # Priority: AI-generated eval file > rule-based fallback
    eval_file = root / f"{name}_deep_eval.md"
    if eval_file.exists():
        try:
            with open(eval_file, "r", encoding="utf-8") as f:
                eval_text = f.read().strip()
            if eval_text:
                # Convert markdown to basic HTML
                eval_html = _md_to_html(eval_text)
                parts.append(f"<h3>因子评估总结</h3><div class='eval'>{eval_html}</div>")
                return  # AI eval takes precedence
        except Exception:
            pass

    # Fallback: rule-based evaluation
    eval_html = _generate_deep_eval(name, dic, ba, ss, mi, ri)
    if eval_html:
        parts.append(f"<h3>因子评估总结</h3><div class='eval'>{eval_html}</div>")


# ─── Deep TXT Parser ──────────────────────────────────────────────────────

def _parse_deep_table(txt_path: Path) -> Optional[pd.DataFrame]:
    """Parse a deep analysis TXT file's summary table (whitespace-separated)."""
    if not txt_path.exists():
        return None
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Find header line (starts with whitespace then column names like A_col)
        header_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith("A_col"):
                header_idx = i
                break
        if header_idx is None:
            return None

        # Collect lines until we hit a blank line or end
        data_lines = []
        for line in lines[header_idx:]:
            stripped = line.strip()
            if not stripped or stripped.startswith("共") or stripped.startswith("平均"):
                break
            data_lines.append(line)
        if len(data_lines) < 2:
            return None

        from io import StringIO
        content = "".join(data_lines)
        df = pd.read_csv(StringIO(content), sep=r'\s+')
        return df
    except Exception:
        return None


def _short_x(col: str) -> str:
    """Shorten X column name for readability."""
    if not col.startswith("X."):
        return col
    s = col[2:]  # strip "X."
    # Extract instrument
    at_pos = s.find("@")
    if at_pos < 0:
        return s
    inst = s[:at_pos].replace("SHFE-", "")
    rest = s[at_pos + 1:]
    # Check level
    parts = rest.split("@", 1)
    if len(parts) == 2 and parts[0].isdigit():
        level = parts[0]
        feature = parts[1]
    else:
        level = ""
        feature = rest
    # Extract key feature part (e.g. od_main from XXY_014h_od_main_...)
    fp = feature.split("_")
    # find od_main / od_sub / od_rel / vg_main etc
    short_feat = ""
    for i, p in enumerate(fp):
        if p in ("od", "vg") and i + 1 < len(fp):
            short_feat = f"{p}_{fp[i+1]}"
            break
    if not short_feat:
        short_feat = feature[:20]
    prefix = f"@{level}" if level else ""
    return f"{inst}{prefix} {short_feat}"


def _short_y(col: str) -> str:
    """Shorten Y column name for readability."""
    if "@" not in col:
        return col
    # Extract instrument and horizon from Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1
    parts = col.rsplit("@", 1)
    if len(parts) == 2:
        inst_part = parts[0].rsplit(".", 1)[-1].replace("SHFE-", "")
        horizon = parts[1]
        return f"{inst_part}@{horizon}s"
    return col


def _shorten_deep_df(df: pd.DataFrame) -> pd.DataFrame:
    """Shorten column names in deep analysis DataFrame for display."""
    df = df.copy()
    rename = {}
    for c in df.columns:
        if c == "A_col":
            rename[c] = "X"
        elif c == "B_col":
            rename[c] = "Y"
        elif c == "daily_ic_tstat":
            rename[c] = "t-stat"
        elif c == "daily_ic_hit_rate":
            rename[c] = "hit%"
        elif c == "daily_ic_mean":
            rename[c] = "IC_mean"
        elif c == "daily_ic_std":
            rename[c] = "IC_std"
        elif c == "annualized_spread_ir":
            rename[c] = "SpreadIR"
        elif c == "daily_spread_mean":
            rename[c] = "spread"
        elif c == "cumulative_spread":
            rename[c] = "cum_spread"
        elif c == "signal_instability_%":
            rename[c] = "instab%"
        elif c == "avg_rank_autocorr":
            rename[c] = "avg_autocorr"
    df = df.rename(columns=rename)
    # Shorten X and Y values
    if "X" in df.columns:
        df["X"] = df["X"].apply(_short_x)
    if "Y" in df.columns:
        df["Y"] = df["Y"].apply(_short_y)
    return df


# ─── Evaluation Summary Generator ─────────────────────────────────────────

def _md_to_html(md: str) -> str:
    """Minimal markdown-to-HTML conversion for eval files."""
    import re
    html = md
    # Bold
    html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html)
    # Headers
    html = re.sub(r'^### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    # Bullet lists
    html = re.sub(r'^- (.+)$', r'<p>• \1</p>', html, flags=re.MULTILINE)
    # Paragraphs: double newline
    html = re.sub(r'\n\n+', '</p><p>', html)
    return html


def _generate_deep_eval(_name, dic, ba, ss, mi, _ri) -> str:
    """Generate a concise evaluation paragraph from deep analysis data."""
    lines = []

    # --- Best Daily IC pair ---
    if dic is not None and not dic.empty:
        best = dic.iloc[0]
        x_short = _short_x(best.get("A_col", ""))
        y_short = _short_y(best.get("B_col", ""))
        tstat = best.get("daily_ic_tstat", 0)
        hit = best.get("daily_ic_hit_rate", 0)
        ic_mean = best.get("daily_ic_mean", 0)
        n_days = int(best.get("n_days", 0))
        lines.append(
            f"<b>核心信号</b>: {x_short} → {y_short}, "
            f"Daily IC={ic_mean:.4f}, t-stat={tstat:.1f}, "
            f"{hit*100:.0f}%正向日 ({n_days}天)"
        )

    # --- Conditional Return ---
    if ba is not None and not ba.empty:
        best_ba = ba.iloc[0]
        spread_ir = best_ba.get("annualized_spread_ir", 0)
        cum = best_ba.get("cumulative_spread", 0)
        mono = best_ba.get("monotonic", "")
        mono_cls = "g" if mono == "positive" else ("b" if mono == "non_monotonic" else "")
        n_positive = int((ba["monotonic"] == "positive").sum())
        n_total = len(ba)
        lines.append(
            f"<b>条件收益</b>: Spread IR(ann.)={spread_ir:.1f}, "
            f"累计价差={cum:.2f}, "
            f"单调性=<span class='{mono_cls}'>{mono}</span>, "
            f"{n_positive}/{n_total} 对正向单调"
        )

        # Horizon pattern: short vs long
        short_mono = ba[ba["B_col"].str.contains("@1|@5|@10", regex=True)]
        long_mono = ba[ba["B_col"].str.contains("@60|@300", regex=True)]
        short_pos = int((short_mono["monotonic"] == "positive").sum())
        long_pos = int((long_mono["monotonic"] == "positive").sum())
        if short_pos > 0 or long_pos > 0:
            lines.append(
                f"<b>周期衰减</b>: 短周期({short_pos}/{len(short_mono)}正向) → "
                f"长周期({long_pos}/{len(long_mono)}正向)"
            )

    # --- Cross-instrument ---
    if dic is not None and not dic.empty:
        cu_pairs = dic[dic["A_col"].str.contains("SHFE-CU")]
        if not cu_pairs.empty:
            best_cu = cu_pairs.iloc[0]
            cu_tstat = best_cu.get("daily_ic_tstat", 0)
            cu_ic = best_cu.get("daily_ic_mean", 0)
            lines.append(
                f"<b>跨品种</b>: CU→AG 最强 Daily IC={cu_ic:.4f} (t={cu_tstat:.1f})"
            )

    # --- Signal Stability ---
    if ss is not None and not ss.empty:
        avg_instab = ss["signal_instability_%"].mean()
        instab_cls = "g" if avg_instab < 20 else ("b" if avg_instab > 40 else "")
        lines.append(
            f"<b>信号稳定性</b>: 平均不稳定性=<span class='{instab_cls}'>{avg_instab:.1f}%</span>"
        )

    # --- Monthly IC ---
    if mi is not None and not mi.empty:
        best_mi = mi.iloc[0]
        icir = best_mi.get("icir", 0)
        hit_m = best_mi.get("hit_rate", 0)
        n_months = int(best_mi.get("n_months", 0))
        lines.append(
            f"<b>月度 IC</b>: ICIR={icir:.1f}, 月胜率={hit_m*100:.0f}% ({n_months}个月)"
        )

    if not lines:
        return ""
    return "<br>\n".join(f"<p>{l}</p>" for l in lines)


def _add_charts(parts: list, feval_dir: Path):
    parts.append("<h2>Key Charts</h2>")
    charts = [
        ("dashboard", "Dashboard", False),
        ("ic_decay", "IC Decay Curve", False),
        ("train_test", "Train / Test Scatter", False),
        ("quintile", "Quintile Monotonicity", True),
        ("session_ic", "Session IC", False),
        ("nrmse", "NRMSE Comparison", False),
        ("vol_regime_ic", "Volatility Regime IC", False),
    ]
    found = False
    for fname, caption, wide in charts:
        b64 = _b64(feval_dir / f"{fname}.png")
        if b64:
            found = True
            cls = "ch wide" if wide else "ch"
            parts.append(
                f"<div class='{cls}'>"
                f"<img src='data:image/png;base64,{b64}' />"
                f"<div class='cap'>{caption}</div></div>"
            )
    if not found:
        parts.append("<p class='m'>no charts</p>")


# ─── Pearson TXT Fallback Parser ───────────────────────────────────────────

def _parse_pearson_txt(txt_path: Path, name: str) -> Optional[pd.DataFrame]:
    if not txt_path.exists():
        return None
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        rows = []
        in_cross = False
        for line in lines:
            if "A组<->B组交叉统计" in line:
                in_cross = True
                continue
            if in_cross and line.strip().startswith("---"):
                continue
            if in_cross and line.strip() and not line.strip().startswith("A组") \
                    and not line.strip().startswith("共"):
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        float(parts[2])
                        rows.append({
                            "factor_name": name, "A_col": parts[0], "B_col": parts[1],
                            "correlation": float(parts[2]), "p_value": float(parts[3]),
                            "significant": "Yes" if parts[4].startswith("Yes") else "No",
                        })
                    except (ValueError, IndexError):
                        pass
            if in_cross and line.strip().startswith("共"):
                break
        return pd.DataFrame(rows) if rows else None
    except Exception:
        return None


# ─── Main Entry ─────────────────────────────────────────────────────────────

def generate_summary_report(output_dir: str, x_filter: str = ""):
    """Scan output_dir for factors, generate one HTML summary per factor."""
    root = Path(output_dir)
    factors = _find_factors(root)
    if not factors:
        print("  no factor data found, skipping HTML report")
        return

    generated = []
    for fac in factors:
        path = _build_factor_html(root, fac, x_filter=x_filter)
        if path:
            generated.append(path)

    if generated:
        for p in generated:
            print(f"    {p}")


def _apply_x_filter(df: Optional[pd.DataFrame], x_filter: str,
                    col: str = "x_col") -> Optional[pd.DataFrame]:
    """Filter DataFrame rows where col contains x_filter substring."""
    if not x_filter or df is None or df.empty:
        return df
    return df[df[col].str.contains(x_filter, regex=False)].reset_index(drop=True)


def _build_factor_html(root: Path, fac: Dict, x_filter: str = "") -> Optional[str]:
    name = fac["name"]
    dailyx = fac["dailyx"]

    feval_dir = dailyx / f"{name}_feval"
    pearson_dir = dailyx / f"{name}_pearson"

    has_data = (feval_dir.exists()
                or (dailyx / f"{name}_pearson").exists()
                or (dailyx / f"{name}_deep").exists())
    if not has_data:
        return None

    p = []

    # Header
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    p.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'>")
    p.append(f"<title>{name} Summary</title><style>{_CSS}</style>")
    p.append("<script src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js' async></script>")
    p.append("</head><body><div class='wrap'>")
    p.append(f"<h1>{name}</h1>")
    p.append(f"<p class='m'>generated {now}</p>")

    # Factor logic description
    _add_factor_logic(p, fac, root)

    # Sections
    if feval_dir.exists():
        _add_feval(p, feval_dir, x_filter=x_filter)

    _add_pearson(p, root, name, pearson_dir if pearson_dir.exists() else None,
                 x_filter=x_filter)
    _add_deep(p, root, name, x_filter=x_filter)

    if feval_dir.exists():
        _add_charts(p, feval_dir)

    p.append("</div></body></html>")

    out = root / f"{name}_summary.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write("".join(p))
    return str(out)
