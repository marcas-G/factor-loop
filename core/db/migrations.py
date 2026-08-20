"""schema 版本迁移链。

版本语义 = schema 演进里程碑(每版对应一个特性里程碑):
  v1 baseline     核心实体表(factors/ideas/evals/iterations/lessons/tags/fts/vec
                  + factor_ic_vec/coverage_map/factor_ic_daily)
                  —— 由 schema.sql 全量直建,迁移链不重建,up 为 noop
                  (新库 schema.sql 直建;py 端从未管 v1 迁移,老库假定已具备基线)
  v2 graph_core   知识图表(axioms/graph_edges) + ideas 必然假设字段
  v3 graph_bounds graph_edges.edge_type CHECK 加 BOUNDS(重建表,幂等)
  v4 angle        信息角度元层 angle_ontology + factors.angle_code
  v5 rename_eval_metrics  factor_evals.seven_dim → eval_metrics(消七维命名残留)
  v6 quality_fields  factors.quality_score/quality_grade(多指标聚合分,方案1+4)
  v7 intuition_field factors.intuition(语义意图描述,研究用)
  v8 anchor_text    factors.anchor_text(embedding 锚定文本,固定四要素模板生成)
  v9 angle_candidates angle_candidates 表(angle 自发现候选记录,防归纳循环)
  v10 ideas_angle_code ideas.angle_code(信息角度血缘,因子回灌从这继承)
  v11 iterations_status_iterable iterations.status/iterable(迭代建议状态机,JS 早有 py 补齐)
  v12 operators_library  算子库(operators 算子主体 + operator_family_edges 撞族边界
                  + iterations.op_id)。算子=从因子故事抽取的可复用测量方法(主体,定义纯抽象);
                  因子=算子的应用实例;撞族边界=算子×基底→撞族(复用/发明避让依据)
  v14 factor_structure  因子结构指纹表(R3 查重主体)。双源提取:
                  frontmatter formula 归一化(canonical_hash/template_hash)+
                  C++ 静态扫描(field_signature/operator_primitives/complexity)。
                  xname 与 factors.xname 对齐但不强 FK(含未入库 Base/Probe 锚点)
  v15 retrieval_tables  检索层派生表(R1-R4 Contract 数据基础):
                  factor_operator_usage(R3 op 通道)/ operator_capability_index+vec(R2)/
                  factor_research_state(R1)/ factor_evidence_rollup(R4+S1)/ library_map VIEW(R1)
  v16 ridge_svd_fields  factors 冗余度画像列(平台 restest Ridge-SVD):
                  latest_dloocv_pct(线性净增益主判据)/ latest_r2_x(X空间冗余度)/
                  latest_res_ic(增量IC)。冗余判定从 R4(IC空间pearson)改为平台 dLOOCV
  v17 verdict_field    factors.verdict(评估结论 pass/fail, 与 status 解耦)。
                  老库回填:status=evaluated→pass, dead_end→fail。

单一真相:
  - DDL 真相 = schema.sql(全量基线,新库直建到最新)
  - 迁移链 = 把现有散落的 ensure_* 幂等函数按版本编排(不重复 DDL,无双真相源)
  - CURRENT_VERSION 与 mjs(runtime/lib/factor-db.mjs)一致,由 test_migrations 断言

用法:
    import sys; sys.path.insert(0, "<项目根>")
    from core.db.migrations import migrate, CURRENT_VERSION
    with db.get_conn(path) as conn:
        migrate(conn)   # 幂等:从当前版本补齐到 CURRENT
"""
from __future__ import annotations

import sqlite3

from core.db import db

# 与 runtime/lib/factor-db.mjs 的 CURRENT_SCHEMA_VERSION 保持一致(test 断言)。
CURRENT_VERSION = 17


def _baseline(conn: sqlite3.Connection) -> None:
    """v1 核心基线表。由 schema.sql 全量直建,迁移链不负责重建。
    py 端从未管 v1 迁移(新库 schema.sql 直建,老库假定已有)。noop,仅占版本号语义。"""
    pass


def _graph_core(conn: sqlite3.Connection) -> None:
    """v2 知识图表(axioms/graph_edges) + ideas 必然假设字段。"""
    db._ensure_graph_tables(conn)
    db.ensure_ideas_necessity_fields(conn)


def _graph_bounds(conn: sqlite3.Connection) -> None:
    """v3 graph_edges.edge_type CHECK 加 BOUNDS(重建表,幂等)。"""
    db.migrate_graph_edge_bounds(conn)


def _angle(conn: sqlite3.Connection) -> None:
    """v4 信息角度元层 angle_ontology + factors.angle_code。"""
    db.ensure_angle_schema(conn)


