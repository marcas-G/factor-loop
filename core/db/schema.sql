-- Factor DB Schema (§8.2 DDL 完整版)
-- 幂等：CREATE ... IF NOT EXISTS

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============ factors（因子实体）============
CREATE TABLE IF NOT EXISTS factors (
    xname            TEXT PRIMARY KEY,
    class_name       TEXT,
    file_path        TEXT,
    formula_text     TEXT,
    params           TEXT,
    status           TEXT NOT NULL
                     CHECK (status IN ('draft','submitted','evaluated','failed','dead_end')),
    verdict          TEXT CHECK (verdict IN ('pass','fail')),  -- 评估结论(pass/fail),与 status 解耦
    latest_ic        REAL,
    latest_icir      REAL,
    latest_sharpe    REAL,
    latest_rank_ic   REAL,
    -- 冗余度画像(平台 restest Ridge-SVD, 与 latest_icir 对称的最新一次评估)
    latest_r2_x      REAL,         -- X 空间冗余度(别人72因子库解释方差, >0.8 高冗余)
    latest_res_ic    REAL,         -- 去掉库冗余后的增量 IC
    created_ts       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_ts  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deprecated_at    TIMESTAMP,
    emb_generated_at TIMESTAMP,
    quality_score    REAL,         -- 多指标聚合分(0-1,独立+稳定加权,方案1)
    quality_grade    TEXT,         -- 等级 A(≥0.7)/B(0.4-0.7)/C(<0.4),方案4
    intuition        TEXT,         -- 语义意图描述(研究用,带 idea#/上下文;人看)
    anchor_text      TEXT,         -- embedding 锚定文本(固定四要素模板生成,检索专用)
    -- Phase 2.1 cohort 元数据（operator_planner 冻结 cohort 因子专用；普通因子 NULL）
    origin_type              TEXT,        -- 因子来源(OPERATOR_PLANNER / BRAINSTORM / ...)
    cohort_tag               TEXT,        -- cohort 标签(PHASE2_FIRST_REAL_COHORT)
    need_id                  TEXT,        -- NeedCard id（mechanical_control 产）
    plan_id                  TEXT,        -- chain_planner plan id（确定性 plan0）
    program_id               TEXT,        -- plan_to_program program id
    operator_chain           TEXT,        -- 算子链 JSON
    field_bindings           TEXT,        -- 字段绑定 JSON（冻结，后验搜索守卫）
    parameter_hash           TEXT,        -- 参数冻结 hash（sha16）
    kernel_hash              TEXT,        -- kernel hash（sha16）
    decision_available_at    TIMESTAMP,   -- 入库时刻（证明早于 5C 评价，未看后续结果）
    evaluation_status        TEXT,        -- 5C 评价状态（PENDING_PLATFORM_FEVAL / 分层摘要）
    posterior_search_forbidden INTEGER    -- 0/1 冻结标记（看 5C 结果后禁改公式/参数/绑定）
);

CREATE INDEX IF NOT EXISTS idx_factors_status       ON factors(status);
CREATE INDEX IF NOT EXISTS idx_factors_last_updated ON factors(last_updated_ts);

-- sqlite-vec 向量虚拟表
CREATE VIRTUAL TABLE IF NOT EXISTS factors_vec USING vec0(
    xname     TEXT PRIMARY KEY,
    embedding FLOAT[512]
);

-- FTS5 公式全文检索
CREATE VIRTUAL TABLE IF NOT EXISTS factors_fts USING fts5(
    formula_text, class_name,
    content='factors', content_rowid='rowid',
    tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS factors_fts_ai AFTER INSERT ON factors BEGIN
    INSERT INTO factors_fts(rowid, formula_text, class_name)
    VALUES (new.rowid, new.formula_text, new.class_name);
END;
CREATE TRIGGER IF NOT EXISTS factors_fts_ad AFTER DELETE ON factors BEGIN
    INSERT INTO factors_fts(factors_fts, rowid, formula_text, class_name)
    VALUES ('delete', old.rowid, old.formula_text, old.class_name);
END;
CREATE TRIGGER IF NOT EXISTS factors_fts_au AFTER UPDATE ON factors BEGIN
    INSERT INTO factors_fts(factors_fts, rowid, formula_text, class_name)
    VALUES ('delete', old.rowid, old.formula_text, old.class_name);
    INSERT INTO factors_fts(rowid, formula_text, class_name)
    VALUES (new.rowid, new.formula_text, new.class_name);
END;

-- ============ ideas（研究想法）============
CREATE TABLE IF NOT EXISTS ideas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    text           TEXT NOT NULL,
    parent_idea_id INTEGER,
    status         TEXT NOT NULL CHECK (status IN ('open','closed')),
    created_ts     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_ts      TIMESTAMP,
    -- 必然假设生成机扩展：论证链是假设的属性（一假设挂多因子，不放 factors 表）
    argument_chain            TEXT,      -- 结构化论证链 JSON（Σ/超加性耦合/唯一性证明/竞争解释/可证伪痕迹）
    support_score             REAL,      -- 假设级连续支持度（贝叶斯平滑，不绝对判断）
    evaluated_factor_count    INTEGER NOT NULL DEFAULT 0,
    support_score_computed_at TIMESTAMP,
    necessity_grade           TEXT,      -- 必然性分级: necessary|identification|conditional|draft（区分硬必然与可识别但非唯一）
    node_layer                TEXT DEFAULT 'HYPOTHESIS',  -- 知识图层: DERIVED(机制推导)|HYPOTHESIS(可算假设)；AXIOM 在 axioms 表
    FOREIGN KEY (parent_idea_id) REFERENCES ideas(id)
);

CREATE INDEX IF NOT EXISTS idx_ideas_parent ON ideas(parent_idea_id);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);

