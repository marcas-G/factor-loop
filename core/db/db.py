"""SQLite 因子库访问层（封装 §8.6 API）。

用法:
    from core.db.db import get_conn, add_factor, add_eval, update_embedding

所有写入都用事务（get_conn 是 contextmanager），调用方负责 with 块边界。
"""

from __future__ import annotations

import json
import re
import sqlite3
import struct
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "factors.db"
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

# angle_code 自动推断(从 formula/tags 关键词 → angle_ontology code)
# 解耦 angle 标注与 explore:所有因子落盘时自动标,不依赖 explore 产 idea 才标
_ANGLE_KEYWORDS = [
    ("imbalance_depth_profile", ["imbalancedepth"]),  # 新自发现角度:per-level imb 向量(优先于 book_imbalance 的宽泛 imbalance)
    ("book_imbalance",       ["imbalance", "imb", "bsi", "ofi"]),
    ("add_cancel_imbalance", ["cancel_imb", "add_imb", "add_cancel_imb"]),
    ("add_cancel_pattern",   ["spoof", "layering", "cancel_pattern", "add_pattern"]),
    ("depth_shape",          ["depth_shape", "entropy", "skew", "hhi", "conc"]),
    ("depth_slope",          ["depth_slope", "book_slope", "slope"]),
    ("spread_structure",     ["spread", "bid_ask_spread"]),
    ("trade_imbalance",      ["trade_imb", "volume_imb", "tvi"]),
    ("trade_rhythm",         ["hawkes", "burst", "rhythm", "cluster"]),
    ("intensity_level",      ["intensity", "turnover", "active"]),
    ("volatility_regime",    ["vol_regime", "volatility", "vol_gate", "volregime", "vol burst", "vol regime"]),
    ("price_microstructure", ["microstructure", "roll", "autocorr"]),
    ("oi_anomaly",           ["oi_", "oi ", "open_interest", "oipersist", "oiresist", "oispike", "oiintensity"]),
]


def infer_angle_code(formula_text: str | None, tags: Iterable[str] | None,
                     xname: str | None = None) -> str | None:
    """从 formula/tags/xname 推断 angle_code。不依赖 explore 标注。

    与 factor-db.mjs inferAngleCode 双端一致。
    """
    text = " ".join(filter(None, [
        (formula_text or "").lower(),
        " ".join(tags or []).lower(),
        (xname or "").lower(),
    ]))
    for code, keywords in _ANGLE_KEYWORDS:
        if any(kw in text for kw in keywords):
            return code
    return None


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
    tags: Iterable[str] | None = None,
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
        VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
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
        # angle_code 回灌(优先 idea.angle_code 血缘,次 DERIVES_FROM properties.angle 兜底):
        a = conn.execute(
            "SELECT angle_code FROM ideas WHERE id=?", (idea_id,)
        ).fetchone()
        if not (a and a[0]):
            a = conn.execute(
                """SELECT json_extract(properties,'$.angle') FROM graph_edges
                   WHERE from_id=? AND edge_type='DERIVES_FROM'
                     AND json_extract(properties,'$.angle') IS NOT NULL LIMIT 1""",
                (str(idea_id),),
            ).fetchone()
        if a and a[0]:
            conn.execute(
                "UPDATE factors SET angle_code=? WHERE xname=?", (a[0], xname)
            )
    # angle_code 自动推断(解耦 explore):idea 无 angle 或无 idea 时,从 formula/xname 推断
    cur_angle = conn.execute(
        "SELECT angle_code FROM factors WHERE xname=?", (xname,)
    ).fetchone()
    if not (cur_angle and cur_angle[0]):
        inferred = infer_angle_code(formula_text, tags, xname)
        if inferred:
            conn.execute(
                "UPDATE factors SET angle_code=? WHERE xname=?", (inferred, xname)
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
    status: str | None = None,
) -> None:
    """新增评估快照 + 更新 factors 冗余字段。

    status: 强制设 factors.status("evaluated"/"dead_end")。None = 不动 status(仅更新最新指标)。
    (对齐 mjs addEval 语义:pass 传 evaluated, fail 传 dead_end, 不传则不碰 status。)
    """
    conn.execute(
        """
        INSERT INTO factor_evals
            (factor_xname, idea_id, ts, symbol, freq, ic_mean, icir, sharpe, rank_ic,
             eval_metrics, conditional_returns, eval_mode, significant, raw_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            factor_xname, idea_id, ts, symbol, freq,
            metrics.get("ic_mean"), metrics.get("icir"),
            metrics.get("sharpe"), metrics.get("rank_ic"),
            json.dumps(metrics.get("eval_metrics"), ensure_ascii=False) if metrics.get("eval_metrics") else None,
            json.dumps(metrics.get("conditional_returns"), ensure_ascii=False) if metrics.get("conditional_returns") else None,
            mode, int(bool(metrics.get("significant", False))), raw_path,
        ),
    )
    if status is not None:
        if status not in VALID_STATUS:
            raise ValueError(f"status must be {VALID_STATUS}, got {status!r}")
        conn.execute(
            """
            UPDATE factors SET
                latest_ic = ?, latest_icir = ?, latest_sharpe = ?, latest_rank_ic = ?,
                last_updated_ts = ?, status = ?
            WHERE xname = ?
            """,
            (
                metrics.get("ic_mean"), metrics.get("icir"),
                metrics.get("sharpe"), metrics.get("rank_ic"),
                ts, status, factor_xname,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE factors SET
                latest_ic = ?, latest_icir = ?, latest_sharpe = ?, latest_rank_ic = ?,
                last_updated_ts = ?
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
    # status='realized' 过滤:排除 open/in_progress 的自指占位(to=from),防递归 CTE 无限循环
    return conn.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT from_xname AS ancestor, 1 AS depth
            FROM iterations WHERE to_xname = ? AND status = 'realized'
            UNION ALL
            SELECT i.from_xname, c.depth + 1
            FROM iterations i JOIN chain c ON i.to_xname = c.ancestor AND i.status = 'realized'
        )
        SELECT ancestor, depth FROM chain ORDER BY depth
        """,
        (xname,),
    ).fetchall()


