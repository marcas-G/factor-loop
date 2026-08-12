"""构造当前 representation —— 分两层:语义覆盖为主,实现为辅。

研究的是表示**语义覆盖**非代码覆盖,故主输入 representation_semantics 不给
formula_text/intuition 全文(大量看故事词会让 assumption 沿现有语言生长)。
直接查 factors.db operators 表(不依赖已删的 concept_query)。
"""
import sqlite3


def _saturation_label(n_total: int, n_dead: int) -> str:
    """角度饱和度粗标:saturated(死得多)/ explored / thin。"""
    if n_total == 0:
        return "unexplored"
    dead_ratio = n_dead / n_total
    if n_total >= 15 and dead_ratio >= 0.6:
        return "saturated"
    if n_total >= 8:
        return "explored"
    return "thin"


def build_representation(conn: sqlite3.Connection, top_angles: int = 16) -> dict:
    """返回 {representation_semantics, implementation_examples}。

    representation_semantics:
      - operators: 算子全量(op_id/name/abstract_structure/input_roles/direction_property/source)
      - angle_families: 因子按 angle_code 聚类 + 饱和度(n_factors/n_evaluated/n_dead_end)
    implementation_examples:
      - 每角度 top-1 因子(按 icir)的 name + 一行 formula 摘要(~60 字),非主体
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

    angle_rows = conn.execute("""
        SELECT angle_code,
               COUNT(*) AS n,
               SUM(CASE WHEN status='evaluated' THEN 1 ELSE 0 END) AS n_eval,
               SUM(CASE WHEN status='dead_end' THEN 1 ELSE 0 END) AS n_dead
        FROM factors
        WHERE angle_code IS NOT NULL AND angle_code != ''
        GROUP BY angle_code
        ORDER BY n DESC
    """).fetchall()
    angle_families = [
        {
            "angle_code": r[0], "n_factors": r[1],
            "n_evaluated": r[2], "n_dead_end": r[3],
            "saturation": _saturation_label(r[1], r[3]),
        }
        for r in angle_rows
    ]

    examples = []
    for r in angle_rows[:top_angles]:
        ac = r[0]
        top = conn.execute("""
            SELECT xname, formula_text, latest_icir, status
            FROM factors WHERE angle_code=?
            ORDER BY COALESCE(latest_icir, -999) DESC LIMIT 1
        """, (ac,)).fetchone()
        if top:
            examples.append({
                "angle_code": ac, "xname": top[0],
                "formula_excerpt": (top[1] or "")[:60],
                "latest_icir": top[2], "status": top[3],
            })

    return {
        "representation_semantics": {
            "operators": operators,
            "angle_families": angle_families,
        },
        "implementation_examples": examples,
    }
