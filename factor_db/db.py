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
        # angle_code 回灌: idea 的角度在 graph_edges DERIVES_FROM 边 properties.angle
        # (explore_uncovered_angle 产 idea 时标)。回灌让 angle_coverage 地图反映饱和度,
        # 驱动 explore 换角度(防主题扎堆)。与 factor-db.mjs addFactorFromHFile 双端一致。
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


# ============ 知识图（axioms / graph_edges / observe_outputs）============
# 分层知识图：AXIOM(axioms表) → DERIVED/HYPOTHESIS(ideas表) → EVIDENCE/REFUTATION(lessons/factors/observe_outputs)。
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
    "observe_outputs": "id",
}

_GRAPH_CONSTANTS = None


def graph_constants() -> dict:
    """加载共享图常量(判据/阈值)。db.py 与 factor-db.mjs 共读 factor_db/graph_constants.json
    → 判据一处,防双端漂移(has_resolved / 饱和度阈值等)。"""
    global _GRAPH_CONSTANTS
    if _GRAPH_CONSTANTS is None:
        _GRAPH_CONSTANTS = json.loads(
            (Path(__file__).resolve().parent / "graph_constants.json").read_text(encoding="utf-8")
        )
    return _GRAPH_CONSTANTS


def _ensure_graph_tables(conn: sqlite3.Connection) -> None:
    """建 axioms/graph_edges/observe_outputs 表(幂等)。migrations v2 graph_core 的表部分。
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
        CREATE TABLE IF NOT EXISTS observe_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, script TEXT NOT NULL,
            axiom_code TEXT NOT NULL, violation TEXT NOT NULL, summary TEXT,
            evidence TEXT, symbol TEXT,
            detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_observe_axiom ON observe_outputs(axiom_code);
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
            "INSERT INTO ideas (text, parent_idea_id, status, argument_chain, necessity_grade, node_layer) "
            "VALUES (?, ?, 'open', ?, ?, ?)",
            (data.get("text"), data.get("parent_idea_id"), chain,
             data.get("necessity_grade"), data.get("node_layer", "HYPOTHESIS")),
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


def add_observe_output(
    conn: sqlite3.Connection,
    script: str,
    axiom_code: str,
    violation: str,
    summary: str | None = None,
    evidence: dict | None = None,
    symbol: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO observe_outputs (script, axiom_code, violation, summary, evidence, symbol)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            script, axiom_code, violation, summary,
            json.dumps(evidence, ensure_ascii=False) if evidence else None,
            symbol,
        ),
    )
    return int(cur.lastrowid)


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
               oo.id AS ev_id, oo.script, oo.summary, oo.evidence AS ev_json, oo.violation,
               a.id AS axiom_id, a.code AS axiom_code, a.statement, a.formal_form, a.expected_signature
        FROM graph_edges ge
        LEFT JOIN observe_outputs oo ON oo.id = ge.from_id AND ge.from_table='observe_outputs'
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
            "evidence": {"id": r["ev_id"], "script": r["script"], "summary": r["summary"],
                         "violation": r["violation"], "evidence": r["ev_json"]} if r["ev_id"] else None,
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
        "observe_outputs": count("SELECT COUNT(*) FROM observe_outputs"),
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
    props = json.loads(row["properties"]) if row and row["properties"] else {}
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
    props = json.loads(row["properties"]) if row and row["properties"] else {}
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

    饱和度启发:saturated=因子≥5且dead_end占≥60%; thin=因子≤2; unexplored=0因子; partial=其余。"""
    rows = conn.execute(
        """
        SELECT a.code, a.name, a.field_family, a.extraction, a.signal_target, a.theory_axiom,
               COUNT(f.xname) AS n_factors,
               COALESCE(SUM(CASE WHEN f.status='dead_end' THEN 1 ELSE 0 END),0) AS n_dead_end,
               COALESCE(SUM(CASE WHEN f.status='evaluated' THEN 1 ELSE 0 END),0) AS n_evaluated,
               MAX(f.latest_icir) AS max_icir
        FROM angle_ontology a
        LEFT JOIN factors f ON f.angle_code = a.code AND f.deprecated_at IS NULL
        GROUP BY a.code, a.name, a.field_family, a.extraction, a.signal_target, a.theory_axiom
        ORDER BY n_factors ASC
        """
    ).fetchall()
    out = []
    for r in rows:
        n, nd = r["n_factors"], r["n_dead_end"]
        sc = graph_constants()["saturation"]
        if n == 0:
            sat = "unexplored"
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
            "n_evaluated": r["n_evaluated"], "max_icir": r["max_icir"], "saturation": sat,
        })
    return out


