#!/usr/bin/env python3
"""算子库查询工具（concept-invent Step 3 查库用）。

两种用法：
  查全貌:  python concept_query.py list
           列出所有算子 + 撞族边界 + 应用实例
  查匹配:  python concept_query.py match "<缺口定义>"
           按缺口关键词扫算子定义/抽象结构,粗筛候选

算子库是 AI 的记忆。挖因子 Step 2(想缺口)不看库,Step 3(匹配)才查库。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_conn  # noqa: E402


def list_all():
    """算子全貌:每个算子 + 撞族边界 + 应用实例(iterations.op_id)。"""
    with get_conn() as conn:
        ops = conn.execute("""
            SELECT op_id, name, definition, input_roles, abstract_structure,
                   direction_property, source, source_ref
            FROM operators ORDER BY op_id
        """).fetchall()
        if not ops:
            print("（算子库为空）")
            return
        for op in ops:
            op_id = op[0]
            print(f"\n{'='*70}")
            print(f"[{op_id}] {op[1]}  ({op[5]}, src={op[6] or '?'})")
            print(f"    定义: {op[2]}")
            if op[3]:
                print(f"    输入角色: {op[3]}")
            if op[4]:
                print(f"    抽象结构: {op[4]}")
            # 撞族边界
            edges = conn.execute("""
                SELECT base_type, family, pearson, residual, tested_on, verdict, note
                FROM operator_family_edges WHERE op_id=? ORDER BY base_type
            """, (op_id,)).fetchall()
            if edges:
                print(f"    撞族边界:")
                for e in edges:
                    fam = e[1] or "闭包外"
                    p = f"p={e[2]}" if e[2] is not None else "p=?"
                    r = f"r={e[3]}" if e[3] is not None else ""
                    print(f"      ×{e[0]:<14} → {fam:<12} {p} {r} [{e[5]}] ({e[4]})")
                    if e[6]:
                        print(f"          {e[6]}")
            else:
                print(f"    撞族边界: (未测)")
            # 应用实例
            apps = conn.execute("""
                SELECT from_xname, to_xname, change_note, outcome
                FROM iterations WHERE op_id=? ORDER BY ts DESC LIMIT 5
            """, (op_id,)).fetchall()
            if apps:
                print(f"    应用实例:")
                for a in apps:
                    print(f"      {a[0]} → {a[1]} ({a[3] or '?'}) {a[2] or ''}")


def match(gap):
    """按缺口关键词粗筛算子(定义/抽象结构/input_roles 命中)。"""
    keywords = [w.strip() for w in gap.replace(",", " ").split() if len(w.strip()) >= 2]
    if not keywords:
        print("用法: match <缺口关键词>")
        return
    with get_conn() as conn:
        ops = conn.execute("SELECT op_id, name, definition, abstract_structure, input_roles FROM operators").fetchall()
        scored = []
        for op in ops:
            text = f"{op[2]} {op[3] or ''} {op[4] or ''}"
            hits = sum(1 for kw in keywords if kw in text)
            if hits > 0:
                scored.append((hits, op))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            print(f"缺口 '{gap}' 无匹配算子 → 发明新算子")
            return
        print(f"缺口 '{gap}' 匹配候选:")
        for hits, op in scored[:5]:
            # 该算子的撞族边界(提示避让)
            edges = conn.execute("""
                SELECT base_type, family, verdict FROM operator_family_edges WHERE op_id=?
            """, (op[0],)).fetchall()
            avoid = ", ".join(f"×{e[0]}→{e[1] or '外'}" for e in edges) or "无"
            print(f"  [{op[0]}] {op[1]} (命中{hits}词)")
            print(f"      定义: {op[2][:80]}")
            print(f"      已测边界(避让): {avoid}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: concept_query.py list | match '<缺口>'")
        sys.exit(1)
    if sys.argv[1] == "list":
        list_all()
    elif sys.argv[1] == "match":
        if len(sys.argv) < 3:
            print("用法: match '<缺口关键词>'")
            sys.exit(1)
        match(sys.argv[2])
    else:
        print(f"未知命令: {sys.argv[1]} (list / match)")
