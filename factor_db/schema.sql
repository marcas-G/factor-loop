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
    latest_ic        REAL,
    latest_icir      REAL,
    latest_sharpe    REAL,
    latest_rank_ic   REAL,
    created_ts       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_ts  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deprecated_at    TIMESTAMP,
    emb_generated_at TIMESTAMP,
    angle_code       TEXT          -- 信息角度元层标注(见 angle_ontology)
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
    seven_dim           TEXT,
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

-- ============ iterations（迭代关系）============
CREATE TABLE IF NOT EXISTS iterations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_xname  TEXT NOT NULL,
    to_xname    TEXT NOT NULL,
    idea_id     INTEGER,
    change_note TEXT,
    reason      TEXT,
    outcome     TEXT CHECK (outcome IN ('improved','declined','neutral')),
    icir_delta  REAL,
    ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_xname) REFERENCES factors(xname),
    FOREIGN KEY (to_xname)   REFERENCES factors(xname),
    FOREIGN KEY (idea_id)    REFERENCES ideas(id)
);

CREATE INDEX IF NOT EXISTS idx_iter_from ON iterations(from_xname);
CREATE INDEX IF NOT EXISTS idx_iter_to   ON iterations(to_xname);
CREATE INDEX IF NOT EXISTS idx_iter_idea ON iterations(idea_id);

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
    freq         TEXT,
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
    freq                TEXT NOT NULL,
    y_horizon           INTEGER NOT NULL,
    date                TEXT NOT NULL,
    ic                  REAL,
    PRIMARY KEY (factor_xname, symbol, freq, y_horizon, date),
    FOREIGN KEY (factor_xname) REFERENCES factors(xname)
);

CREATE INDEX IF NOT EXISTS idx_ic_daily_scene ON factor_ic_daily(symbol, freq, y_horizon, date);

-- ============ pattern_cards（归纳引擎：模式卡实体）============
-- 统计扫描发现的异常模式。7 维坐标(F/T/C/S/Y/H/R)+ 统计证据 + 生命周期。
-- 生命周期：raw(扫描产)→audited(过审计)→archived(入库)→explained(→idea)/absorbed(→模型)/deprecated。
-- 层级：模式卡 →(hypothesis-generator 解释)→ idea →(brainstorm 实现)→ 因子。模式卡是 idea 的上游。
-- archived 高优先卡自动喂 hypothesis-generator(衔接①出);因子→模型→残差→重扫(衔接②入)。
CREATE TABLE IF NOT EXISTS pattern_cards (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    f_feature         TEXT NOT NULL,          -- F 特征:ofi/imb/depth_slope/...
    t_transform       TEXT NOT NULL,          -- T 变换:level/ts_quantile/delta/...
    c_condition       TEXT,                   -- C 条件:类型化 JSON {"vol_regime":"high"},null=无条件
    s_structure       TEXT NOT NULL,          -- S 模式结构:upper_tail/threshold_break/...  ★覆盖地图 p 维
    y_target          TEXT NOT NULL,          -- Y 目标:raw_return/model_residual/...
    h_horizon         INTEGER NOT NULL,       -- H 预测周期秒:1/5/10/60/300
    r_reference       TEXT,                   -- R 基准:self_history/cross_contract/model_prediction
    strength          REAL,
    significance      REAL,
    n_samples         INTEGER,
    stability         REAL,
    evidence          TEXT,                   -- 完整证据 JSON(分位轮廓/路径/条件切片)
    status            TEXT NOT NULL CHECK (status IN
                      ('raw','audited','archived','explained','absorbed','deprecated')),
    detected_by       TEXT,
    detected_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    audit_result      TEXT,                   -- 审计详情 JSON(多重检验校正/泄漏检查)
    idea_id           INTEGER,               -- explained → 指向 ideas.id
    absorbed_by_model TEXT,
    priority          REAL,                   -- archived 时算:strength×significance×novelty×residual_coverage
    mutated_from      INTEGER,               -- 变异树父 pattern_cards.id
    FOREIGN KEY (idea_id)      REFERENCES ideas(id),
    FOREIGN KEY (mutated_from) REFERENCES pattern_cards(id)
);
CREATE INDEX IF NOT EXISTS idx_pc_status ON pattern_cards(status);
CREATE INDEX IF NOT EXISTS idx_pc_scene  ON pattern_cards(s_structure, y_target, h_horizon);
CREATE INDEX IF NOT EXISTS idx_pc_feed   ON pattern_cards(status, priority) WHERE status='archived';

-- ============ pattern_dims（七维受控词表）============
-- 模式空间领土的经纬度。F/T/C/S/Y/R 受控取值(H 是整数不限)。预填盘口域化值。
CREATE TABLE IF NOT EXISTS pattern_dims (
    dim         TEXT NOT NULL,                -- 'F'/'T'/'C'/'S'/'Y'/'R'
    value       TEXT NOT NULL,
    description TEXT,
    PRIMARY KEY (dim, value)
);