def get_descendants(conn: sqlite3.Connection, xname: str) -> list[tuple[str, int]]:
    # status='realized' 过滤:排除 open/in_progress 的自指占位(to=from),防递归 CTE 无限循环
    return conn.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT to_xname AS descendant, 1 AS depth
            FROM iterations WHERE from_xname = ? AND status = 'realized'
            UNION ALL
            SELECT i.to_xname, c.depth + 1
            FROM iterations i JOIN chain c ON i.from_xname = c.descendant AND i.status = 'realized'
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
    if not factor_xname:
        raise ValueError("lesson 必须绑 factor_xname")
    evidence_json = json.dumps(evidence, ensure_ascii=False) if evidence else None

    # 幂等:同 (factor_xname, idea_id, type) 已有 → UPDATE 最新一条;否则 INSERT。
    # (对齐 mjs addLesson:避免重复 lesson 堆积。)
    if idea_id is None:
        existing = conn.execute(
            """SELECT id FROM lessons
               WHERE factor_xname = ? AND idea_id IS NULL AND type = ?
               ORDER BY created_ts DESC LIMIT 1""",
            (factor_xname, type_),
        ).fetchone()
    else:
        existing = conn.execute(
            """SELECT id FROM lessons
               WHERE factor_xname = ? AND idea_id = ? AND type = ?
               ORDER BY created_ts DESC LIMIT 1""",
            (factor_xname, idea_id, type_),
        ).fetchone()

    if existing:
        conn.execute(
            """UPDATE lessons SET text = ?, evidence = ?, created_ts = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (text, evidence_json, existing[0]),
        )
        return int(existing[0])

    cur = conn.execute(
        """
        INSERT INTO lessons (type, scope, text, evidence, idea_id, factor_xname)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            type_, scope, text,
            evidence_json,
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
    # vec0 虚拟表不支持 INSERT OR REPLACE(撞主键报 UNIQUE 而非替换),先 DELETE 再 INSERT
    conn.execute("DELETE FROM factors_vec WHERE xname = ?", (xname,))
    conn.execute(
        "INSERT INTO factors_vec (xname, embedding) VALUES (?, ?)",
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


# ============ 知识图（axioms / graph_edges）============
# 分层知识图：AXIOM(axioms表) → DERIVED/HYPOTHESIS(ideas表) → EVIDENCE/REFUTATION(lessons/factors)。
# graph_edges 跨表软引用 (from_table, from_id)。from_id: factors 存 xname，其余存 integer id 字符串。

VALID_EDGE_TYPES = {
    "CONTRADICTS", "DERIVES_FROM", "INSTANTIATES",
    "SPECIALIZES", "ORTHOGONAL_TO", "SUPPORTS", "REFUTES", "BOUNDS",
}
# 节点表 → 主键列名（from_id/to_id 存该列的值）
NODE_PK = {
    "axioms": "id",
    "ideas": "id",
    "factors": "xname",        # TEXT 主键
    "lessons": "id",
}

_GRAPH_CONSTANTS = None


def graph_constants() -> dict:
    """加载共享图常量(判据/阈值)。db.py 与 factor-db.mjs 共读 core/db/graph_constants.json
    → 判据一处,防双端漂移(has_resolved / 饱和度阈值等)。"""
    global _GRAPH_CONSTANTS
    if _GRAPH_CONSTANTS is None:
        _GRAPH_CONSTANTS = json.loads(
            (Path(__file__).resolve().parent / "graph_constants.json").read_text(encoding="utf-8")
        )
    return _GRAPH_CONSTANTS


def _ensure_graph_tables(conn: sqlite3.Connection) -> None:
    """建 axioms/graph_edges 表(幂等)。migrations v2 graph_core 的表部分。
    新库由 schema.sql 直建；此函数给老库在线补齐。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS axioms (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL, statement TEXT NOT NULL, formal_form TEXT,
            expected_signature TEXT, source TEXT, falsifiable TEXT,
            created_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS graph_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_table TEXT NOT NULL, from_id TEXT NOT NULL,
            to_table TEXT NOT NULL, to_id TEXT NOT NULL,
            edge_type TEXT NOT NULL CHECK (edge_type IN
                ('CONTRADICTS','DERIVES_FROM','INSTANTIATES','SPECIALIZES',
                 'ORTHOGONAL_TO','SUPPORTS','REFUTES','BOUNDS')),
            weight REAL, properties TEXT,
            created_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_table, from_id, to_table, to_id, edge_type)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_from ON graph_edges(from_table, from_id);
        CREATE INDEX IF NOT EXISTS idx_edges_to   ON graph_edges(to_table, to_id);
        CREATE INDEX IF NOT EXISTS idx_edges_type ON graph_edges(edge_type);
        """
    )


# ideas 必然假设字段：schema.sql ideas 表已全含；此映射给老库在线补列，对齐 mjs migrateIdeasSchema。
# py 端此前缺此迁移（双端漂移点），阶段2 schema 版本化补齐。
_IDEAS_NECESSITY_FIELDS = {
    "node_layer":               "TEXT DEFAULT 'HYPOTHESIS'",
    "argument_chain":           "TEXT",
    "support_score":            "REAL",
    "evaluated_factor_count":   "INTEGER NOT NULL DEFAULT 0",
    "support_score_computed_at": "TIMESTAMP",
    "necessity_grade":          "TEXT",
}


def ensure_ideas_necessity_fields(conn: sqlite3.Connection) -> None:
    """补 ideas 必然假设字段(幂等,PRAGMA 检查 + ALTER ADD)。migrations v2 的列部分。
    对齐 mjs migrateIdeasSchema——py 端此前缺此迁移,阶段2 补齐消双端漂移。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ideas)")}
    if not cols:
        return  # ideas 表不存在(全新库,schema.sql 尚未跑),跳过
    for col, decl in _IDEAS_NECESSITY_FIELDS.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE ideas ADD COLUMN {col} {decl}")


def ensure_graph_schema(conn: sqlite3.Connection) -> None:
    """对现有库幂等补齐知识图表结构(= migrations v2 graph_core + v3 bounds + v4 angle)。
    新库由 schema.sql 直接建；此函数给已存在的库做在线迁移。向后兼容,调用方不变。"""
    _ensure_graph_tables(conn)
    ensure_ideas_necessity_fields(conn)
    migrate_graph_edge_bounds(conn)
    ensure_angle_schema(conn)


def add_axiom(
    conn: sqlite3.Connection,
    code: str,
    category: str,
    statement: str,
    formal_form: str | None = None,
    expected_signature: dict | str | None = None,
    source: str | None = None,
    falsifiable: str | None = None,
) -> int:
    """写一条公理。code 唯一，重复则返回已有 id（幂等）。"""
    existing = conn.execute("SELECT id FROM axioms WHERE code = ?", (code,)).fetchone()
    if existing:
        return int(existing[0])
    es = (
        expected_signature
        if isinstance(expected_signature, str)
        else (json.dumps(expected_signature, ensure_ascii=False) if expected_signature else None)
    )
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO axioms
            (code, category, statement, formal_form, expected_signature, source, falsifiable)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (code, category, statement, formal_form, es, source, falsifiable),
    )
    return int(cur.lastrowid) if cur.lastrowid else int(
        conn.execute("SELECT id FROM axioms WHERE code = ?", (code,)).fetchone()[0]
    )


def add_graph_node(conn: sqlite3.Connection, table: str, data: dict) -> int:
    """写节点:table='axioms'→add_axiom;table='ideas'→带 argument_chain/necessity_grade/node_layer 的 idea。
    与 factor-db.mjs addGraphNode 对称(graph-engine G4 落盘用)。"""
    if table == "axioms":
        return add_axiom(conn, **data)
    if table == "ideas":
        chain = data.get("argument_chain")
        if chain is not None and not isinstance(chain, str):
            chain = json.dumps(chain, ensure_ascii=False)
        cur = conn.execute(
            "INSERT INTO ideas (text, parent_idea_id, status, argument_chain, necessity_grade, node_layer, angle_code) "
            "VALUES (?, ?, 'open', ?, ?, ?, ?)",
            (data.get("text"), data.get("parent_idea_id"), chain,
             data.get("necessity_grade"), data.get("node_layer", "HYPOTHESIS"),
             data.get("angle_code")),
        )
        return int(cur.lastrowid)
    raise ValueError(f"add_graph_node 不支持表: {table}")


def add_graph_edge(
    conn: sqlite3.Connection,
    from_table: str,
    from_id,
    to_table: str,
    to_id,
    edge_type: str,
    weight: float | None = None,
    properties: dict | None = None,
) -> int | None:
    """写一条图边。幂等（UNIQUE 约束，重复返回已有 id）。from_id/to_id 接受 str/int。"""
    if edge_type not in VALID_EDGE_TYPES:
        raise ValueError(f"edge_type must be {VALID_EDGE_TYPES}, got {edge_type!r}")
    _NODE_PK = ("axioms", "ideas", "factors", "lessons")
    if from_table not in _NODE_PK:
        raise ValueError(f"from_table must be in {_NODE_PK}, got {from_table!r}")
    if to_table not in _NODE_PK:
        raise ValueError(f"to_table must be in {_NODE_PK}, got {to_table!r}")
    # 节点存在性校验(防 LLM 写不存在的 xname/id,留孤儿边)
    _PK = {"axioms": "id", "ideas": "id", "factors": "xname", "lessons": "id"}
    if not conn.execute(f"SELECT 1 FROM {from_table} WHERE {_PK[from_table]}=?", (str(from_id),)).fetchone():
        raise ValueError(f"from 节点 {from_table}:{from_id} 不存在")
    if not conn.execute(f"SELECT 1 FROM {to_table} WHERE {_PK[to_table]}=?", (str(to_id),)).fetchone():
        raise ValueError(f"to 节点 {to_table}:{to_id} 不存在")
    props = json.dumps(properties, ensure_ascii=False) if properties else None
    existing = conn.execute(
        """
        SELECT id FROM graph_edges
        WHERE from_table=? AND from_id=? AND to_table=? AND to_id=? AND edge_type=?
        """,
        (from_table, str(from_id), to_table, str(to_id), edge_type),
    ).fetchone()
    if existing:
        return int(existing[0])
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO graph_edges
            (from_table, from_id, to_table, to_id, edge_type, weight, properties)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (from_table, str(from_id), to_table, str(to_id), edge_type, weight, props),
    )
    return int(cur.lastrowid) if cur.lastrowid else None


def _node_row(conn: sqlite3.Connection, table: str, node_id) -> sqlite3.Row | None:
    """取节点完整行（按表主键）。"""
    pk = NODE_PK.get(table)
    if not pk:
        return None
    return conn.execute(
        f"SELECT * FROM {table} WHERE {pk} = ?", (str(node_id),)
    ).fetchone()


def query_contradictions(
    conn: sqlite3.Connection, resolved: bool = False, axiom_code: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """查 CONTRADICTS 边。resolved=False 返回未解矛盾（resolve_contradiction 输入）。
    resolved 判据：properties JSON 含 resolved_by。"""
    has_resolved = graph_constants()["resolved_clause"]
    where = f"ge.edge_type='CONTRADICTS' AND {'NOT' if not resolved else ''} ({has_resolved})"
    params: list[Any] = []
    if axiom_code:
        where += " AND a.code = ?"
        params.append(axiom_code)
    rows = conn.execute(
        f"""
        SELECT ge.id AS edge_id, ge.weight, ge.properties,
               a.id AS axiom_id, a.code AS axiom_code, a.statement, a.formal_form, a.expected_signature
        FROM graph_edges ge
        JOIN axioms a ON a.id = ge.to_id AND ge.to_table='axioms'
        WHERE {where}
        ORDER BY COALESCE(ge.weight, 0) DESC LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "edge_id": r["edge_id"], "weight": r["weight"], "properties": r["properties"],
            "evidence": None,
            "axiom": {"id": r["axiom_id"], "code": r["axiom_code"], "statement": r["statement"],
                      "formal_form": r["formal_form"], "expected_signature": r["expected_signature"]},
        })
    return out


def get_subgraph(
    conn: sqlite3.Connection, table: str, node_id, depth: int = 2,
    edge_types: list[str] | None = None, limit: int = 200,
) -> dict:
    """取以某节点为中心、depth 跳内的子图（BFS）。返回 {center, nodes, edges}。"""
    et_filter = ""
    params: list[Any] = []
    if edge_types:
        placeholders = ",".join("?" * len(edge_types))
        et_filter = f" AND edge_type IN ({placeholders})"
        params = list(edge_types)

    center = _node_row(conn, table, node_id)
    nodes: dict[tuple[str, str], dict] = {}
    edges: list[dict] = []
    if center:
        nodes[(table, str(node_id))] = {"table": table, "id": str(node_id),
                                         "depth": 0, "fields": dict(center)}
    frontier = [(table, str(node_id))]
    for d in range(1, depth + 1):
        if not frontier:
            break
        placeholders = ",".join(
            f"(from_table=? AND from_id=?)" for _ in frontier
        ) + " OR " + " OR ".join(
            f"(to_table=? AND to_id=?)" for _ in frontier
        )
        flat: list[Any] = []
        for ft, fid in frontier:
            flat += [ft, fid]
        for ft, fid in frontier:
            flat += [ft, fid]
        rows = conn.execute(
            f"""
            SELECT from_table, from_id, to_table, to_id, edge_type, weight, properties
            FROM graph_edges WHERE ({placeholders}){et_filter} LIMIT ?
            """,
            flat + params + [limit],
        ).fetchall()
        next_frontier: list[tuple[str, str]] = []
        for r in rows:
            edges.append(dict(r))
            for side in [("from_table", "from_id"), ("to_table", "to_id")]:
                t, i = r[side[0]], str(r[side[1]])
                key = (t, i)
                if key not in nodes:
                    row = _node_row(conn, t, i)
                    if row:
                        nodes[key] = {"table": t, "id": i, "depth": d, "fields": dict(row)}
                        next_frontier.append(key)
        frontier = next_frontier
    return {"center": {"table": table, "id": str(node_id)},
            "nodes": list(nodes.values()), "edges": edges}


