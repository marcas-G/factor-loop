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
    emb_generated_at TIMESTAMP
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