-- ============ pattern_coverage（模式空间覆盖地图 C[f,s,y,h]）============
-- 归纳引擎主覆盖地图(模式空间领土探索记录)。任务生成器看它决定扫哪。
-- 与因子层 coverage_map VIEW 并存——两层语义不同(模式卡 vs 因子)。
CREATE TABLE IF NOT EXISTS pattern_coverage (
    f_feature         TEXT NOT NULL,
    s_structure       TEXT NOT NULL,
    y_target          TEXT NOT NULL,
    h_horizon         INTEGER NOT NULL,
    searched_count    INTEGER DEFAULT 0,      -- raw+audited+archived 总试过
    archived_count    INTEGER DEFAULT 0,      -- 过审计入库
    explained_count   INTEGER DEFAULT 0,      -- 已成 idea
    avg_strength      REAL,
    last_searched_at  TIMESTAMP,
    PRIMARY KEY (f_feature, s_structure, y_target, h_horizon)
);

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
-- id 类型: factors 存 xname(TEXT)，axioms/ideas/lessons/observe_outputs 存 integer id 字符串。
-- 边类型:
--   CONTRADICTS    矛盾（推理燃料: observe 实测 vs axiom 理论预期；resolve_contradiction 触发）
--   DERIVES_FROM   推导来源（idea 从 axiom/derived 推出）
--   INSTANTIATES   实例化（factor 是 idea 的可测实现）
--   SPECIALIZES    特化（idea 是另一 idea 的更窄形式 / factor 演化）
--   ORTHOGONAL_TO  正交（两信息源不应冗余）
--   SUPPORTS       支持（evidence 支撑 idea）
--   REFUTES        反驳（refutation 击破 idea）
CREATE TABLE IF NOT EXISTS graph_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_table  TEXT NOT NULL,                     -- 'axioms'/'ideas'/'factors'/'lessons'/'observe_outputs'
    from_id     TEXT NOT NULL,                     -- factors 存 xname；其余存 integer id 字符串
    to_table    TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    edge_type   TEXT NOT NULL CHECK (edge_type IN
                ('CONTRADICTS','DERIVES_FROM','INSTANTIATES','SPECIALIZES',
                 'ORTHOGONAL_TO','SUPPORTS','REFUTES','BOUNDS')),
    weight      REAL,                              -- CONTRADICTS=矛盾显著性/SUPPORTS=IC强度/REFUTES=反驳强度/SPECIALIZES=|icir_delta|
    properties  TEXT,                              -- JSON: {"observe_script":..,"resolved_by":idea_id,"role":..,"via":..}
    created_ts  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_table, from_id, to_table, to_id, edge_type)   -- 幂等：同四元组+类型不重复
);
CREATE INDEX IF NOT EXISTS idx_edges_from      ON graph_edges(from_table, from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to        ON graph_edges(to_table, to_id);
CREATE INDEX IF NOT EXISTS idx_edges_type      ON graph_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_type_from ON graph_edges(edge_type, from_table, from_id);

-- ============ observe_outputs（知识图 · EVIDENCE 层：理论违反型观测）============
-- observe 脚本产出的"理论预期 vs 实测"矛盾证据。CONTRADICTS 边的 from 端载体。
-- 独立于 lessons（lessons 只装因子实验 dead_end/success，factor_xname NOT NULL；observe 无具体因子）。
-- 每个 observe 输出匹配一个 axiom_code：违反理论预期 → CONTRADICTS 边 (observe_outputs.id → axioms.id)。
CREATE TABLE IF NOT EXISTS observe_outputs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    script       TEXT NOT NULL,                    -- 'observe_autocorrelation'/'observe_microstructure'...
    axiom_code   TEXT NOT NULL,                    -- 对应公理 code（软引用 axioms.code，不加外键）
    violation    TEXT NOT NULL,                    -- 违反字段/类型: 'roll_bounce_signature=False'
    summary      TEXT,                             -- 一句话总结
    evidence     TEXT,                             -- 完整 observe 输出 JSON
    symbol       TEXT,                             -- 品种（如 SHFE-AG）
    detected_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_observe_axiom ON observe_outputs(axiom_code);
CREATE INDEX IF NOT EXISTS idx_observe_script ON observe_outputs(script);

-- ============ angle_ontology（信息角度元层：数据→提取角度字典）============
-- 让 graph-engine 感知"哪些信息角度被探索/饱和/未探索",自动换角度(不靠人喂)。
-- 角度 = 字段族 × 提取结构。factors.angle_code 标注每因子属哪角度。
-- 覆盖度(query_angle_coverage)聚合每角度的因子数/dead_end/饱和度,驱动 explore_uncovered_angle。
CREATE TABLE IF NOT EXISTS angle_ontology (
    code          TEXT PRIMARY KEY,           -- 'book_imbalance'/'depth_shape'/...
    name          TEXT NOT NULL,
    field_family  TEXT NOT NULL,              -- size/add_cancel/volume/turnover/oi/mid/price/time
    extraction    TEXT NOT NULL,               -- 截面差/分布矩/时间聚类/时序存活/游程/异常/水平动量
    signal_target TEXT,                        -- 方向/流动性/冲击/意图/状态/资金事件
    theory_axiom  TEXT,                        -- 关联 axiom code(软引用 axioms.code)
    description   TEXT
);
CREATE INDEX IF NOT EXISTS idx_angle_family ON angle_ontology(field_family);