def neighborhood(
    conn: sqlite3.Connection, table: str, node_id,
    edge_types: list[str] | None = None, direction: str = "both", limit: int = 10,
) -> list[dict]:
    """取某节点 1 跳邻居。direction: out/in/both。"""
    et_filter = ""
    params: list[Any] = []
    clauses = []
    if direction in ("out", "both"):
        clauses.append("(from_table=? AND from_id=?)")
        params += [table, str(node_id)]
    if direction in ("in", "both"):
        clauses.append("(to_table=? AND to_id=?)")
        params += [table, str(node_id)]
    where = " OR ".join(clauses)
    if edge_types:
        placeholders = ",".join("?" * len(edge_types))
        et_filter = f" AND edge_type IN ({placeholders})"
        params += list(edge_types)
    rows = conn.execute(
        f"""
        SELECT from_table, from_id, to_table, to_id, edge_type, weight, properties
        FROM graph_edges WHERE ({where}){et_filter} LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    out = []
    for r in rows:
        is_from = r["from_table"] == table and str(r["from_id"]) == str(node_id)
        nb_t, nb_i = (r["to_table"], str(r["to_id"])) if is_from else (r["from_table"], str(r["from_id"]))
        nb = _node_row(conn, nb_t, nb_i)
        out.append({
            "neighbor_table": nb_t, "neighbor_id": nb_i,
            "edge_type": r["edge_type"], "weight": r["weight"],
            "direction": "out" if is_from else "in",
            "fields": dict(nb) if nb else None,
        })
    return out


def find_refutation_clusters(
    conn: sqlite3.Connection, target_table: str | None = None, target_id=None,
    min_size: int = 3, limit: int = 5,
) -> list[dict]:
    """找 REFUTES/SUPPORTS 边指向同一目标的聚簇（generalize_from_refutation 输入）。"""
    where = "edge_type IN ('REFUTES','SUPPORTS') AND to_table IN ('axioms','ideas')"
    params: list[Any] = []
    if target_table:
        where += " AND to_table = ?"
        params.append(target_table)
    if target_id is not None:
        where += " AND to_id = ?"
        params.append(str(target_id))
    rows = conn.execute(
        f"""
        SELECT to_table, to_id, edge_type, COUNT(*) AS sz
        FROM graph_edges WHERE {where}
        GROUP BY to_table, to_id, edge_type HAVING sz >= ?
        ORDER BY sz DESC LIMIT ?
        """,
        params + [min_size, limit],
    ).fetchall()
    out = []
    for r in rows:
        members = conn.execute(
            """SELECT from_table, from_id FROM graph_edges
               WHERE to_table=? AND to_id=? AND edge_type=?""",
            (r["to_table"], r["to_id"], r["edge_type"]),
        ).fetchall()
        target = _node_row(conn, r["to_table"], r["to_id"])
        out.append({
            "target_table": r["to_table"], "target_id": r["to_id"],
            "edge_type": r["edge_type"], "size": r["sz"],
            "target": dict(target) if target else None,
            "members": [dict(m) for m in members],
        })
    return out


def graph_stats(conn: sqlite3.Connection) -> dict:
    """图统计：各层节点数、各边类型数、未解矛盾数。自转循环停止条件用。"""
    def count(sql, args=()):
        return conn.execute(sql, args).fetchone()[0]
    return {
        "axioms": count("SELECT COUNT(*) FROM axioms"),
        "derived": count(
            "SELECT COUNT(*) FROM ideas WHERE node_layer='DERIVED'"
        ),
        "hypothesis": count(
            "SELECT COUNT(*) FROM ideas WHERE node_layer='HYPOTHESIS' OR node_layer IS NULL"
        ),
        "evidence_lessons": count(
            "SELECT COUNT(*) FROM lessons WHERE type='success_pattern' AND deprecated_at IS NULL"
        ),
        "refutation_lessons": count(
            "SELECT COUNT(*) FROM lessons WHERE type='dead_end' AND deprecated_at IS NULL"
        ),
        "edges_by_type": {
            r[0]: r[1] for r in conn.execute(
                "SELECT edge_type, COUNT(*) FROM graph_edges GROUP BY edge_type"
            )
        },
        "total_edges": count("SELECT COUNT(*) FROM graph_edges"),
        "unresolved_contradictions": count(
            f"SELECT COUNT(*) FROM graph_edges WHERE edge_type='CONTRADICTS' "
            f"AND NOT ({graph_constants()['resolved_clause']})"
        ),
    }


def mark_contradiction_resolved(
    conn: sqlite3.Connection, edge_id: int, idea_id: int,
) -> None:
    """标记 CONTRADICTS 边已由某 idea 解决（properties 加 resolved_by）。"""
    row = conn.execute(
        "SELECT properties FROM graph_edges WHERE id = ?", (edge_id,)
    ).fetchone()
    try:
        props = json.loads(row["properties"]) if row and row["properties"] else {}
    except Exception:
        props = {}
    props["resolved_by"] = idea_id
    conn.execute(
        "UPDATE graph_edges SET properties = ? WHERE id = ?",
        (json.dumps(props, ensure_ascii=False), edge_id),
    )


def mark_contradiction_bounded(
    conn: sqlite3.Connection, edge_id: int, regime: str, reason: str,
) -> None:
    """标记 CONTRADICTS 边为「axiom 边界限定」(否定性结论:axiom 在此 regime 不完备,
    产不出必然正命题)。properties 加 resolution='bounded' + regime + reason。
    与 mark_contradiction_resolved 对称:resolved=肯定解决(产 idea),bounded=否定解决(axiom 证伪)。
    bounded 后该矛盾不再算 unresolved(不再被反复选中 resolve)。"""
    row = conn.execute(
        "SELECT properties FROM graph_edges WHERE id = ?", (edge_id,)
    ).fetchone()
    try:
        props = json.loads(row["properties"]) if row and row["properties"] else {}
    except Exception:
        props = {}
    props["resolution"] = "bounded"
    props["regime"] = regime
    props["reason"] = reason
    conn.execute(
        "UPDATE graph_edges SET properties = ? WHERE id = ?",
        (json.dumps(props, ensure_ascii=False), edge_id),
    )


def migrate_graph_edge_bounds(conn: sqlite3.Connection) -> None:
    """graph_edges.edge_type CHECK 加 'BOUNDS'(SQLite 不能改 CHECK,需重建表)。幂等。
    新库由 schema.sql 直接建(已含 BOUNDS);旧库由此函数重建迁移。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_edges'"
    ).fetchone()
    if not row or not row["sql"] or "BOUNDS" in row["sql"]:
        return  # 表不存在 或 已含 BOUNDS
    conn.executescript(
        """
        CREATE TABLE graph_edges_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_table TEXT NOT NULL, from_id TEXT NOT NULL,
            to_table TEXT NOT NULL, to_id TEXT NOT NULL,
            edge_type TEXT NOT NULL CHECK (edge_type IN
                ('CONTRADICTS','DERIVES_FROM','INSTANTIATES','SPECIALIZES',
                 'ORTHOGONAL_TO','SUPPORTS','REFUTES','BOUNDS')),
            weight REAL, properties TEXT,
            created_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_table, from_id, to_table, to_id, edge_type)
        );
        INSERT INTO graph_edges_new (id,from_table,from_id,to_table,to_id,edge_type,weight,properties,created_ts)
        SELECT id,from_table,from_id,to_table,to_id,edge_type,weight,properties,created_ts FROM graph_edges;
        DROP TABLE graph_edges;
        ALTER TABLE graph_edges_new RENAME TO graph_edges;
        CREATE INDEX IF NOT EXISTS idx_edges_from ON graph_edges(from_table, from_id);
        CREATE INDEX IF NOT EXISTS idx_edges_to   ON graph_edges(to_table, to_id);
        CREATE INDEX IF NOT EXISTS idx_edges_type ON graph_edges(edge_type);
        """
    )


# ============ 信息角度元层（angle_ontology + factors.angle_code）============
# 数据→信息角度字典。让 graph-engine 感知"哪些角度饱和、哪些未探索",自动换角度。

