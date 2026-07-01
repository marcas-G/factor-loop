"""SQLite 因子库访问层（封装 §8.6 API）。

用法:
    from factor_db.db import get_conn, add_factor, add_eval, update_embedding

所有写入都用事务（get_conn 是 contextmanager），调用方负责 with 块边界。
"""

from __future__ import annotations

import json
import sqlite3
import struct
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(__file__).resolve().parent.parent / "factors.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def get_conn(db_path: str | Path = DB_PATH):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _load_vec_extension(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_vec_extension(conn: sqlite3.Connection) -> None:
    """加载 sqlite-vec 扩展（factors_vec 虚拟表需要）。失败时静默——只在写向量时报错。"""
    try:
        import sqlite_vec
        sqlite_vec.load(conn)
    except ImportError:
        pass  # 调用方未装；遇到 vec0 表时会报错，明确告知


# ============ factors ============

VALID_STATUS = {"draft", "submitted", "evaluated", "failed", "dead_end"}


def add_factor(
    conn: sqlite3.Connection,
    xname: str,
    class_name: str | None,
    file_path: str | None,
    formula_text: str | None = None,
    params: dict | None = None,
    status: str = "draft",
    idea_id: int | None = None,
    created_ts: str | None = None,
    skip_if_exists: bool = True,
) -> bool:
    """新增因子。返回 True 表示新增，False 表示已存在跳过。"""
    if status not in VALID_STATUS:
        raise ValueError(f"status must be one of {VALID_STATUS}, got {status!r}")

    if skip_if_exists:
        row = conn.execute("SELECT 1 FROM factors WHERE xname = ?", (xname,)).fetchone()
        if row:
            return False

    conn.execute(
        """
        INSERT OR IGNORE INTO factors
            (xname, class_name, file_path, formula_text, params, status, created_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            xname,
            class_name,
            file_path,
            formula_text,
            json.dumps(params, ensure_ascii=False) if params else None,
            status,
            created_ts,
        ),
    )

    if idea_id is not None:
        conn.execute(
            "INSERT OR IGNORE INTO idea_factor_links (idea_id, factor_xname) VALUES (?, ?)",
            (idea_id, xname),
        )
    return True


def update_factor_formula(
    conn: sqlite3.Connection,
    xname: str,
    formula_text: str,
    description: str | None = None,
    tags: Iterable[str] | None = None,
    category: str | None = None,
    params: dict | None = None,
) -> None:
    """AI 回填阶段用：更新公式/描述/标签/分类/参数，并同步 tags 表。"""
    sets = ["formula_text = ?", "last_updated_ts = CURRENT_TIMESTAMP"]
    vals: list[Any] = [formula_text]

    # formula_text 单独写，description / category / params 进单独列（如存在）
    if category is not None:
        # factors 没有单独 category 列，靠 tags 表达；保留参数以兼容
        pass
    if params is not None:
        sets.append("params = ?")
        vals.append(json.dumps(params, ensure_ascii=False))

    vals.append(xname)
    conn.execute(f"UPDATE factors SET {', '.join(sets)} WHERE xname = ?", vals)

    if tags:
        for tag_name in tags:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
            tag_id = conn.execute(
                "SELECT id FROM tags WHERE name = ?", (tag_name,)
            ).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO factor_tags (factor_xname, tag_id) VALUES (?, ?)",
                (xname, tag_id),
            )


# ============ ideas ============

def add_idea(conn: sqlite3.Connection, text: str, parent_idea_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO ideas (text, parent_idea_id, status) VALUES (?, ?, 'open')",
        (text, parent_idea_id),
    )
    return int(cur.lastrowid)


# ============ factor_evals ============

def add_eval(
    conn: sqlite3.Connection,
    factor_xname: str,
    ts: str,
    metrics: dict,
    symbol: str | None = None,
    freq: str | None = None,
    idea_id: int | None = None,
    mode: str = "full",
    raw_path: str | None = None,
) -> None:
    """新增评估快照 + 更新 factors 冗余字段。"""
    conn.execute(
        """
        INSERT INTO factor_evals
            (factor_xname, idea_id, ts, symbol, freq, ic_mean, icir, sharpe, rank_ic,
             seven_dim, conditional_returns, eval_mode, significant, raw_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            factor_xname, idea_id, ts, symbol, freq,
            metrics.get("ic_mean"), metrics.get("icir"),
            metrics.get("sharpe"), metrics.get("rank_ic"),
            json.dumps(metrics.get("seven_dim"), ensure_ascii=False) if metrics.get("seven_dim") else None,
            json.dumps(metrics.get("conditional_returns"), ensure_ascii=False) if metrics.get("conditional_returns") else None,
            mode, int(bool(metrics.get("significant", False))), raw_path,
        ),
    )
    conn.execute(
        """
        UPDATE factors SET
            latest_ic = ?, latest_icir = ?, latest_sharpe = ?, latest_rank_ic = ?,
            last_updated_ts = ?, status = 'evaluated'
        WHERE xname = ?
        """,
        (
            metrics.get("ic_mean"), metrics.get("icir"),
            metrics.get("sharpe"), metrics.get("rank_ic"),
            ts, factor_xname,
        ),
    )