# ============ 操作选择（动态优先级打分）============
# 替代 graph-engine G1 的固定优先级表(resolve>generalize>...>explore)。
# 固定表让 generalize 总赢 explore → 深度优先陷阱(卡在饱和角度扎堆)。
# 动态打分:角度饱和时 explore 升权 / 聚簇在饱和角度时 generalize 降权 / 操作历史防垄断。

def query_recent_operations(conn: sqlite3.Connection, n: int = 10) -> list[str]:
    """最近 N 个 idea 的产生操作(DERIVES_FROM 边 properties.via)。操作历史,diversity 判据。"""
    rows = conn.execute(
        """SELECT json_extract(properties,'$.via') AS via FROM graph_edges
           WHERE edge_type='DERIVES_FROM' AND json_extract(properties,'$.via') IS NOT NULL
           ORDER BY id DESC LIMIT ?""", (n,)
    ).fetchall()
    return [r[0] for r in rows if r[0]]


def select_graph_operation(conn: sqlite3.Connection) -> dict:
    """动态优先级打分:根据图状态给 5 操作打分,返回推荐 + 分数 + 理由。

    打分因子:角度饱和度 / 聚簇所在角度 / 操作历史 diversity / 触发点强度。
    核心:角度 saturated 时 explore 升到 0.85 > generalize(聚簇在饱和角度 ×0.3)→ 换角度。
    """
    stats = graph_stats(conn)
    coverage = query_angle_coverage(conn)
    recent = query_recent_operations(conn, 10)

    saturated = [a for a in coverage if a["saturation"] == "saturated"]
    fresh = [a for a in coverage if a["saturation"] in ("unexplored", "thin")]
    sat_codes = {a["code"] for a in saturated}
    recent_gen = sum(1 for o in recent if o == "generalize_from_refutation")
    recent_deep = sum(1 for o in recent if o and o != "explore_uncovered_angle")

    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}

    # resolve: 未解矛盾=强燃料,优先
    if stats["unresolved_contradictions"] > 0:
        scores["resolve_contradiction"] = 0.9
        reasons["resolve_contradiction"] = f"{stats['unresolved_contradictions']} 未解矛盾(强燃料)"
    else:
        scores["resolve_contradiction"] = 0.0

    # generalize: 聚簇在 fresh 角度才高分;在 saturated 角度深挖无价值
    clusters = find_refutation_clusters(conn, min_size=3, limit=5)
    if clusters:
        base, parts = 0.7, ["有 size≥3 聚簇 0.7"]
        cluster_in_sat = False
        for cl in clusters:
            a = conn.execute(
                """SELECT json_extract(properties,'$.angle') FROM graph_edges
                   WHERE from_id=? AND edge_type='DERIVES_FROM'
                     AND json_extract(properties,'$.angle') IS NOT NULL LIMIT 1""",
                (cl["target_id"],),
            ).fetchone()
            if a and a[0] in sat_codes:
                cluster_in_sat = True
        if cluster_in_sat:
            base *= 0.3
            parts.append("聚簇在 saturated 角度 ×0.3")
        if recent_gen >= 3:
            base *= 0.5
            parts.append(f"连续 {recent_gen} 次 generalize ×0.5(防垄断)")
        scores["generalize_from_refutation"] = base
        reasons["generalize_from_refutation"] = "; ".join(parts)
    else:
        scores["generalize_from_refutation"] = 0.0

    # fill/orthogonal: 精修型,触发少,有触发点 0.5(主矛盾在 generalize vs explore,先简化)
    scores["fill_chain_gap"] = 0.0
    scores["orthogonal_branch"] = 0.0

    # explore: saturated + fresh 才高分(该换);连续深挖 +diversity
    e, parts = 0.3, []
    if saturated and fresh:
        e = 0.85
        parts.append(f"{len(saturated)} saturated + {len(fresh)} fresh → 该换 0.85")
    else:
        parts.append("无饱和或无 fresh 0.3")
    if recent_deep >= 3:
        e = min(0.95, e + 0.1)
        parts.append(f"连续 {recent_deep} 次深挖 → diversity +0.1")
    scores["explore_uncovered_angle"] = e
    reasons["explore_uncovered_angle"] = "; ".join(parts)

    best = max(scores, key=scores.get)
    return {
        "recommended": best,
        "score": round(scores[best], 3),
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "reason": reasons.get(best, ""),
        "saturated_angles": sorted(sat_codes),
        "fresh_angles": sorted(a["code"] for a in fresh),
        "recent_operations": recent,
    }


# ============ schema 版本追踪（schema_version 表读写原语）============
# 版本链定义在 factor_db/migrations.py（CURRENT_VERSION + MIGRATIONS）。
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