def ensure_angle_schema(conn: sqlite3.Connection) -> None:
    """建 angle_ontology 表 + factors.angle_code 列。幂等。"""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS angle_ontology (
            code          TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            field_family  TEXT NOT NULL,
            extraction    TEXT NOT NULL,
            signal_target TEXT,
            theory_axiom  TEXT,
            description   TEXT
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_angle_family ON angle_ontology(field_family)")
    fcols = {r[1] for r in conn.execute("PRAGMA table_info(factors)")}
    if "angle_code" not in fcols:
        conn.execute("ALTER TABLE factors ADD COLUMN angle_code TEXT")


def add_angle(
    conn: sqlite3.Connection, code: str, name: str, field_family: str, extraction: str,
    signal_target: str | None = None, theory_axiom: str | None = None, description: str | None = None,
) -> None:
    """写一条信息角度(幂等,code 主键)。"""
    conn.execute(
        """INSERT OR IGNORE INTO angle_ontology
           (code,name,field_family,extraction,signal_target,theory_axiom,description)
           VALUES (?,?,?,?,?,?,?)""",
        (code, name, field_family, extraction, signal_target, theory_axiom, description),
    )


def tag_factor_angle(conn: sqlite3.Connection, xname: str, angle_code: str) -> None:
    """标注因子所属信息角度。"""
    conn.execute("UPDATE factors SET angle_code=? WHERE xname=?", (angle_code, xname))


def query_angle_coverage(conn: sqlite3.Connection) -> list[dict]:
    """每角度的探索状态:因子数/dead_end/evaluated/最高icir/饱和度。explore_uncovered_angle 的输入。

    饱和度启发:saturated=因子≥5且dead_end占≥60%; thin=因子≤2; unexplored=0因子且0 idea; partial=其余。
    saturation 把 idea 占用算进去:有 idea(方向已推理触及)但无 factor → partial(非 explore fresh),
    避免 graph 反复往"假 fresh"角度派 explore 产同方向对偶命题。"""
    rows = conn.execute(
        """
        SELECT a.code, a.name, a.field_family, a.extraction, a.signal_target, a.theory_axiom,
               COUNT(f.xname) AS n_factors,
               COALESCE(SUM(CASE WHEN f.status='dead_end' THEN 1 ELSE 0 END),0) AS n_dead_end,
               COALESCE(SUM(CASE WHEN f.status='evaluated' THEN 1 ELSE 0 END),0) AS n_evaluated,
               (SELECT COUNT(*) FROM ideas i WHERE i.angle_code = a.code) AS n_ideas,
               MAX(f.latest_icir) AS max_icir
        FROM angle_ontology a
        LEFT JOIN factors f ON f.angle_code = a.code AND f.deprecated_at IS NULL
        GROUP BY a.code, a.name, a.field_family, a.extraction, a.signal_target, a.theory_axiom
        ORDER BY n_factors ASC
        """
    ).fetchall()
    out = []
    for r in rows:
        n, nd, ni = r["n_factors"], r["n_dead_end"], r["n_ideas"] or 0
        sc = graph_constants()["saturation"]
        if n == 0 and ni == 0:
            sat = "unexplored"
        elif n == 0 and ni > 0:
            sat = "partial"
        elif n >= sc["min_n_saturated"] and nd >= n * sc["dead_ratio_saturated"]:
            sat = "saturated"
        elif n <= sc["max_n_thin"]:
            sat = "thin"
        else:
            sat = "partial"
        out.append({
            "code": r["code"], "name": r["name"], "field_family": r["field_family"],
            "extraction": r["extraction"], "signal_target": r["signal_target"],
            "theory_axiom": r["theory_axiom"], "n_factors": n, "n_dead_end": nd,
            "n_evaluated": r["n_evaluated"], "n_ideas": ni, "max_icir": r["max_icir"], "saturation": sat,
        })
    return out


# ============ 操作选择（3 操作数据驱动打分）============
# 操作层只 3 个: generalize(归纳) / fill(维护) / explore(拓展)
# orthogonal/generalize_refutation/success 是方法论层(graph-reasoner 推理时自选)
# 打分 = trigger_strength(从图状态连续计算) × diversity_bonus(防垄断)
# 无魔数 if-else,纯数据驱动。

# normalize 分母(scale 参数,非魔数):聚簇 10 个/空节 5 个 = trigger 满分
_CLUSTER_SCALE = 10.0
_GAP_SCALE = 5.0
# diversity 惩罚系数:最近占比 100% → 降权 70%
_DIV_PENALTY = 0.7


def query_recent_operations(conn: sqlite3.Connection, n: int = 10) -> list[str]:
    """最近 N 个 idea 的产生操作(DERIVES_FROM 边 properties.via)→ 操作层归类。
    方法论级 via(generalize_from_refutation 等)归一到操作级(generalize)。"""
    OP_MAP = {
        "generalize_from_refutation": "generalize",
        "generalize_from_success": "generalize",
        "refutation_correction": "generalize",
        "orthogonal_branch": "generalize",
        "fill_chain_gap": "fill",
        "explore_uncovered_angle": "explore",
        "resolve_contradiction": "generalize",
        "trace_verification": "generalize",
    }
    rows = conn.execute(
        """SELECT json_extract(properties,'$.via') AS via FROM graph_edges
           WHERE edge_type='DERIVES_FROM' AND json_extract(properties,'$.via') IS NOT NULL
           ORDER BY id DESC LIMIT ?""", (n,)
    ).fetchall()
    return [OP_MAP.get(r[0], r[0]) for r in rows if r[0]]


def _count_fill_gaps(conn: sqlite3.Connection) -> int:
    """客观空节数:background_axioms 引用不存在 axiom + competing<2。SQL 可查。"""
    import json as _json
    axcodes = {r[0] for r in conn.execute("SELECT code FROM axioms")}
    idea_ids = {str(r[0]) for r in conn.execute("SELECT id FROM ideas")}
    n = 0
    for r in conn.execute(
        "SELECT id, argument_chain FROM ideas WHERE node_layer='DERIVED' AND argument_chain IS NOT NULL"
    ).fetchall():
        ch = _json.loads(r[1])
        for a in (ch.get("background_axioms") or []):
            if a not in axcodes and a not in idea_ids:
                n += 1
        comp = ch.get("competing_explanations") or []
        if len(comp) < 2:
            n += 1
    return n


def _max_angle_cluster(conn: sqlite3.Connection) -> int:
    """同 angle_code 的 dead_end 因子最大数(angle 聚簇大小)。"""
    row = conn.execute(
        """SELECT MAX(n) FROM (
              SELECT COUNT(*) n FROM factors
              WHERE status='dead_end' AND deprecated_at IS NULL AND angle_code IS NOT NULL
              GROUP BY angle_code
           )"""
    ).fetchone()
    return int(row[0]) if row and row[0] else 0


def select_graph_operation(conn: sqlite3.Connection) -> dict:
    """3 操作数据驱动打分:score = trigger × diversity,无魔数 if-else。

    操作层(3 个):
      generalize(归纳): 从图里案例(反例/成功/混合)归纳新假设
      fill(维护):       补已有论证链客观空节
      explore(拓展):    往未探索角度产种子

    方法论层(graph-reasoner 推理时自选,不在此打分):
      全dead_end→反例归纳 / 有pass→成功归纳或正交展开 / 混合→对比归纳
    """
    coverage = query_angle_coverage(conn)
    recent = query_recent_operations(conn, 10)

    n_fresh = sum(1 for a in coverage if a["saturation"] in ("unexplored", "thin"))
    n_saturated = sum(1 for a in coverage if a["saturation"] == "saturated")
    total = max(len(coverage), 1)

    # ===== trigger strength(连续,从图状态算) =====
    # generalize: max(idea 聚簇, angle 聚簇) / scale
    idea_clusters = find_refutation_clusters(conn, min_size=3, limit=5)
    max_idea_cluster = max((cl["size"] for cl in idea_clusters), default=0)
    max_angle_cluster = _max_angle_cluster(conn)
    max_cluster = max(max_idea_cluster, max_angle_cluster)

    n_gaps = _count_fill_gaps(conn)

    trigger = {
        "generalize": min(1.0, max_cluster / _CLUSTER_SCALE),
        "fill":       min(1.0, n_gaps / _GAP_SCALE),
        "explore":    (n_fresh / total) * (n_saturated / total),
        # angle_discovery:explore 卡(nFresh==0)+ 饱和多 → 该发现新角度,突破预定义语言边界
        "angle_discovery": (n_saturated / total) if n_fresh == 0 else 0.0,
    }

    # ===== diversity bonus(连续,防垄断) =====
    scores = {}
    for op in trigger:
        ratio = recent.count(op) / max(len(recent), 1) if recent else 0
        diversity = 1.0 - ratio * _DIV_PENALTY
        scores[op] = round(trigger[op] * diversity, 3)

    best = max(scores, key=scores.get)
    return {
        "recommended": best,
        "score": scores[best],
        "scores": scores,
        "trigger": {k: round(v, 3) for k, v in trigger.items()},
        "max_cluster": max_cluster,
        "n_gaps": n_gaps,
        "n_fresh": n_fresh,
        "n_saturated": n_saturated,
        "recent_operations": recent,
        "fresh_angles": sorted(a["code"] for a in coverage if a["saturation"] in ("unexplored", "thin")),
        "saturated_angles": sorted(a["code"] for a in coverage if a["saturation"] == "saturated"),
    }


# ============ schema 版本追踪（schema_version 表读写原语）============
# 版本链定义在 core/db/migrations.py（CURRENT_VERSION + MIGRATIONS）。
# 这里只提供低级读写：建表 / 读当前版本 / 记一个版本。migrate(conn) 编排用。

def ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    """建 schema_version 表(幂等)。新库由 schema.sql 直建,此函数给老库补。"""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )


def current_schema_version(conn: sqlite3.Connection) -> int:
    """读当前 schema 版本。无 schema_version 表或空 = 0(史前库)。"""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return 0  # 表不存在
    return int(row[0]) if row and row[0] is not None else 0


def record_schema_version(conn: sqlite3.Connection, version: int, name: str) -> None:
    """记录一个迁移版本(幂等:INSERT OR IGNORE)。"""
    ensure_schema_version_table(conn)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, name) VALUES (?, ?)",
        (version, name),
    )


# ============ 质量聚合分(方案1 加权线性 + 固定阈值归一 + 方案4 等级) ============
# Gate(ICIR≥1.5 + 成本后正 + 忠实 + 不否决)过门槛后,按独立性+稳定性加权。
# ICIR 只作门槛不进分(边际递减)。固定阈值归一(不依赖库分布,新因子不动别人分)。
# stability 用 deep_best 的 monthly_icir + signal_instability(core_metrics 历史全 null)。