CREATE VIRTUAL TABLE IF NOT EXISTS ideas_fts USING fts5(
    text, content='ideas', content_rowid='rowid', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS ideas_fts_ai AFTER INSERT ON ideas BEGIN
    INSERT INTO ideas_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS ideas_fts_ad AFTER DELETE ON ideas BEGIN
    INSERT INTO ideas_fts(ideas_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS ideas_fts_au AFTER UPDATE ON ideas BEGIN
    INSERT INTO ideas_fts(ideas_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO ideas_fts(rowid, text) VALUES (new.rowid, new.text);
END;

-- ============ factor_evals（评估快照）============
CREATE TABLE IF NOT EXISTS factor_evals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_xname        TEXT NOT NULL,
    idea_id             INTEGER,
    ts                  TIMESTAMP NOT NULL,
    symbol              TEXT,
    freq                TEXT,
    ic_mean             REAL,
    icir                REAL,
    sharpe              REAL,
    rank_ic             REAL,
    eval_metrics           TEXT,
    conditional_returns TEXT,
    eval_mode           TEXT CHECK (eval_mode IN ('full','pearson','deep')),
    significant         INTEGER DEFAULT 0,
    raw_path            TEXT,
    FOREIGN KEY (factor_xname) REFERENCES factors(xname),
    FOREIGN KEY (idea_id)         REFERENCES ideas(id)
);

CREATE INDEX IF NOT EXISTS idx_evals_factor_ts ON factor_evals(factor_xname, ts DESC);
CREATE INDEX IF NOT EXISTS idx_evals_idea_ts   ON factor_evals(idea_id, ts);
CREATE INDEX IF NOT EXISTS idx_evals_symbol    ON factor_evals(symbol);
CREATE INDEX IF NOT EXISTS idx_evals_freq      ON factor_evals(freq);

-- ============ idea_factor_links（idea 内尝试）============
CREATE TABLE IF NOT EXISTS idea_factor_links (
    idea_id      INTEGER NOT NULL,
    factor_xname TEXT NOT NULL,
    tried_order  INTEGER,
    verdict      TEXT,
    PRIMARY KEY (idea_id, factor_xname),
    FOREIGN KEY (idea_id)      REFERENCES ideas(id),
    FOREIGN KEY (factor_xname) REFERENCES factors(xname)
);

CREATE INDEX IF NOT EXISTS idx_ifl_factor ON idea_factor_links(factor_xname);

-- ============ iteration_suggestions（因子节点待办建议）============
-- 本表是因子节点的待办属性：从某因子出发建议下一步做什么。realize 后血缘事实
-- 只写 factor_lineage_edges；本表不重复存 target/outcome/icir。
CREATE TABLE IF NOT EXISTS iteration_suggestions (
    suggestion_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    from_xname        TEXT NOT NULL,
    idea_id           INTEGER,
    op_id             INTEGER,
    change_note       TEXT,
    reason            TEXT,
    status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','in_progress','realized','abandoned')),
    created_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_xname)        REFERENCES factors(xname),
    FOREIGN KEY (idea_id)           REFERENCES ideas(id),
    FOREIGN KEY (op_id)             REFERENCES operators(op_id)
);

CREATE INDEX IF NOT EXISTS idx_is_from   ON iteration_suggestions(from_xname);
CREATE INDEX IF NOT EXISTS idx_is_status ON iteration_suggestions(status);
CREATE INDEX IF NOT EXISTS idx_is_idea   ON iteration_suggestions(idea_id);
CREATE INDEX IF NOT EXISTS idx_is_op     ON iteration_suggestions(op_id);

-- v19 兼容视图：老报表/SQL 仍可用 iterations 名称读取建议，但真相只在
-- iteration_suggestions。该 view 不可写；新状态机必须走 iteration_* API。
CREATE VIEW IF NOT EXISTS iterations AS
SELECT
    s.suggestion_id AS id,
    s.from_xname,
    COALESCE(e.child_xname, s.from_xname) AS to_xname,
    s.idea_id,
    s.change_note,
    s.reason,
    e.outcome,
            e.icir_delta,
            s.created_ts AS ts,
            s.status,
            s.op_id
FROM iteration_suggestions s
LEFT JOIN factor_lineage_edges e
  ON e.suggestion_id = s.suggestion_id AND e.origin = 'suggestion';

-- ============ factor_lineage（真实血缘 DAG）============
-- 一条边 = 一个已存在因子到另一个已存在因子的 derivation。open/in_progress 建议
-- 不产生边；这保证血缘查询永远不会把自指占位当成真实父子关系。
CREATE TABLE IF NOT EXISTS factor_lineage_edges (
    edge_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_xname  TEXT NOT NULL,
    child_xname   TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'iteration'
                  CHECK (relation_type IN ('iteration','repair','operator_application','manual','reseed')),
    origin        TEXT NOT NULL DEFAULT 'suggestion'
                  CHECK (origin IN ('suggestion','retry','cog_repair','operator_contract','manual_backfill','reseeding')),
    suggestion_id INTEGER,
    idea_id       INTEGER,
    op_id         INTEGER,
    change_note   TEXT,
    reason        TEXT,
    outcome       TEXT CHECK (outcome IN ('improved','declined','neutral')),
    icir_delta    REAL,
    evidence      TEXT,
    confidence    TEXT NOT NULL DEFAULT 'observed'
                  CHECK (confidence IN ('observed','declared','inferred')),
    created_ts    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (parent_xname, child_xname, relation_type),
    FOREIGN KEY (parent_xname)   REFERENCES factors(xname),
    FOREIGN KEY (child_xname)    REFERENCES factors(xname),
    FOREIGN KEY (suggestion_id)  REFERENCES iteration_suggestions(suggestion_id),
    FOREIGN KEY (idea_id)        REFERENCES ideas(id),
    FOREIGN KEY (op_id)          REFERENCES operators(op_id),
    CHECK (parent_xname <> child_xname)
);

CREATE INDEX IF NOT EXISTS idx_fle_parent ON factor_lineage_edges(parent_xname);
CREATE INDEX IF NOT EXISTS idx_fle_child  ON factor_lineage_edges(child_xname);
CREATE INDEX IF NOT EXISTS idx_fle_sugg   ON factor_lineage_edges(suggestion_id);
CREATE INDEX IF NOT EXISTS idx_fle_idea   ON factor_lineage_edges(idea_id);
CREATE INDEX IF NOT EXISTS idx_fle_op     ON factor_lineage_edges(op_id);

-- Transitive closure: one row per (ancestor, descendant), including depth-0 self paths.
-- path_count counts minimum-length paths and is capped during rebuild; it is for
-- diagnostics, not a replacement for edge provenance.
CREATE TABLE IF NOT EXISTS factor_lineage_paths (
    ancestor_xname   TEXT NOT NULL,
    descendant_xname TEXT NOT NULL,
    min_depth        INTEGER NOT NULL,
    path_count       INTEGER NOT NULL DEFAULT 1,
    is_direct        INTEGER NOT NULL DEFAULT 0 CHECK (is_direct IN (0,1)),
    rebuilt_ts       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ancestor_xname, descendant_xname),
    FOREIGN KEY (ancestor_xname)   REFERENCES factors(xname),
    FOREIGN KEY (descendant_xname) REFERENCES factors(xname)
);