def _rename_eval_metrics(conn: sqlite3.Connection) -> None:
    """v5 factor_evals.seven_dim → eval_metrics(消除七维命名残留)。
    seven_dim 是早期 factor_check 7 维设计的字段名,内容已非 7 维(8+ key)。
    SQLite 3.25+ ALTER TABLE RENAME COLUMN;幂等(已是 eval_metrics 则跳过)。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(factor_evals)")}
    if "seven_dim" in cols and "eval_metrics" not in cols:
        conn.execute("ALTER TABLE factor_evals RENAME COLUMN seven_dim TO eval_metrics")


def _add_quality_fields(conn: sqlite3.Connection) -> None:
    """v6 factors.quality_score/quality_grade(多指标聚合分)。"""
    db.ensure_quality_fields(conn)


def _add_intuition_field(conn: sqlite3.Connection) -> None:
    """v7 factors.intuition(语义意图描述,研究用)。"""
    db.ensure_intuition_field(conn)


def _add_anchor_text(conn: sqlite3.Connection) -> None:
    """v8 factors.anchor_text(embedding 锚定文本,固定四要素模板生成)。"""
    db.ensure_anchor_text_field(conn)


def _add_angle_candidates(conn: sqlite3.Connection) -> None:
    """v9 angle_candidates 表(angle 自发现候选记录,防归纳循环)。"""
    db.ensure_angle_candidates_table(conn)


def _add_ideas_angle_code(conn: sqlite3.Connection) -> None:
    """v10 ideas.angle_code(信息角度血缘,因子回灌从这继承)。"""
    db.ensure_ideas_angle_code(conn)


def _add_iterations_columns(conn: sqlite3.Connection) -> None:
    """v11 iterations.status/iterable(迭代建议状态机)。
    schema.sql 新库已含;此步给既有 Python 库补列(JS 侧 init 早有 migrateIterationsSchema,
    py 侧原本漏 → 纯 Python 库与版本号 v10 不一致)。"""
    db.ensure_iterations_columns(conn)


def _add_operators_library(conn: sqlite3.Connection) -> None:
    """v12 算子库：算子为主体（operators）+ 撞族边界（operator_family_edges）+ iterations.op_id。
    算子 = 从因子故事抽取的可复用测量方法（主体，定义纯抽象，不绑因子/基底）。
    因子是算子的应用实例（iterations.op_id）。撞族边界 = 算子×基底→撞族（复用避让依据）。"""
    db.ensure_operators_library(conn)


def _add_cohort_meta(conn: sqlite3.Connection) -> None:
    """v13 factors cohort 元数据（Phase 2.1 operator_planner 冻结 cohort 因子专用）。

    spec §3：A/B 入 factors 表保留血缘(need_id/plan_id/program_id/operator_chain/field_bindings)
    + 冻结 hash(parameter_hash/kernel_hash) + decision_available_at（证明入库早于 5C 评价）。
    普通因子这些列 NULL。
    """
    db.ensure_cohort_meta_fields(conn)


def _add_factor_structure(conn: sqlite3.Connection) -> None:
    """v14 factor_structure 表(因子结构指纹, R3 查重主体)。双源提取:
    formula 归一化(canonical/template hash)+ C++ 静态扫描(field/primitives/complexity)。"""
    db.ensure_factor_structure_table(conn)


def _add_retrieval_tables(conn: sqlite3.Connection) -> None:
    """v15 检索层派生表(R1-R4 Contract 数据基础)。
    factor_operator_usage / operator_capability_index+vec / factor_research_state /
    factor_evidence_rollup / library_map VIEW。"""
    db.ensure_retrieval_tables(conn)


def _add_ridge_svd_fields(conn: sqlite3.Connection) -> None:
    """v16 factors 冗余度画像列(平台 restest Ridge-SVD)。
    latest_dloocv_pct / latest_r2_x / latest_res_ic。"""
    db.ensure_ridge_svd_fields(conn)


def _add_verdict_field(conn: sqlite3.Connection) -> None:
    """v17 factors.verdict(评估结论 pass/fail) + 老库按 status 回填。"""
    db.ensure_verdict_field(conn)
    conn.execute("UPDATE factors SET verdict='pass' WHERE status='evaluated' AND verdict IS NULL")
    conn.execute("UPDATE factors SET verdict='fail' WHERE status='dead_end' AND verdict IS NULL")


# (version, name, up) 有序。baseline 在前保证版本号语义完整;每步 up 必须幂等。
MIGRATIONS = [
    (1, "baseline",     _baseline),
    (2, "graph_core",   _graph_core),
    (3, "graph_bounds", _graph_bounds),
    (4, "angle",        _angle),
    (5, "rename_eval_metrics", _rename_eval_metrics),
    (6, "quality_fields", _add_quality_fields),
    (7, "intuition_field", _add_intuition_field),
    (8, "anchor_text",     _add_anchor_text),
    (9, "angle_candidates", _add_angle_candidates),
    (10, "ideas_angle_code", _add_ideas_angle_code),
    (11, "iterations_status_iterable", _add_iterations_columns),
    (12, "operators_library", _add_operators_library),
    (13, "cohort_meta", _add_cohort_meta),
    (14, "factor_structure", _add_factor_structure),
    (15, "retrieval_tables", _add_retrieval_tables),
    (16, "ridge_svd_fields", _add_ridge_svd_fields),
    (17, "verdict_field", _add_verdict_field),
]


def migrate(conn: sqlite3.Connection) -> int:
    """从当前版本幂等补齐到 CURRENT_VERSION。返回应用后的版本。

    每步 up 成功后写一行 schema_version。
    史前库(无 schema_version 表, version 0)→ 跑全部 up → 标 CURRENT。
    全新库(init_db 已 schema.sql 直建结构)→ 第一次 migrate 时 cur=0,
      up 全幂等(CREATE IF NOT EXISTS / ALTER 缺列)→ 安全标到 CURRENT。
    """
    db.ensure_schema_version_table(conn)
    cur = db.current_schema_version(conn)
    for version, name, up in MIGRATIONS:
        if version <= cur:
            continue
        up(conn)
        db.record_schema_version(conn, version, name)
    return db.current_schema_version(conn)