def ensure_quality_fields(conn: sqlite3.Connection) -> None:
    """补 factors.quality_score/quality_grade 列(幂等)。v6 quality_fields。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(factors)")}
    if "quality_score" not in cols:
        conn.execute("ALTER TABLE factors ADD COLUMN quality_score REAL")
    if "quality_grade" not in cols:
        conn.execute("ALTER TABLE factors ADD COLUMN quality_grade TEXT")


def ensure_intuition_field(conn: sqlite3.Connection) -> None:
    """补 factors.intuition 列(语义意图描述,研究用)。v7 intuition_field。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(factors)")}
    if "intuition" not in cols:
        conn.execute("ALTER TABLE factors ADD COLUMN intuition TEXT")


def ensure_anchor_text_field(conn: sqlite3.Connection) -> None:
    """补 factors.anchor_text 列(embedding 锚定文本,固定四要素模板生成)。v8 anchor_text。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(factors)")}
    if "anchor_text" not in cols:
        conn.execute("ALTER TABLE factors ADD COLUMN anchor_text TEXT")


def ensure_cohort_meta_fields(conn: sqlite3.Connection) -> None:
    """补 factors cohort 元数据列(Phase 2.1 operator_planner 冻结 cohort 因子专用)。v13 cohort_meta。

    spec §3：A/B 入 factors 表保留血缘 + 冻结 hash。普通因子这些列 NULL（不影响）。
    幂等：PRAGMA 检查列存在才 ALTER。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(factors)")}
    additions = {
        "origin_type": "TEXT",
        "cohort_tag": "TEXT",
        "need_id": "TEXT",
        "plan_id": "TEXT",
        "program_id": "TEXT",
        "operator_chain": "TEXT",
        "field_bindings": "TEXT",
        "parameter_hash": "TEXT",
        "kernel_hash": "TEXT",
        "decision_available_at": "TIMESTAMP",
        "evaluation_status": "TEXT",
        "posterior_search_forbidden": "INTEGER",
    }
    for col, decl in additions.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE factors ADD COLUMN {col} {decl}")


def ensure_angle_candidates_table(conn: sqlite3.Connection) -> None:
    """建 angle_candidates 表(angle 自发现候选记录,防归纳循环)。v9 angle_candidates。"""
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "angle_candidates" not in tabs:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS angle_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
                field_family TEXT, extraction TEXT, signal_target TEXT, theory_axiom TEXT,
                description TEXT, novelty_argument TEXT, trigger_angle TEXT,
                status TEXT NOT NULL CHECK(status IN ('proposed','accepted','rejected')),
                reject_reason TEXT, nearest_existing TEXT,
                tried_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ac_status ON angle_candidates(status)")


def add_angle_candidate(conn, *, code, field_family=None, extraction=None, signal_target=None,
                        theory_axiom=None, description=None, novelty_argument=None,
                        trigger_angle=None, status="proposed") -> int:
    """写一条 angle 自发现候选(proposed),返回 id。"""
    cur = conn.execute(
        """INSERT INTO angle_candidates
           (code, field_family, extraction, signal_target, theory_axiom, description,
            novelty_argument, trigger_angle, status)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (code, field_family, extraction, signal_target, theory_axiom, description,
         novelty_argument, trigger_angle, status),
    )
    return int(cur.lastrowid)


def update_angle_candidate(conn, candidate_id: int, *, status: str,
                           reject_reason: str | None = None,
                           nearest_existing: str | None = None) -> None:
    """更新候选状态(accept→accepted / reject→rejected + reason)。"""
    conn.execute(
        """UPDATE angle_candidates SET status=?, reject_reason=?, nearest_existing=? WHERE id=?""",
        (status, reject_reason, nearest_existing, candidate_id),
    )


def list_angle_candidates(conn, status: str | None = None) -> list[sqlite3.Row]:
    """列候选(可按 status 过滤)。meta-angle-discoverer 查 rejected 防循环用。"""
    if status:
        return conn.execute(
            "SELECT * FROM angle_candidates WHERE status=? ORDER BY tried_at DESC", (status,)
        ).fetchall()
    return conn.execute("SELECT * FROM angle_candidates ORDER BY tried_at DESC").fetchall()


def ensure_ideas_angle_code(conn: sqlite3.Connection) -> None:
    """补 ideas.angle_code 列(信息角度血缘)。v10。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ideas)")}
    if "angle_code" not in cols:
        conn.execute("ALTER TABLE ideas ADD COLUMN angle_code TEXT")