CREATE INDEX IF NOT EXISTS idx_flp_descendant ON factor_lineage_paths(descendant_xname, min_depth);

-- Materialized per-factor lineage profile. primary_root is a topological root; a
-- factor with multiple roots remains a DAG node and is not collapsed into one tree.
CREATE TABLE IF NOT EXISTS factor_lineage_nodes (
    xname                    TEXT PRIMARY KEY,
    is_root                  INTEGER NOT NULL DEFAULT 1 CHECK (is_root IN (0,1)),
    is_leaf                  INTEGER NOT NULL DEFAULT 1 CHECK (is_leaf IN (0,1)),
    parent_count             INTEGER NOT NULL DEFAULT 0,
    child_count              INTEGER NOT NULL DEFAULT 0,
    primary_root_xname       TEXT NOT NULL,
    depth_from_primary_root  INTEGER NOT NULL DEFAULT 0,
    descendant_count         INTEGER NOT NULL DEFAULT 0,
    max_descendant_depth     INTEGER NOT NULL DEFAULT 0,
    evaluated_descendant_count INTEGER NOT NULL DEFAULT 0,
    dead_end_descendant_count  INTEGER NOT NULL DEFAULT 0,
    open_suggestion_count      INTEGER NOT NULL DEFAULT 0,
    last_lineage_ts            TIMESTAMP,
    updated_ts                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (xname)              REFERENCES factors(xname),
    FOREIGN KEY (primary_root_xname) REFERENCES factors(xname)
);

CREATE INDEX IF NOT EXISTS idx_fln_root ON factor_lineage_nodes(primary_root_xname);
CREATE INDEX IF NOT EXISTS idx_fln_leaf ON factor_lineage_nodes(is_leaf);

-- ============ lessons（仅 check_done 实验结果：dead_end 或 success_pattern）============
CREATE TABLE IF NOT EXISTS lessons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT NOT NULL
                  CHECK (type IN ('dead_end','success_pattern')),
    scope         TEXT NOT NULL CHECK (scope = 'factor'),
    text          TEXT NOT NULL,
    evidence      TEXT,
    idea_id       INTEGER,
    factor_xname  TEXT NOT NULL,
    created_ts    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deprecated_at TIMESTAMP,
    FOREIGN KEY (idea_id)      REFERENCES ideas(id),
    FOREIGN KEY (factor_xname) REFERENCES factors(xname)
);

