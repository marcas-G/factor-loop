#!/usr/bin/env python3
"""因子日志模块 — 三个 skill 共享。

提供两个日志文件:
  - 因子提交日志.md  (全部三个 skill 写入，详细操作记录)
  - 因子实验日志.md  (factor-evaluate + new-feature-test 写入，简洁结果摘要)

存放目录: ~/factor-logs/
"""

from __future__ import annotations

import fcntl
import os
from datetime import datetime

LOG_DIR = os.path.expanduser("~/factor-logs")
SUBMISSION_LOG = os.path.join(LOG_DIR, "因子提交日志.md")
EXPERIMENT_LOG = os.path.join(LOG_DIR, "因子实验日志.md")


def _ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _time_str() -> str:
    return datetime.now().strftime("%H:%M")


def _get_or_create_log(log_path: str, title: str) -> list[str]:
    """读取已有日志行；若文件不存在则创建并写入标题行。返回行列表。"""
    _ensure_dir()
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n")
        return [f"# {title}", ""]
    with open(log_path, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def _write_lines(log_path: str, lines: list[str]):
    _ensure_dir()
    with open(log_path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write("\n".join(lines) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _find_or_create_date_section(lines: list[str], date: str) -> int:
    """在 lines 中找到 date 对应的 ## section，返回其行号；找不到则返回 -1。"""
    marker = f"## {date}"
    for i, line in enumerate(lines):
        if line.strip() == marker:
            return i
    return -1


def _append_under_section(log_path: str, title: str, date: str, content_lines: list[str]):
    """追加日志内容到指定日期 section 下方。

    如果日期 section 不存在，创建之。
    """
    lines = _get_or_create_log(log_path, title)
    section_idx = _find_or_create_date_section(lines, date)

    if section_idx == -1:
        # 追加新日期 section
        new_lines = [f"\n## {date}\n"] + content_lines
        _write_lines(log_path, new_lines)
    else:
        # 在已有日期 section 下追加
        _write_lines(log_path, content_lines)


# ==================== 提交日志 ====================

def append_submission_log(skill: str, action: str, details: dict):
    """追加到因子提交日志.md。

    Args:
        skill: skill 名称，如 "factor-evaluate", "featuretool", "new-feature-test"
        action: 操作描述，如 "feval评估", "提交", "下载", "残差分析"
        details: 详细信息字典，key 会作为加粗 label
    """
    date = _today_str()
    time = _time_str()

    content = [f"### {time} {skill} ({action})"]
    for k, v in details.items():
        content.append(f"- **{k}**: {v}")
    content.append("")

    _append_under_section(SUBMISSION_LOG, "因子提交日志", date, content)


# ==================== 实验日志 ====================

def append_experiment_log(factor_name: str, best_metric: str, result_path: str,
                          output_dir: str = ""):
    """追加到因子实验日志.md。

    Args:
        factor_name: 因子名称
        best_metric: 最佳指标描述，如 "IC=0.045, ICIR=2.31"
        result_path: 结果目录/文件路径（相对于 output_dir）
        output_dir: 输出根目录（用于生成绝对路径和超链接）
    """
    date = _today_str()
    time = _time_str()

    # 生成绝对路径
    if output_dir and not os.path.isabs(result_path):
        abs_path = os.path.normpath(os.path.join(output_dir, result_path))
    else:
        abs_path = os.path.normpath(result_path)
    abs_path = os.path.expanduser(abs_path)

    # file:// 超链接（支持在 markdown 阅读器中直接点击打开）
    display = os.path.basename(abs_path.rstrip("/"))
    file_link = f"[{display}](file://{abs_path})"

    # 检查今天是否已有表格，如果没有则创建表头
    lines = _get_or_create_log(EXPERIMENT_LOG, "因子实验日志")
    section_idx = _find_or_create_date_section(lines, date)

    table_header = "| 时间 | 因子 | 最佳指标 | 结果路径 |"
    table_sep = "|------|------|----------|----------|"
    row = f"| {time} | {factor_name} | {best_metric} | {file_link} |"

    if section_idx == -1:
        # 新日期 section + 表头 + 行
        content = ["\n## {date}".format(date=date), "", table_header, table_sep, row]
        _write_lines(EXPERIMENT_LOG, content)
    else:
        # 检查今天 section 下是否已有表头
        has_header = False
        for i in range(section_idx, len(lines)):
            if lines[i].strip() == table_header:
                has_header = True
                break
            if lines[i].startswith("## ") and i > section_idx:
                break  # 到了下个 section

        if has_header:
            _write_lines(EXPERIMENT_LOG, [row])
        else:
            _write_lines(EXPERIMENT_LOG, ["", table_header, table_sep, row, ""])
