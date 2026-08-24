"""构造当前 representation —— 分两层:语义覆盖为主,实现为辅。

研究的是表示**语义覆盖**非代码覆盖,故主输入 representation_semantics 不给
formula_text/intuition 全文(大量看故事词会让 assumption 沿现有语言生长)。
直接查 factors.db operators 表(不依赖已删的 concept_query)。
"""
import sqlite3


def build_representation(conn: sqlite3.Connection, top_examples: int = 16) -> dict:
    """返回 {representation_semantics, implementation_examples}。

    representation_semantics:
      - operators: 算子全量(op_id/name/abstract_structure/input_roles/direction_property/source)
    implementation_examples:
      - 全库 top 因子(按 icir)的 name + 一行 formula 摘要(~60 字),非主体
    """
    op_rows = conn.execute("""
        SELECT op_id, name, abstract_structure, input_roles, direction_property, source
        FROM operators ORDER BY op_id
    """).fetchall()
    operators = [
        {
            "op_id": r[0], "name": r[1],
            "abstract_structure": r[2], "input_roles": r[3],
            "direction_property": r[4], "source": r[5],
        }
        for r in op_rows
    ]

    examples = [
        {
            "xname": r[0],
            "formula_excerpt": (r[1] or "")[:60],
            "latest_icir": r[2], "status": r[3],
        }
        for r in conn.execute("""
            SELECT xname, formula_text, latest_icir, status
            FROM factors
            WHERE deprecated_at IS NULL
            ORDER BY COALESCE(latest_icir, -999) DESC
            LIMIT ?
        """, (top_examples,)).fetchall()
    ]

    return {
        "representation_semantics": {
            "operators": operators,
        },
        "implementation_examples": examples,
    }