CREATE INDEX IF NOT EXISTS idx_lessons_type_scope ON lessons(type, scope);
CREATE INDEX IF NOT EXISTS idx_lessons_factor     ON lessons(factor_xname);
CREATE INDEX IF NOT EXISTS idx_lessons_idea       ON lessons(idea_id);

CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
    text, content='lessons', content_rowid='rowid', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS lessons_fts_ai AFTER INSERT ON lessons BEGIN
    INSERT INTO lessons_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS lessons_fts_ad AFTER DELETE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS lessons_fts_au AFTER UPDATE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO lessons_fts(rowid, text) VALUES (new.rowid, new.text);
END;

-- ============ tags（标准化标签字典）============
CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

-- ============ factor_tags（因子-标签多对多）============
CREATE TABLE IF NOT EXISTS factor_tags (
    factor_xname TEXT NOT NULL,
    tag_id       INTEGER NOT NULL,
    PRIMARY KEY (factor_xname, tag_id),
    FOREIGN KEY (factor_xname) REFERENCES factors(xname),
    FOREIGN KEY (tag_id)       REFERENCES tags(id)
);

CREATE INDEX IF NOT EXISTS idx_ft_tag ON factor_tags(tag_id);

-- ============ factor_ic_vec（因子日级 IC 序列向量，ANN 找预测行为相似因子）============
-- 设计：每个 (factor, symbol, freq, y_horizon) 算一条"每日 IC 序列"：
--       每个交易日 t，对该日所有 tick 算 corr(X_t, Y_h_t) → 单日一个 IC 值
--       拼成 N 日 IC 序列 → z-score + L2 归一化 → 250 维向量
-- 业务语义：两个因子 IC 序列相似 = 预测能力同涨同跌 = 真冗余（比值序列相似更贴近业务）
CREATE VIRTUAL TABLE IF NOT EXISTS factor_ic_vec USING vec0(
    factor_xname TEXT,
    symbol       TEXT,
    freq         TEXT,         -- 参数化名(因子实例标识,非真频率);IC 对齐跨 freq(同 symbol+horizon+date)
    y_horizon    INTEGER,
    embedding    FLOAT[250]
);

CREATE TABLE IF NOT EXISTS factor_ic_vec_meta (
    factor_xname        TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    freq                TEXT NOT NULL,
    y_horizon           INTEGER NOT NULL,
    n_samples           INTEGER,
    start_date          TEXT,
    end_date            TEXT,
    mean_ic             REAL,
    std_ic              REAL,
    icir                REAL,           -- mean_ic / std_ic，因子评估常用指标
    computed_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (factor_xname, symbol, freq, y_horizon),
    FOREIGN KEY (factor_xname) REFERENCES factors(xname)
);

-- ============ coverage_map（覆盖地图视图，只读聚合）============
-- v1 覆盖地图：按 symbol × freq × status × necessity_grade 聚合"已搜过"的空间。
-- 数据源 factor_ic_vec_meta（symbol/freq 真值在此；factor_evals.symbol/freq 恒 NULL，见 addEval）。
-- 动态 gap 判定（thin/hot/stale 阈值）在 coverageMap() JS 层算，不进 VIEW。
-- coverageMap() 用内联 SQL 自给自足，VIEW 不存在不影响功能——此 VIEW 仅供直查/文档。
CREATE VIEW IF NOT EXISTS coverage_map AS
SELECT
    m.symbol,
    m.y_horizon,
    f.status,
    i.necessity_grade,
    COUNT(DISTINCT f.xname)                                                AS searched_count,
    COUNT(DISTINCT CASE WHEN f.status = 'evaluated' THEN f.xname END)      AS evaluated_count,
    COUNT(DISTINCT CASE WHEN f.status = 'dead_end'  THEN f.xname END)      AS dead_end_count,
    AVG(f.latest_icir)                                                     AS avg_icir,
    MAX(m.computed_at)                                                     AS last_evaluated_ts
FROM factor_ic_vec_meta m
JOIN factors f ON f.xname = m.factor_xname
LEFT JOIN factor_evals e2 ON e2.id = (
    SELECT id FROM factor_evals WHERE factor_xname = f.xname ORDER BY ts DESC LIMIT 1
)
LEFT JOIN ideas i ON i.id = e2.idea_id
GROUP BY m.symbol, m.y_horizon, f.status, i.necessity_grade;

-- ============ factor_ic_daily（因子原始日级 IC 序列，残差 Miner 用）============
-- refresh_factor_ic_vectors.py 算 IC 序列向量时，把归一化前的原始每日 IC 也存下来。
-- residual_ic_strength 用它做正交：新因子 IC 序列在库内基底 IC 张成空间的残差比例
--   = 预测能力不被已有因子线性解释的程度（高=真新颖，低=冗余）。
-- 与 factor_ic_vec（归一化 250 维向量，ANN 查相似）互补：那是形状，这是原始幅度。
CREATE TABLE IF NOT EXISTS factor_ic_daily (
    factor_xname        TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    freq                TEXT NOT NULL,   -- 参数化名(因子实例标识,非真频率);IC 对齐/冗余查询靠 (symbol, y_horizon, date) 跨 freq,不限 freq
    y_horizon           INTEGER NOT NULL,
    date                TEXT NOT NULL,
    ic                  REAL,
    PRIMARY KEY (factor_xname, symbol, freq, y_horizon, date),
    FOREIGN KEY (factor_xname) REFERENCES factors(xname)
);

