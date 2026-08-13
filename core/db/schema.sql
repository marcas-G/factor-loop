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
    -- 冗余度画像(平台 restest Ridge-SVD, 与 latest_icir 对称的最新一次评估)
    -- 主判据 dLOOCV: >1% 对线性模型显著增量, <0 过拟合, ≈0 无增益
    latest_dloocv_pct REAL,        -- 对线性模型净增益%(Ridge 近似 Lasso 的 LOOCV 下降%)
    latest_r2_x      REAL,         -- X 空间冗余度(别人72因子库解释方差, >0.8 高冗余)
    latest_res_ic    REAL,         -- 去掉库冗余后的增量 IC
    created_ts       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_ts  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deprecated_at    TIMESTAMP,
    emb_generated_at TIMESTAMP,
    angle_code       TEXT,         -- 信息角度元层标注(见 angle_ontology)
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
    operator_chain           TEXT,        -- 算子链 JSON（与 angleontology 血缘）
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
    angle_code                TEXT,        -- 信息角度(explore 产时标;因子 angle_code 从这继承血缘,不靠关键词)
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
    status      TEXT NOT NULL DEFAULT 'realized',
    iterable    INTEGER NOT NULL DEFAULT 1,
    op_id       INTEGER,                 -- v12: 本次迭代用的算子(算子库主体)。可空=非算子迭代(参数调整等)
    FOREIGN KEY (from_xname) REFERENCES factors(xname),
    FOREIGN KEY (to_xname)   REFERENCES factors(xname),
    FOREIGN KEY (idea_id)    REFERENCES ideas(id),
    FOREIGN KEY (op_id)      REFERENCES operators(op_id)
);

CREATE INDEX IF NOT EXISTS idx_iter_from ON iterations(from_xname);
CREATE INDEX IF NOT EXISTS idx_iter_to   ON iterations(to_xname);
CREATE INDEX IF NOT EXISTS idx_iter_idea ON iterations(idea_id);
CREATE INDEX IF NOT EXISTS idx_iter_op   ON iterations(op_id);

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

-- ============ angle_candidates（angle 自发现候选记录,防归纳循环）============
-- meta-angle-discoverer 产候选 → proposed;reviewer accept → accepted(并 addAngle 入 angle_ontology);
-- reject → rejected(reject_reason)。下次 meta-angle-discoverer 查 rejected 已试维度,避免重产相似。
CREATE TABLE IF NOT EXISTS angle_candidates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL,
    field_family      TEXT,
    extraction        TEXT,
    signal_target     TEXT,
    theory_axiom      TEXT,
    description       TEXT,
    novelty_argument  TEXT,
    trigger_angle     TEXT,                -- 从哪个 saturated 角度归纳(book_imbalance 等)
    status            TEXT NOT NULL CHECK(status IN ('proposed','accepted','rejected')),
    reject_reason     TEXT,                -- reviewer reject reason(reskin/weak_support/ungrounded)
    nearest_existing  TEXT,                -- reviewer 说最像的现有角度
    tried_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ac_status ON angle_candidates(status);

-- ============ 算子库 v12（算子为主体，因子为应用实例）============
-- 算子 = 从因子故事里抽取的可复用测量方法（如"对手吸收"/"弹性变化"）。
-- 算子是主体：定义纯抽象（不绑具体因子/基底），可配任何基底复用。
-- 因子是算子的应用实例（记在 iterations.op_id：在故事节点 from 上用算子 op 产出 to）。
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
-- 数据源:从 ideas/iterations/lessons 聚合。R1 select_research_object 用 exhaustion_score 选下一只。
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
-- 全库 coverage 索引:按 status/angle/field_family/structure_family 聚合因子数 + dead_end/success 密度。
-- 不是 prompt 背景,是 Step 0 检索索引——让 selector 对 100% 因子库有覆盖意识。
-- 普通因子 angle_code 推断后可用;structure_family 从 factor_structure.complexity 粗分(细粒度待结构族聚类)。
CREATE VIEW IF NOT EXISTS library_map AS
SELECT
    f.status                                              AS status,
    f.angle_code                                          AS angle_code,
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
GROUP BY f.status, f.angle_code, COALESCE(fs.complexity, 'unknown');

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