# ============ iterations ============

def add_iteration(
    conn: sqlite3.Connection,
    from_xname: str,
    to_xname: str,
    idea_id: int | None = None,
    change_note: str | None = None,
    reason: str | None = None,
    outcome: str | None = None,
    icir_delta: float | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO iterations
            (from_xname, to_xname, idea_id, change_note, reason, outcome, icir_delta)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (from_xname, to_xname, idea_id, change_note, reason, outcome, icir_delta),
    )


def get_ancestors(conn: sqlite3.Connection, xname: str) -> list[tuple[str, int]]:
    return conn.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT from_xname AS ancestor, 1 AS depth
            FROM iterations WHERE to_xname = ?
            UNION ALL
            SELECT i.from_xname, c.depth + 1
            FROM iterations i JOIN chain c ON i.to_xname = c.ancestor
        )
        SELECT ancestor, depth FROM chain ORDER BY depth
        """,
        (xname,),
    ).fetchall()


def get_descendants(conn: sqlite3.Connection, xname: str) -> list[tuple[str, int]]:
    return conn.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT to_xname AS descendant, 1 AS depth
            FROM iterations WHERE from_xname = ?
            UNION ALL
            SELECT i.to_xname, c.depth + 1
            FROM iterations i JOIN chain c ON i.from_xname = c.descendant
        )
        SELECT descendant, depth FROM chain ORDER BY depth
        """,
        (xname,),
    ).fetchall()


# ============ lessons ============

VALID_LESSON_TYPE = {"dead_end", "next_direction", "pitfall", "insight", "success_pattern"}
VALID_LESSON_SCOPE = {"global", "idea", "factor"}


def add_lesson(
    conn: sqlite3.Connection,
    type_: str,
    scope: str,
    text: str,
    idea_id: int | None = None,
    factor_xname: str | None = None,
    evidence: dict | None = None,
) -> int:
    if type_ not in VALID_LESSON_TYPE:
        raise ValueError(f"type_ must be {VALID_LESSON_TYPE}, got {type_!r}")
    if scope not in VALID_LESSON_SCOPE:
        raise ValueError(f"scope must be {VALID_LESSON_SCOPE}, got {scope!r}")
    cur = conn.execute(
        """
        INSERT INTO lessons (type, scope, text, evidence, idea_id, factor_xname)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            type_, scope, text,
            json.dumps(evidence, ensure_ascii=False) if evidence else None,
            idea_id, factor_xname,
        ),
    )
    return int(cur.lastrowid)


def search_lessons(
    conn: sqlite3.Connection, query: str, lesson_type: str | None = None, limit: int = 20
) -> list[sqlite3.Row]:
    sql = """
        SELECT l.id, l.type, l.scope, l.text, l.factor_xname, l.idea_id,
               bm25(lessons_fts) AS score
        FROM lessons_fts f JOIN lessons l ON l.rowid = f.rowid
        WHERE lessons_fts MATCH ?
    """
    params: list[Any] = [query]
    if lesson_type:
        sql += " AND l.type = ?"
        params.append(lesson_type)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


# ============ embeddings ============

def update_embedding(conn: sqlite3.Connection, xname: str, embedding: list[float]) -> None:
    blob = struct.pack(f"{len(embedding)}f", *embedding)
    conn.execute(
        "INSERT OR REPLACE INTO factors_vec (xname, embedding) VALUES (?, ?)",
        (xname, blob),
    )
    conn.execute(
        "UPDATE factors SET emb_generated_at = CURRENT_TIMESTAMP WHERE xname = ?",
        (xname,),
    )


def search_similar(
    conn: sqlite3.Connection,
    query_emb: list[float],
    top_k: int = 10,
    status: str | None = None,
    min_icir: float | None = None,
) -> list[sqlite3.Row]:
    """向量查重。query_emb 已 L2 normalize。"""
    blob = struct.pack(f"{len(query_emb)}f", *query_emb)
    sql = """
        SELECT v.xname, v.distance, f.status, f.latest_icir, f.latest_ic, f.formula_text
        FROM factors_vec v JOIN factors f ON f.xname = v.xname
        WHERE v.embedding MATCH ? AND k = ?
    """
    params: list[Any] = [blob, top_k]
    if status:
        sql += " AND f.status = ?"
        params.append(status)
    if min_icir is not None:
        sql += " AND f.latest_icir >= ?"
        params.append(min_icir)
    sql += " AND f.deprecated_at IS NULL ORDER BY v.distance"
    return conn.execute(sql, params).fetchall()