CREATE INDEX IF NOT EXISTS idx_ic_daily_scene ON factor_ic_daily(symbol, freq, y_horizon, date);

-- ============ axioms（知识图 · AXIOM 层：理论公理/利润来源）============
-- 分层知识图的根节点，DERIVES_FROM 推理链的起点。可被攻击的经验命题（非定义）。
-- 可信度最高：人工锚定（文献/framework §2）。下游 DERIVED/HYPOTHESIS 推理都引用此处 code。
-- 迁移脚本 seed_axioms 预填 13 条：8 理论(Roll/Kyle/Gatheral/Hurst/杠杆/正交/扩散/EMH) + L1-L5 利润来源。
CREATE TABLE IF NOT EXISTS axioms (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL UNIQUE,        -- 稳定代号: 'roll_bounce'/'kyle_lambda'/'profit_L1'...
    category          TEXT NOT NULL,               -- 'microstructure'/'efficiency'/'profit_source'/'memory'
    statement         TEXT NOT NULL,               -- 完整命题陈述（可被攻击的经验命题）
    formal_form       TEXT,                        -- 形式化表达: "Cov(r_t,r_{t+1})<0 ∧ Cov(r_t,r_{t+k})≈0 for k≥2"
    expected_signature TEXT,                       -- 理论预期可观测签名 JSON: {"lag1_ac":"negative_significant",...}
    source            TEXT,                        -- 学术出处: 'Roll 1984'/'framework §2 L1'
    falsifiable       TEXT,                        -- 可证伪条件: "若 bid-ask bounce 不存在则 lag1 自相关为零"
    created_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_axioms_category ON axioms(category);

-- ============ graph_edges（知识图 · 跨表语义关系边）============
-- 统一存跨表语义关系。from/to 用 (table, id) 软引用现有表行，不在本表存节点内容（单一真相源）。
-- id 类型: factors 存 xname(TEXT)，axioms/ideas/lessons 存 integer id 字符串。
-- 边类型:
--   CONTRADICTS    矛盾（推理燃料；resolve_contradiction 触发）
--   DERIVES_FROM   推导来源（idea 从 axiom/derived 推出）
--   INSTANTIATES   实例化（factor 是 idea 的可测实现）
--   SPECIALIZES    特化（idea 是另一 idea 的更窄形式 / factor 演化）
--   ORTHOGONAL_TO  正交（两信息源不应冗余）
--   SUPPORTS       支持（evidence 支撑 idea）
--   REFUTES        反驳（refutation 击破 idea）
CREATE TABLE IF NOT EXISTS graph_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_table  TEXT NOT NULL,                     -- 'axioms'/'ideas'/'factors'/'lessons'
    from_id     TEXT NOT NULL,                     -- factors 存 xname；其余存 integer id 字符串
    to_table    TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    edge_type   TEXT NOT NULL CHECK (edge_type IN
                ('CONTRADICTS','DERIVES_FROM','INSTANTIATES','SPECIALIZES',
                 'ORTHOGONAL_TO','SUPPORTS','REFUTES','BOUNDS')),
    weight      REAL,                              -- CONTRADICTS=矛盾显著性/SUPPORTS=IC强度/REFUTES=反驳强度/SPECIALIZES=|icir_delta|
    properties  TEXT,                              -- JSON: {"resolved_by":idea_id,"role":..,"via":..}
    created_ts  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_table, from_id, to_table, to_id, edge_type)   -- 幂等：同四元组+类型不重复
);
CREATE INDEX IF NOT EXISTS idx_edges_from      ON graph_edges(from_table, from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to        ON graph_edges(to_table, to_id);
CREATE INDEX IF NOT EXISTS idx_edges_type      ON graph_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_type_from ON graph_edges(edge_type, from_table, from_id);

-- ============ 算子库 v12（算子为主体，因子为应用实例）============
-- 算子 = 从因子故事里抽取的可复用测量方法（如"对手吸收"/"弹性变化"）。
-- 算子是主体：定义纯抽象（不绑具体因子/基底），可配任何基底复用。
-- 因子是算子的应用实例（记在 iteration_suggestions.op_id / factor_lineage_edges.op_id）。
-- 撞族边界 = 算子×基底类型 → 撞了哪个族（复用/发明的避让依据）。
CREATE TABLE IF NOT EXISTS operators (
    op_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL UNIQUE,        -- 算子名（如 "对手吸收"）
    definition         TEXT NOT NULL,               -- 机制描述（纯抽象，禁止出现具体因子名/基底名）
    input_roles        TEXT,                        -- JSON：需要什么角色（如 ["thrust_direction","opposing_resource"]）
    abstract_structure TEXT,                        -- 抽象计算骨架（参数化，不绑基底，如 "consump=(ema_res-res_now)/ema_res"）
    direction_property TEXT CHECK(direction_property IN ('INVARIANT','EQUIVARIANT','PAIRED')),
    source             TEXT,                        -- 来源：strong_factor_5q / failed_lesson / market_theory
    source_ref         TEXT,                        -- 来源因子 xname（从哪挖出的）
    created_ts         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 撞族边界：算子 × 基底类型 → 撞族结果（pearson/residual/tested_on）
-- 每条 = 该算子在该基底类型上测过一次。family=NULL 表示未撞族（闭包外/空白）。
CREATE TABLE IF NOT EXISTS operator_family_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id       INTEGER NOT NULL,
    base_type   TEXT NOT NULL,                       -- 基底类型：size/flow/spread/oi/price/cancel/...
    family      TEXT,                                 -- 撞的族（imbalance/ofi/cancel/...），NULL=闭包外
    pearson     REAL,                                 -- 与库内最高 |pearson|
    residual    REAL,                                 -- 残差 IC 强度
    tested_on   TEXT,                                 -- 测试因子 xname
    verdict     TEXT CHECK(verdict IN ('outside_closure','inside_closure','untested')),
    note        TEXT,
    ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(op_id, base_type),                        -- 一个算子×基底类型只保留最新一次撞族结果
    FOREIGN KEY (op_id)     REFERENCES operators(op_id),
    FOREIGN KEY (tested_on)  REFERENCES factors(xname)
);

CREATE INDEX IF NOT EXISTS idx_ofe_op   ON operator_family_edges(op_id);
CREATE INDEX IF NOT EXISTS idx_ofe_base ON operator_family_edges(base_type);
CREATE INDEX IF NOT EXISTS idx_ofe_fam  ON operator_family_edges(family);

-- ============ factor_structure（因子结构指纹, R3 查重主体）============
-- 双源提取(避免 C++ 完整 AST 成本黑洞):
--   源1 frontmatter formula 伪代码归一化 → canonical_text/canonical_hash/template_hash
--       canonical: 字段名归一(size→SIZE/价格→PRICE)+ 去注释 + 去空白;template: 在 canonical 基础上参数占位化
--   源2 C++ 静态扫描(正则/词法) → field_signature/operator_primitives/complexity
-- R3 search_factor_realizations 的 structural channel 主力:
--   exact_hash 精确撞 / template_hash 换参撞 / operator_primitives 结构族聚类
-- xname 与 factors.xname 对齐(可独立存在,不强 FK — 含未入库的 Base/Probe 锚点)
CREATE TABLE IF NOT EXISTS factor_structure (
    xname              TEXT PRIMARY KEY,
    canonical_text     TEXT,        -- formula 伪代码归一化后文本(字段归一+去注释去空白)
    canonical_hash     TEXT,        -- sha1(canonical_text) — 精确结构撞
    template_hash      TEXT,        -- sha1(canonical_text 参数占位化) — 换参撞
    tree_depth         INTEGER,     -- 公式嵌套深度(主输出表达式)
    node_count         INTEGER,     -- 公式节点数
    field_signature    TEXT,        -- JSON: 用到的原始字段归一名 + 频次 {bid_size,ask_size,oi,...}
    operator_primitives TEXT,       -- JSON: 用到的算子原语 + 频次 {ratio,diff,rank,log,tanh,ring,ewma,...}
    complexity         TEXT,        -- 粗档: trivial/simple/moderate/complex(按 node_count+primitives 种类)
    source_formula     TEXT,        -- 原始 frontmatter formula(原始保留,审计用)
    source_file        TEXT,        -- .h 文件路径
    extracted_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fs_canonical_hash ON factor_structure(canonical_hash);
CREATE INDEX IF NOT EXISTS idx_fs_template_hash  ON factor_structure(template_hash);
CREATE INDEX IF NOT EXISTS idx_fs_complexity     ON factor_structure(complexity);

-- ============ factor_operator_usage（因子用到的算子, R3 operator 通道）============
-- 因子级 × 算子级交叉表:某因子用到了哪些 operators 表里的算子(role + 次数)。
-- R3 search_factor_realizations 的 operator 通道:同 operator family = 撞族信号。
-- 数据源:factor_structure 提取后(或人工/agent 标注)回填。xname/op_id 都不强 FK(含未入库)。
CREATE TABLE IF NOT EXISTS factor_operator_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    xname       TEXT NOT NULL,
    op_id       INTEGER,
    op_role     TEXT,                  -- 算子在因子里扮演的角色(主变换/门控/归一化/...)
    use_count   INTEGER DEFAULT 1,
    note        TEXT,
    UNIQUE(xname, op_id, op_role),
    FOREIGN KEY (xname) REFERENCES factors(xname),
    FOREIGN KEY (op_id)  REFERENCES operators(op_id)
);
CREATE INDEX IF NOT EXISTS idx_fou_xname ON factor_operator_usage(xname);
CREATE INDEX IF NOT EXISTS idx_fou_opid  ON factor_operator_usage(op_id);

-- ============ operator_capability_index（算子能力索引, R2 检索主体）============
-- 算子级 capability 派生索引:从 operators 抽 carrier/measurement_object/temporal_requirement 等。
-- R2 search_operator_closure:SQL 硬过滤(carrier/temporal/observable)+ vec rerank(distinction)。
-- 一算子一行。operators 空时此表空(R2 降级为"仅标准静态闭包")。
CREATE TABLE IF NOT EXISTS operator_capability_index (
    op_id                       INTEGER PRIMARY KEY,
    op_name                     TEXT,
    carrier_type                TEXT,    -- scalar_field/event_sequence/book_shape/episode/phase/...
    measurement_object          TEXT,    -- 被测对象(episode/phase/depth_shape/imbalance/...)
    measurement_property        TEXT,    -- 被测属性(concentration/asymmetry/persistence/...)
    input_role_signature        TEXT,    -- JSON: 输入语义角色 [thrust_direction, opposing_resource,...]
    output_role                 TEXT,    -- 输出语义角色
    temporal_requirement        TEXT,    -- static/ordered/cross_section/event_driven
    cross_section_requirement   TEXT,
    pair_requirement            TEXT,
    observable_requirements     TEXT,    -- JSON: 需要的可观测能力 [timestamped_scalar_sequence,...]
    invariance                  TEXT,    -- JSON: 不变性属性
    updated_ts                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (op_id) REFERENCES operators(op_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS operator_capability_vec USING vec0(
    op_id    INTEGER PRIMARY KEY,
    embedding FLOAT[768]
);
CREATE INDEX IF NOT EXISTS idx_oci_carrier  ON operator_capability_index(carrier_type);
CREATE INDEX IF NOT EXISTS idx_oci_object  ON operator_capability_index(measurement_object);
CREATE INDEX IF NOT EXISTS idx_oci_temporal ON operator_capability_index(temporal_requirement);

-- ============ factor_research_state（因子研究态, R1 检索主体）============
-- 一因子一行:这个 Factor 作为 Research Object 被认知协议研究过多少次。
-- 区分 Factor Product State(factors.status) vs Factor Research State(本表)。
-- 数据源:从 ideas/factor_lineage_edges/lessons 聚合。R1 select_research_object 用 exhaustion_score 选下一只。
CREATE TABLE IF NOT EXISTS factor_research_state (
    xname                       TEXT PRIMARY KEY,
    times_selected              INTEGER NOT NULL DEFAULT 0,
    last_selected_ts            TIMESTAMP,
    cognitive_attempts          INTEGER NOT NULL DEFAULT 0,
    contradicticts_count        INTEGER NOT NULL DEFAULT 0,
    consistent_count            INTEGER NOT NULL DEFAULT 0,
    insufficient_count          INTEGER NOT NULL DEFAULT 0,
    out_of_domain_count         INTEGER NOT NULL DEFAULT 0,
    factor_iteration_count      INTEGER NOT NULL DEFAULT 0,
    operator_gap_count          INTEGER NOT NULL DEFAULT 0,
    new_operator_count          INTEGER NOT NULL DEFAULT 0,
    successful_child_count      INTEGER NOT NULL DEFAULT 0,
    dead_end_child_count        INTEGER NOT NULL DEFAULT 0,
    open_idea_count             INTEGER NOT NULL DEFAULT 0,
    research_exhaustion_score   REAL NOT NULL DEFAULT 0.0,  -- 0-1, 越高越耗尽
    last_outcome                TEXT,    -- NEW_OPERATOR/FACTOR_ITERATION/INSUFFICIENT/CONSISTENT/OOD
    last_updated_ts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (xname) REFERENCES factors(xname)
);
CREATE INDEX IF NOT EXISTS idx_frs_exhaustion ON factor_research_state(research_exhaustion_score);
CREATE INDEX IF NOT EXISTS idx_frs_last_sel   ON factor_research_state(last_selected_ts);

-- ============ factor_evidence_rollup（因子证据聚合, R4 + S1 evidence_view）============
-- factor_ic_daily → Agent readable summary(几十行,非几千行 raw IC)。
-- R4 search_behavior_neighbors + S1 evidence_view(rollup 替代逐日 IC JOIN)。
-- 多 slice_type:FULL/RECENT/SYMBOL/REGIME/FEED。
CREATE TABLE IF NOT EXISTS factor_evidence_rollup (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_xname        TEXT NOT NULL,
    symbol              TEXT,
    freq                TEXT,
    y_horizon           INTEGER,
    slice_type          TEXT NOT NULL CHECK(slice_type IN ('FULL','RECENT','YEAR','SYMBOL','REGIME','FEED')),
    slice_key           TEXT,            -- 具体键(RECENT=最近N天 / REGIME=regime名 / FEED=main|sub)
    n                   INTEGER,
    ic_mean             REAL,
    ic_std              REAL,
    icir                REAL,
    positive_ratio      REAL,
    ic_median           REAL,
    ic_q10              REAL,
    ic_q90              REAL,
    start_date          TEXT,
    end_date            TEXT,
    source_eval_id      INTEGER,
    computed_ts         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(factor_xname, symbol, freq, y_horizon, slice_type, slice_key),
    FOREIGN KEY (factor_xname) REFERENCES factors(xname),
    FOREIGN KEY (source_eval_id) REFERENCES factor_evals(id)
);
CREATE INDEX IF NOT EXISTS idx_fer_factor ON factor_evidence_rollup(factor_xname);
CREATE INDEX IF NOT EXISTS idx_fer_scene  ON factor_evidence_rollup(symbol, freq, y_horizon);

-- ============ library_map（全库聚合视图, R1 选 Research Object 用）============
-- 全库 coverage 索引:按 status/structure_family 聚合因子数 + dead_end/success 密度。
-- 不是 prompt 背景,是 Step 0 检索索引——让 selector 对 100% 因子库有覆盖意识。
CREATE VIEW IF NOT EXISTS library_map AS
SELECT
    f.status                                              AS status,
    COALESCE(fs.complexity, 'unknown')                    AS structure_family,
    COUNT(DISTINCT f.xname)                               AS total_factors,
    COUNT(DISTINCT CASE WHEN f.status='dead_end' THEN f.xname END)  AS dead_end_count,
    COUNT(DISTINCT CASE WHEN f.status='evaluated' THEN f.xname END) AS evaluated_count,
    COUNT(DISTINCT l_de.id)                               AS dead_end_lesson_count,
    COUNT(DISTINCT l_su.id)                               AS success_lesson_count
FROM factors f
LEFT JOIN factor_structure fs ON fs.xname = f.xname
LEFT JOIN lessons l_de ON l_de.factor_xname = f.xname AND l_de.type='dead_end' AND l_de.deprecated_at IS NULL
LEFT JOIN lessons l_su ON l_su.factor_xname = f.xname AND l_su.type='success_pattern' AND l_su.deprecated_at IS NULL
WHERE f.deprecated_at IS NULL
GROUP BY f.status, COALESCE(fs.complexity, 'unknown');

-- ============ factor_lineage_branches（root 视角分支画像）============
-- Root = 没有非自身祖先的因子。闭包包含 depth-0 self path，所以孤立项也成为一个
-- 单节点 branch。该视图是派生读模型，真实来源仍是 factors + suggestions + lineage edges。
CREATE VIEW IF NOT EXISTS factor_lineage_branches AS
WITH roots AS (
    SELECT f.xname AS root_xname
    FROM factors f
    WHERE f.deprecated_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM factor_lineage_paths p
          WHERE p.descendant_xname = f.xname
            AND p.ancestor_xname <> f.xname
      )
),
members AS (
    SELECT p.ancestor_xname AS root_xname,
           p.descendant_xname AS member_xname,
           p.min_depth AS member_depth
    FROM factor_lineage_paths p
    JOIN roots r ON r.root_xname = p.ancestor_xname
),
suggestion_stats AS (
    SELECT from_xname,
           SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_suggestion_count,
           MAX(updated_ts) AS last_suggestion_ts
    FROM iteration_suggestions
    GROUP BY from_xname
),
edge_stats AS (
    SELECT parent_xname,
           COUNT(*) AS realized_child_count,
           MAX(created_ts) AS last_edge_ts
    FROM factor_lineage_edges
    GROUP BY parent_xname
),
aggregated AS (
    SELECT m.root_xname,
           COUNT(*) AS member_count,
           MAX(m.member_depth) AS max_depth,
           SUM(CASE WHEN f.status='evaluated' THEN 1 ELSE 0 END) AS evaluated_count,
           SUM(CASE WHEN f.status='dead_end' THEN 1 ELSE 0 END) AS dead_end_count,
           MAX(f.last_updated_ts) AS last_factor_ts,
           COALESCE(SUM(ss.open_suggestion_count), 0) AS open_suggestion_count,
           MAX(ss.last_suggestion_ts) AS last_suggestion_ts,
           COALESCE(SUM(es.realized_child_count), 0) AS realized_edge_count,
           MAX(es.last_edge_ts) AS last_edge_ts
    FROM members m
    JOIN factors f ON f.xname=m.member_xname AND f.deprecated_at IS NULL
    LEFT JOIN suggestion_stats ss ON ss.from_xname=m.member_xname
    LEFT JOIN edge_stats es ON es.parent_xname=m.member_xname
    GROUP BY m.root_xname
)
SELECT a.root_xname,
       rf.status AS root_status,
       a.member_count,
       a.max_depth,
       a.evaluated_count,
       a.dead_end_count,
       ROUND(CAST(a.dead_end_count AS REAL) / CAST(a.member_count AS REAL), 4) AS dead_end_ratio,
       a.open_suggestion_count,
       a.realized_edge_count,
       MAX(a.last_factor_ts, a.last_suggestion_ts, a.last_edge_ts) AS last_activity_ts
FROM aggregated a
JOIN factors rf ON rf.xname=a.root_xname;

-- ============ schema_version（schema 版本追踪）============
-- 记录库当前结构版本 + 已应用的迁移。migrate(conn) 每步成功后写一行。
-- 新库由 schema.sql 直建到最新结构 → init_db 直接标 CURRENT_VERSION。
-- 老库（无此表 = 史前库，version 0）由 migrate() 幂等补齐 + 标版本。
-- 单一真相：版本链定义在 factor_db/migrations.py（py）与 pipeline-mcp/lib/factor-db.mjs（mjs），
-- 双端 CURRENT 一致性由 test_migrations 断言。
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