def ensure_iterations_columns(conn: sqlite3.Connection) -> None:
    """补 iterations.status/iterable 列(迭代建议状态机)。
    v11 iterations_status_iterable。与 runtime migrateIterationsSchema 对齐——
    schema.sql 新库已含,此函数给既有 Python 库经 migrate 补列(JS 侧靠 init 兜底,py 侧原本漏)。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(iterations)")}
    if not cols:
        return  # 表不存在(全新库待 schema.sql 建),跳过
    if "status" not in cols:
        conn.execute("ALTER TABLE iterations ADD COLUMN status TEXT NOT NULL DEFAULT 'realized'")
    if "iterable" not in cols:
        conn.execute("ALTER TABLE iterations ADD COLUMN iterable INTEGER NOT NULL DEFAULT 1")


def ensure_operators_library(conn: sqlite3.Connection) -> None:
    """v12 算子库：operators（算子主体）+ operator_family_edges（撞族边界）+ iterations.op_id。
    算子 = 从因子故事抽取的可复用测量方法（主体，定义纯抽象）。
    因子 = 算子的应用实例（iterations.op_id：在故事节点 from 上用算子 op 产出 to）。
    撞族边界 = 算子×基底类型→撞族（复用/发明的避让依据）。
    schema.sql 新库已含 operators/operator_family_edges 表 + iterations.op_id 列；
    此函数给既有 Python 库幂等补建。"""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # operators 表
    if "operators" not in tables:
        conn.execute("""
            CREATE TABLE operators (
                op_id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name               TEXT NOT NULL UNIQUE,
                definition         TEXT NOT NULL,
                input_roles        TEXT,
                abstract_structure TEXT,
                direction_property TEXT CHECK(direction_property IN ('INVARIANT','EQUIVARIANT','PAIRED')),
                source             TEXT,
                source_ref         TEXT,
                created_ts         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    # operator_family_edges 表
    if "operator_family_edges" not in tables:
        conn.execute("""
            CREATE TABLE operator_family_edges (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                op_id       INTEGER NOT NULL,
                base_type   TEXT NOT NULL,
                family      TEXT,
                pearson     REAL,
                residual    REAL,
                tested_on   TEXT,
                verdict     TEXT CHECK(verdict IN ('outside_closure','inside_closure','untested')),
                note        TEXT,
                ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (op_id)     REFERENCES operators(op_id),
                FOREIGN KEY (tested_on)  REFERENCES factors(xname)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ofe_op   ON operator_family_edges(op_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ofe_base ON operator_family_edges(base_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ofe_fam  ON operator_family_edges(family)")
    # iterations.op_id 列
    iter_cols = {r[1] for r in conn.execute("PRAGMA table_info(iterations)")}
    if iter_cols and "op_id" not in iter_cols:
        conn.execute("ALTER TABLE iterations ADD COLUMN op_id INTEGER REFERENCES operators(op_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_iter_op ON iterations(op_id)")


def ensure_factor_structure_table(conn: sqlite3.Connection) -> None:
    """v14 factor_structure 表(因子结构指纹, R3 查重主体)。

    双源提取(避免 C++ 完整 AST 成本黑洞):
      - 源1 frontmatter formula 伪代码归一化 → canonical_hash/template_hash
      - 源2 C++ 静态扫描 → field_signature/operator_primitives/complexity
    xname 与 factors.xname 对齐,但不强 FK(含未入库 Base/Probe 锚点)。
    schema.sql 新库直建;此函数给既有库幂等补建。"""
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "factor_structure" not in tabs:
        conn.execute("""
            CREATE TABLE factor_structure (
                xname              TEXT PRIMARY KEY,
                canonical_text     TEXT,
                canonical_hash     TEXT,
                template_hash      TEXT,
                tree_depth         INTEGER,
                node_count         INTEGER,
                field_signature    TEXT,
                operator_primitives TEXT,
                complexity         TEXT,
                source_formula     TEXT,
                source_file        TEXT,
                extracted_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX idx_fs_canonical_hash ON factor_structure(canonical_hash)")
        conn.execute("CREATE INDEX idx_fs_template_hash  ON factor_structure(template_hash)")
        conn.execute("CREATE INDEX idx_fs_complexity     ON factor_structure(complexity)")


def ensure_retrieval_tables(conn: sqlite3.Connection) -> None:
    """v15 检索层派生表:R1/R2/R3/R4 检索 Contract 的数据基础。

    5 张:
      - factor_operator_usage  R3 operator 通道(因子×算子交叉)
      - operator_capability_index + operator_capability_vec  R2 算子能力索引(SQL 过滤+vec rerank)
      - factor_research_state  R1 因子研究态(被研究次数/exhaustion)
      - factor_evidence_rollup  R4 + S1 IC 聚合(替代逐日 IC JOIN)
      - library_map VIEW  R1 全库覆盖聚合
    """
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "factor_operator_usage" not in tabs:
        conn.execute("""
            CREATE TABLE factor_operator_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                xname TEXT NOT NULL, op_id INTEGER, op_role TEXT,
                use_count INTEGER DEFAULT 1, note TEXT,
                UNIQUE(xname, op_id, op_role)
            )
        """)
        conn.execute("CREATE INDEX idx_fou_xname ON factor_operator_usage(xname)")
        conn.execute("CREATE INDEX idx_fou_opid  ON factor_operator_usage(op_id)")
    if "operator_capability_index" not in tabs:
        conn.execute("""
            CREATE TABLE operator_capability_index (
                op_id INTEGER PRIMARY KEY, op_name TEXT,
                carrier_type TEXT, measurement_object TEXT, measurement_property TEXT,
                input_role_signature TEXT, output_role TEXT,
                temporal_requirement TEXT, cross_section_requirement TEXT,
                pair_requirement TEXT, observable_requirements TEXT,
                invariance TEXT,
                updated_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX idx_oci_carrier  ON operator_capability_index(carrier_type)")
        conn.execute("CREATE INDEX idx_oci_object  ON operator_capability_index(measurement_object)")
        conn.execute("CREATE INDEX idx_oci_temporal ON operator_capability_index(temporal_requirement)")
    # operator_capability_vec(vec0 虚拟表,768 维 bge-small embedding)
    vec_tabs = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%vec0%'"
    )}
    if "operator_capability_vec" not in vec_tabs:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE operator_capability_vec USING vec0("
                "op_id INTEGER PRIMARY KEY, embedding FLOAT[768])"
            )
        except sqlite3.OperationalError:
            pass  # sqlite-vec 未加载,跳过(查询时降级)
    if "factor_research_state" not in tabs:
        conn.execute("""
            CREATE TABLE factor_research_state (
                xname TEXT PRIMARY KEY,
                times_selected INTEGER NOT NULL DEFAULT 0,
                last_selected_ts TIMESTAMP,
                cognitive_attempts INTEGER NOT NULL DEFAULT 0,
                contradicticts_count INTEGER NOT NULL DEFAULT 0,
                consistent_count INTEGER NOT NULL DEFAULT 0,
                insufficient_count INTEGER NOT NULL DEFAULT 0,
                out_of_domain_count INTEGER NOT NULL DEFAULT 0,
                factor_iteration_count INTEGER NOT NULL DEFAULT 0,
                operator_gap_count INTEGER NOT NULL DEFAULT 0,
                new_operator_count INTEGER NOT NULL DEFAULT 0,
                successful_child_count INTEGER NOT NULL DEFAULT 0,
                dead_end_child_count INTEGER NOT NULL DEFAULT 0,
                open_idea_count INTEGER NOT NULL DEFAULT 0,
                research_exhaustion_score REAL NOT NULL DEFAULT 0.0,
                last_outcome TEXT,
                last_updated_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX idx_frs_exhaustion ON factor_research_state(research_exhaustion_score)")
        conn.execute("CREATE INDEX idx_frs_last_sel   ON factor_research_state(last_selected_ts)")
    if "factor_evidence_rollup" not in tabs:
        conn.execute("""
            CREATE TABLE factor_evidence_rollup (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_xname TEXT NOT NULL, symbol TEXT, freq TEXT, y_horizon INTEGER,
                slice_type TEXT NOT NULL CHECK(slice_type IN ('FULL','RECENT','YEAR','SYMBOL','REGIME','FEED')),
                slice_key TEXT, n INTEGER,
                ic_mean REAL, ic_std REAL, icir REAL, positive_ratio REAL,
                ic_median REAL, ic_q10 REAL, ic_q90 REAL,
                start_date TEXT, end_date TEXT, source_eval_id INTEGER,
                computed_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(factor_xname, symbol, freq, y_horizon, slice_type, slice_key)
            )
        """)
        conn.execute("CREATE INDEX idx_fer_factor ON factor_evidence_rollup(factor_xname)")
        conn.execute("CREATE INDEX idx_fer_scene  ON factor_evidence_rollup(symbol, freq, y_horizon)")
    # library_map VIEW
    views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    if "library_map" not in views:
        conn.execute("""
            CREATE VIEW library_map AS
            SELECT
                f.status AS status, f.angle_code AS angle_code,
                COALESCE(fs.complexity, 'unknown') AS structure_family,
                COUNT(DISTINCT f.xname) AS total_factors,
                COUNT(DISTINCT CASE WHEN f.status='dead_end' THEN f.xname END) AS dead_end_count,
                COUNT(DISTINCT CASE WHEN f.status='evaluated' THEN f.xname END) AS evaluated_count,
                COUNT(DISTINCT l_de.id) AS dead_end_lesson_count,
                COUNT(DISTINCT l_su.id) AS success_lesson_count
            FROM factors f
            LEFT JOIN factor_structure fs ON fs.xname = f.xname
            LEFT JOIN lessons l_de ON l_de.factor_xname=f.xname AND l_de.type='dead_end' AND l_de.deprecated_at IS NULL
            LEFT JOIN lessons l_su ON l_su.factor_xname=f.xname AND l_su.type='success_pattern' AND l_su.deprecated_at IS NULL
            WHERE f.deprecated_at IS NULL
            GROUP BY f.status, f.angle_code, COALESCE(fs.complexity, 'unknown')
        """)


def _map_monthly_icir(x: float | None) -> float:
    """monthly_icir 固定阈值归一(不依赖库)。≥2→1, ≥1→0.7, ≥0.5→0.4, ≥0.2→0.2, 否则0。"""
    if x is None:
        return 0.3  # 缺数据中性
    if x >= 2.0:
        return 1.0
    if x >= 1.0:
        return 0.7
    if x >= 0.5:
        return 0.4
    if x >= 0.2:
        return 0.2
    return 0.0


def _map_ic_std(x: float | None) -> float:
    """session IC std 固定阈值归一(低好,跨时段平稳)。"""
    if x is None:
        return 0.3
    if x < 0.0005:
        return 1.0
    if x < 0.001:
        return 0.7
    if x < 0.002:
        return 0.4
    return 0.0


def quality_score_from_parts(
    independence: float | None,
    train_test: dict | None,
    monthly_icir: float | None,
    signal_instability_pct: float | None,
    session_ic_std: float | None,
    vol_regime_sign_consistent: bool | None,
) -> tuple[float, str]:
    """多指标聚合分(方案1 加权线性)+等级(方案4)。固定阈值归一,从质量出发。

    independence: residual_ic_strength(0-1,vs 库内基底残差,高=真新颖不冗余)。
    train_test: {decay, same_sign} 样本外衰减——**防过拟合核心**。
    monthly_icir / signal_instability_pct / session_ic_std: 时间稳定(deep_best + core_metrics)。
    vol_regime_sign_consistent: 跨波动 regime 符号一致(regime 鲁棒)。
    返回 (score 0-1, grade A≥0.7 / B 0.4-0.7 / C<0.4)。

    stability = 0.4×样本(train_test,防过拟合) + 0.4×时间(monthly+std+signal) + 0.2×regime
    样本维最关键:符号反(same_sign=False)→过拟合/反转,直接 0 分。
    """
    ind = max(0.0, min(independence or 0.0, 1.0))
    # 样本稳定(防过拟合)
    decay = train_test.get("decay") if isinstance(train_test, dict) else None
    same_sign = train_test.get("same_sign") if isinstance(train_test, dict) else None
    if same_sign is False:
        sample_stab = 0.0  # 样本内外符号反→过拟合/反转,重罚
    elif decay is None:
        sample_stab = 0.3
    else:
        sample_stab = max(0.0, 1.0 - (decay or 3.0) / 3.0)  # decay 0→1(无衰减), 3→0
    # 时间稳定
    month_consist = _map_monthly_icir(monthly_icir)
    ic_std_stab = _map_ic_std(session_ic_std)
    signal_stab = 1.0 - min((signal_instability_pct or 50.0) / 100.0, 1.0)
    time_stab = 0.4 * month_consist + 0.4 * ic_std_stab + 0.2 * signal_stab
    # regime 稳定
    regime_stab = 1.0 if vol_regime_sign_consistent else 0.0
    stability = 0.4 * sample_stab + 0.4 * time_stab + 0.2 * regime_stab
    score = 0.5 * ind + 0.5 * stability
    grade = "A" if score >= 0.7 else ("B" if score >= 0.4 else "C")
    return round(score, 3), grade


# ═══════════════════════════════════════════════════════════════════════════
# 以下函数从 runtime/lib/factor-db.mjs 吸收(B 类:原 mjs 有、db.py 无)。
# 换 python 后 mjs 删除,这些是 MCP tool handler 直接调用的唯一实现。
# ═══════════════════════════════════════════════════════════════════════════

def _trigram_tokens(text: str, limit: int = 12) -> list[str]:
    """把自然语言切成 trigram 列表(FTS5 trigram 分词器友好),去重,最多 limit 个。
    (对齐 mjs searchFactors/searchLessons 的 trigram 逻辑。)"""
    cleaned = re.sub(r"\s+", "", text or "")
    tokens: list[str] = []
    seen: set[str] = set()
    for i in range(len(cleaned) - 2):
        t = cleaned[i:i + 3]
        if t not in seen:
            tokens.append(t)
            seen.add(t)
            if len(tokens) >= limit:
                break
    return tokens


def _trigram_match_query(text: str, limit: int = 12) -> str | None:
    """自然语言 → FTS5 trigram match 串(`"tok1" OR "tok2" ...`)。"""
    tokens = _trigram_tokens(text, limit)
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


def _days_since(ts) -> float:
    """距今多少天(UTC 天)。ts 可为 str(datetime)。无法解析 → +inf。"""
    if not ts:
        return float("inf")
    s = str(ts).strip().replace(" ", "T")
    if not re.search(r"[zZ]$|[+-]\d\d:?\d\d$", s):
        s += "Z"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return float("inf")


# ============ 因子状态/查询 ============

def update_factor_status(conn: sqlite3.Connection, xname: str, status: str) -> None:
    if status not in VALID_STATUS:
        raise ValueError(f"status must be {VALID_STATUS}, got {status!r}")
    conn.execute(
        "UPDATE factors SET status = ?, last_updated_ts = CURRENT_TIMESTAMP WHERE xname = ?",
        (status, xname),
    )


def factor_exists(conn: sqlite3.Connection, xname: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM factors WHERE xname = ?", (xname,)).fetchone())


def count_factors(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM factors").fetchone()["n"])


def count_lessons(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM lessons").fetchone()["n"])


def count_evaluated(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM factors WHERE status='evaluated'").fetchone()["n"])


def recent_lessons(conn: sqlite3.Connection, k: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, type, scope, text, idea_id, factor_xname, created_ts "
        "FROM lessons ORDER BY id DESC LIMIT ?", (k,),
    ).fetchall()


def recent_factors(conn: sqlite3.Connection, k: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT xname, class_name, status, latest_ic, latest_icir, last_updated_ts "
        "FROM factors ORDER BY last_updated_ts DESC LIMIT ?", (k,),
    ).fetchall()


def search_factors(conn: sqlite3.Connection, query: str, k: int = 10) -> list[sqlite3.Row]:
    """FTS5 全文检索 factors(formula/class_name),trigram 分词中文友好。"""
    q = (query or "").strip()
    if len(q) < 3:
        return recent_factors(conn, k)
    match = _trigram_match_query(q)
    if not match:
        return recent_factors(conn, k)
    return conn.execute(
        """SELECT f.xname, f.class_name, f.status, f.latest_icir, f.formula_text,
                  bm25(factors_fts) AS score
           FROM factors_fts ft JOIN factors f ON f.rowid = ft.rowid
           WHERE factors_fts MATCH ? ORDER BY score LIMIT ?""",
        (match, k),
    ).fetchall()


def ensure_formula_tags(conn: sqlite3.Connection, xname: str, formula: str | None, tags: list[str] | None) -> None:
    """兜底:若 factors.formula_text 为空则补;tags 逐个绑定(幂等)。
    用于 persistVerdict 在 .h 无 frontmatter 时保证三件套不缺。"""
    if not xname:
        return
    if formula:
        row = conn.execute("SELECT formula_text FROM factors WHERE xname = ?", (xname,)).fetchone()
        if row and row["formula_text"] is None:
            conn.execute(
                "UPDATE factors SET formula_text = ?, last_updated_ts = CURRENT_TIMESTAMP WHERE xname = ?",
                (formula, xname),
            )
    for t in tags or []:
        if t:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (str(t),))
            tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (str(t),)).fetchone()
            if tag_id:
                conn.execute(
                    "INSERT OR IGNORE INTO factor_tags (factor_xname, tag_id) VALUES (?, ?)",
                    (xname, tag_id["id"]),
                )


def add_lessons(conn: sqlite3.Connection, lessons: list[dict], idea_id: int | None = None) -> list[int]:
    """批量写 lesson(逐条 try/except,跳过无效条目)。返回写入的 lesson id 列表。"""
    ids = []
    for l in lessons or []:
        try:
            ids.append(add_lesson(
                conn,
                type_=l["type"],
                scope="factor",
                text=l["text"],
                idea_id=l.get("idea_id") or idea_id,
                factor_xname=l["xname"],
                evidence=l.get("evidence"),
            ))
        except Exception:
            pass  # 无效条目跳过(对齐 mjs addLessons 逐条容错)
    return ids


# ============ 迭代状态机(open→in_progress→realized / reopen 回滚) ============

def open_iteration(
    conn: sqlite3.Connection,
    from_xname: str,
    idea_id: int | None = None,
    change_note: str | None = None,
    reason: str | None = None,
    iterable: bool = True,
) -> int:
    """开 open suggestion。同 (from, change) 已 open/in_progress → 幂等返回已有 id。"""
    existing = conn.execute(
        """SELECT id FROM iterations
           WHERE from_xname = ? AND change_note IS ? AND status IN ('open','in_progress')
           ORDER BY ts DESC LIMIT 1""",
        (from_xname, change_note),
    ).fetchone()
    if existing:
        return int(existing["id"])
    cur = conn.execute(
        """INSERT INTO iterations (from_xname, to_xname, idea_id, change_note, reason, status, iterable)
           VALUES (?, ?, ?, ?, ?, 'open', ?)""",
        (from_xname, from_xname, idea_id, change_note, reason, 1 if iterable else 0),  # to 自指占位
    )
    return int(cur.lastrowid)


def claim_iteration(conn: sqlite3.Connection, iter_id: int) -> dict:
    """open→in_progress(接续候选 B 时)。非 open 不可 claim。"""
    row = conn.execute("SELECT status FROM iterations WHERE id = ?", (iter_id,)).fetchone()
    if not row:
        raise ValueError(f"iteration id 不存在: {iter_id}")
    if row["status"] != "open":
        return {"ok": False, "error": f"iteration {iter_id} 状态={row['status']},非 open 不可 claim"}
    conn.execute("UPDATE iterations SET status = 'in_progress' WHERE id = ?", (iter_id,))
    return {"ok": True}


def realize_iteration(conn: sqlite3.Connection, iter_id: int, to_xname: str, icir_delta: float | None = None) -> dict:
    """in_progress→realized(B 已入库后)。填真实 to_xname + outcome(由 icir_delta 推导)。"""
    row = conn.execute("SELECT status FROM iterations WHERE id = ?", (iter_id,)).fetchone()
    if not row:
        raise ValueError(f"iteration id 不存在: {iter_id}")
    if row["status"] != "in_progress":
        return {"ok": False, "error": f"iteration {iter_id} 状态={row['status']},非 in_progress 不可 realize"}
    if icir_delta is None:
        outcome = "neutral"
    elif icir_delta > 0.02:
        outcome = "improved"
    elif icir_delta < -0.02:
        outcome = "declined"
    else:
        outcome = "neutral"
    conn.execute(
        "UPDATE iterations SET status = 'realized', to_xname = ?, outcome = ?, icir_delta = ? WHERE id = ?",
        (to_xname, outcome, icir_delta, iter_id),
    )
    return {"ok": True, "outcome": outcome}


def reopen_iteration(conn: sqlite3.Connection, iter_id: int) -> dict:
    """失败回滚:in_progress→open(允许下次再接续)。"""
    row = conn.execute("SELECT status FROM iterations WHERE id = ?", (iter_id,)).fetchone()
    if not row:
        raise ValueError(f"iteration id 不存在: {iter_id}")
    if row["status"] != "in_progress":
        return {"ok": False, "error": f"iteration {iter_id} 状态={row['status']},非 in_progress 不可 reopen"}
    conn.execute("UPDATE iterations SET status = 'open' WHERE id = ?", (iter_id,))
    return {"ok": True}


def list_open_iterations(conn: sqlite3.Connection, top_k: int = 5, source_status: str | None = None) -> list[sqlite3.Row]:
    """检索待接续 open 建议,按 priority 降序。
    priority = (evaluated?2.0:0.5) × exp(-age/14):pass 精进优先,老建议降权。"""
    sql = """SELECT i.id AS suggestion_id, i.from_xname, i.change_note, i.reason, i.idea_id, i.iterable, i.ts,
                    f.status AS from_status, f.latest_icir AS from_icir, f.formula_text AS from_formula,
                    (CASE WHEN f.status = 'evaluated' THEN 2.0 ELSE 0.5 END)
                      * EXP(-(julianday('now') - julianday(i.ts)) / 14.0) AS priority
             FROM iterations i JOIN factors f ON f.xname = i.from_xname
             WHERE i.status = 'open'"""
    params: list[Any] = []
    if source_status:
        sql += " AND f.status = ?"
        params.append(source_status)
    sql += " ORDER BY priority DESC LIMIT ?"
    params.append(top_k)
    return conn.execute(sql, params).fetchall()


# ============ 假设 / 发现(ideas + 论证链) ============

def add_hypothesis(
    conn: sqlite3.Connection,
    text: str,
    argument_chain: dict | None = None,
    parent_idea_id: int | None = None,
    necessity_grade: str | None = None,
    angle_code: str | None = None,
) -> int:
    """写 idea + 结构化论证链(argument_chain)。论证链是假设的属性,不是因子的。"""
    chain = json.dumps(argument_chain, ensure_ascii=False) if argument_chain is not None else None
    cur = conn.execute(
        """INSERT INTO ideas (text, parent_idea_id, status, argument_chain, necessity_grade, angle_code)
           VALUES (?, ?, 'open', ?, ?, ?)""",
        (text, parent_idea_id, chain, necessity_grade, angle_code),
    )
    return int(cur.lastrowid)


def get_hypothesis(conn: sqlite3.Connection, idea_id: int) -> sqlite3.Row | None:
    """取假设的论证链 + 分级(reviewer-agent 审稿 / 忠实度判定读用)。"""
    return conn.execute(
        """SELECT id, text, argument_chain, necessity_grade, support_score, evaluated_factor_count, status
           FROM ideas WHERE id = ?""",
        (idea_id,),
    ).fetchone()


def update_idea_support_score(conn: sqlite3.Connection, idea_id: int, k: int = 1) -> dict:
    """聚合假设支持度(贝叶斯平滑 (pass+k)/(total+2k),不绝对判断)。"""
    if idea_id is None:
        return {"ok": False, "error": "ideaId 为空"}
    rows = conn.execute(
        """SELECT f.status FROM idea_factor_links l
           JOIN factors f ON f.xname = l.factor_xname
           WHERE l.idea_id = ? AND f.status IN ('evaluated','dead_end')""",
        (idea_id,),
    ).fetchall()
    total = len(rows)
    n_pass = sum(1 for r in rows if r["status"] == "evaluated")
    score = None if total == 0 else (n_pass + k) / (total + 2 * k)
    conn.execute(
        """UPDATE ideas SET support_score = ?, evaluated_factor_count = ?,
           support_score_computed_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (score, total, idea_id),
    )
    return {"ok": True, "idea_id": idea_id, "pass": n_pass, "total": total, "score": score}


def discover_failed_hypotheses(
    conn: sqlite3.Connection, max_score: float = 0.4, min_evaluated: int = 2, limit: int = 10,
) -> list[sqlite3.Row]:
    """扫失效假设(support_score 低 + 已评估够多)——下一轮反常的原料。"""
    return conn.execute(
        """SELECT id, text, support_score, evaluated_factor_count, necessity_grade
           FROM ideas
           WHERE support_score IS NOT NULL AND support_score < ? AND evaluated_factor_count >= ?
           ORDER BY support_score ASC LIMIT ?""",
        (max_score, min_evaluated, limit),
    ).fetchall()


def discover_recent_dead_ends(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    """最近 dead_end lessons(避雷 + 失效回喂)。"""
    return conn.execute(
        "SELECT id, text, factor_xname, idea_id, created_ts FROM lessons "
        "WHERE type = 'dead_end' ORDER BY created_ts DESC LIMIT ?",
        (limit,),
    ).fetchall()


# ============ 覆盖地图(coverage map) ============

_COVERAGE_AXES = {
    "symbol": "m.symbol",
    "y_horizon": "m.y_horizon",
    "status": "f.status",
    "necessity_grade": "i.necessity_grade",
}
_DEFAULT_COVERAGE_AXES = ["symbol", "y_horizon", "status", "necessity_grade"]
_COVERAGE_STALE_DAYS = 60


def coverage_map(
    conn: sqlite3.Connection,
    slice_: dict | None = None,
    group_by: list[str] | None = None,
    min_count: int = 0,
) -> list[dict]:
    """覆盖张量切片。每格 gap_tags ∈ thin|hot|stale|normal(可叠加)。
    thin=试过≤3且0评估成功; hot=evaluated≥1且avg_icir>全库均值; stale=最近评估>60天。"""
    slice_ = slice_ or {}
    axes = [a for a in (group_by or _DEFAULT_COVERAGE_AXES) if a in _COVERAGE_AXES] or _DEFAULT_COVERAGE_AXES
    select_cols = ", ".join(f"{_COVERAGE_AXES[a]} AS {a}" for a in axes)
    group_cols = ", ".join(_COVERAGE_AXES[a] for a in axes)

    where, params = [], []
    for a in _COVERAGE_AXES:
        if a in slice_ and slice_[a] is not None:
            where.append(f"{_COVERAGE_AXES[a]} = ?")
            params.append(slice_[a])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    having_sql = ""
    if min_count > 0:
        having_sql = "HAVING COUNT(DISTINCT f.xname) >= ?"
        params.append(min_count)

    rows = conn.execute(f"""
        SELECT {select_cols},
               COUNT(DISTINCT f.xname) AS searched_count,
               COUNT(DISTINCT CASE WHEN f.status='evaluated' THEN f.xname END) AS evaluated_count,
               COUNT(DISTINCT CASE WHEN f.status='dead_end' THEN f.xname END) AS dead_end_count,
               AVG(f.latest_icir) AS avg_icir,
               MAX(m.computed_at) AS last_evaluated_ts
        FROM factor_ic_vec_meta m
        JOIN factors f ON f.xname = m.factor_xname
        LEFT JOIN factor_evals e2 ON e2.id = (
            SELECT id FROM factor_evals WHERE factor_xname = f.xname ORDER BY ts DESC LIMIT 1
        )
        LEFT JOIN ideas i ON i.id = e2.idea_id
        {where_sql}
        GROUP BY {group_cols}
        {having_sql}
        ORDER BY searched_count DESC
    """, params).fetchall()

    med = conn.execute(
        "SELECT AVG(latest_icir) AS a FROM factors WHERE status='evaluated' AND latest_icir IS NOT NULL"
    ).fetchone()
    median_icir = (med["a"] or 0) if med else 0

    result = []
    for r in rows:
        d = dict(r)
        tags = []
        if d["searched_count"] <= 3 and d["evaluated_count"] == 0:
            tags.append("thin")
        if d["evaluated_count"] >= 1 and d["avg_icir"] is not None and d["avg_icir"] > median_icir and d["avg_icir"] > 0:
            tags.append("hot")
        if _days_since(d["last_evaluated_ts"]) > _COVERAGE_STALE_DAYS:
            tags.append("stale")
        if not tags:
            tags.append("normal")
        d["gap_tags"] = tags
        result.append(d)
    return result


def coverage_gaps(conn: sqlite3.Connection, top_k: int = 5) -> dict:
    """覆盖空白/热点队列:unexplored/thin/hot/stale 各取 top_k,带 suggestion 文本。"""
    unexplored = conn.execute("""
        SELECT m.symbol, m.y_horizon, i.necessity_grade,
               COUNT(DISTINCT f.xname) AS searched_count,
               COUNT(DISTINCT CASE WHEN f.status='evaluated' THEN f.xname END) AS evaluated_count
        FROM factor_ic_vec_meta m
        JOIN factors f ON f.xname = m.factor_xname
        LEFT JOIN factor_evals e2 ON e2.id = (
            SELECT id FROM factor_evals WHERE factor_xname = f.xname ORDER BY ts DESC LIMIT 1
        )
        LEFT JOIN ideas i ON i.id = e2.idea_id
        GROUP BY m.symbol, m.y_horizon, i.necessity_grade
        HAVING evaluated_count = 0
        ORDER BY searched_count DESC LIMIT ?
    """, (top_k,)).fetchall()

    unexplored_list = [{
        "symbol": r["symbol"], "y_horizon": r["y_horizon"], "necessity_grade": r["necessity_grade"],
        "searched_count": r["searched_count"], "evaluated_count": r["evaluated_count"],
        "gap_tag": "unexplored",
        "suggestion": f"{r['symbol'] or '?'} × h={r['y_horizon'] if r['y_horizon'] is not None else '?'}s "
                      f"× {r['necessity_grade'] or 'any'} 维度空白(试过 {r['searched_count']} 个均无 evaluated),值得冷启动探索",
    } for r in unexplored]

    cells = coverage_map(conn)

    def pick(tag: str) -> list[dict]:
        out = []
        for c in cells:
            if tag in c["gap_tags"]:
                out.append({
                    "symbol": c.get("symbol"), "y_horizon": c.get("y_horizon"),
                    "status": c.get("status"), "necessity_grade": c.get("necessity_grade"),
                    "searched_count": c.get("searched_count"), "evaluated_count": c.get("evaluated_count"),
                    "avg_icir": c.get("avg_icir"), "last_evaluated_ts": c.get("last_evaluated_ts"),
                    "gap_tag": tag,
                    "suggestion": (
                        f"{c.get('symbol') or '?'} × h={c.get('y_horizon') if c.get('y_horizon') is not None else '?'}s "
                        f"高效热点(avg_icir={(c.get('avg_icir') or 0):.3f}),值得在该格继续变异"
                        if tag == "hot" else
                        f"{c.get('symbol') or '?'} × h={c.get('y_horizon') if c.get('y_horizon') is not None else '?'}s "
                        f"× {c.get('status')} 欠探索({c.get('searched_count')} 个试过 0 评估成功),换轴或弃"
                        if tag == "thin" else
                        f"{c.get('symbol') or '?'} × h={c.get('y_horizon') if c.get('y_horizon') is not None else '?'}s "
                        f"该格 {round(_days_since(c.get('last_evaluated_ts')))} 天没动,可能 drift,待复验"
                    ),
                })
                if len(out) >= top_k:
                    break
        return out

    return {"unexplored": unexplored_list, "thin": pick("thin"), "hot": pick("hot"), "stale": pick("stale")}


# ============ 单因子详情 / 相似 ============

def get_factor_detail(conn: sqlite3.Connection, xname: str) -> dict:
    """单因子全貌:基本信息 + 最近 10 evals + tags + 迭代链(ancestors+descendants)。"""
    factor = conn.execute("SELECT * FROM factors WHERE xname = ?", (xname,)).fetchone()
    if not factor:
        raise ValueError(f"xname 不存在: {xname}")
    evals = conn.execute(
        "SELECT ts, ic_mean, icir, sharpe, eval_mode, significant FROM factor_evals "
        "WHERE factor_xname = ? ORDER BY ts DESC LIMIT 10", (xname,),
    ).fetchall()
    tags = [r["name"] for r in conn.execute(
        "SELECT t.name FROM tags t JOIN factor_tags ft ON ft.tag_id = t.id WHERE ft.factor_xname = ?",
        (xname,),
    ).fetchall()]
    ancestors = get_ancestors(conn, xname)
    descendants = get_descendants(conn, xname)
    return {"factor": dict(factor), "evals": [dict(e) for e in evals], "tags": tags,
            "ancestors": [{"xname": a[0], "depth": a[1]} for a in ancestors],
            "descendants": [{"xname": d[0], "depth": d[1]} for d in descendants]}


def get_similar_factors(conn: sqlite3.Connection, xname: str, k: int = 10) -> list[sqlite3.Row]:
    """向量查重:读自身 factors_vec embedding → search_similar。"""
    row = conn.execute("SELECT embedding FROM factors_vec WHERE xname = ?", (xname,)).fetchone()
    if not row:
        raise ValueError(f"xname 在 factors_vec 中不存在: {xname}")
    emb = list(struct.unpack(f"{len(row['embedding']) // 4}f", row["embedding"]))
    return search_similar(conn, emb, k)


def extract_metrics(daily_ic_preview: str | None) -> dict:
    """从 daily_ic_results.txt 文本正则抽 IC/ICIR/Sharpe/Rank IC(纯文本,无 DB)。"""
    if not daily_ic_preview:
        return {}

    def find(regex: str):
        m = re.search(regex, str(daily_ic_preview), re.IGNORECASE)
        return float(m.group(1)) if m else None

    return {
        "ic_mean": find(r"IC[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)"),
        "icir": find(r"ICIR[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)"),
        "sharpe": find(r"Sharpe[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)"),
        "rank_ic": find(r"Rank\s*IC[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)"),
    }
