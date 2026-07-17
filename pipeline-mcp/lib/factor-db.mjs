// Factor DB Node.js 客户端（镜像 factor_db/db.py）
//
// 用法:
//   import { init, addFactorFromHFile, addEval, addLesson } from "./factor-db.mjs";
//   init();
//   addFactorFromHFile("factors/Foo.h", ideaId=1);
//
// 加载 vec0 扩展后, factors_vec 虚拟表可直接读写。

import { DatabaseSync } from "node:sqlite";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

// 仓库根 = pipeline-mcp 的上一级(自动跟随 clone 位置)
const CWD = path.resolve(import.meta.dirname, "../..");  // 项目根(对齐 Python db.py DB_PATH + factor_db/ 脚本目录)
const DB_PATH = path.join(CWD, "factors.db");
// 所有 python 调用统一走独立 venv（系统 python3 缺 sqlite_vec）
const VENV_PY = process.env.QUANT_VENV_PY || "/home/lgao/quant-venv/bin/python";
const PY = fs.existsSync(VENV_PY) ? VENV_PY : "python3";
const VEC0_SO = findVec0So();

// status 取值（与 schema.sql CHECK 约束一致）
const VALID_STATUS = ["draft", "submitted", "evaluated", "failed", "dead_end"];
const VALID_LESSON_TYPE = ["dead_end", "success_pattern"];
const VALID_LESSON_SCOPE = ["factor"];

// angle_code 自动推断(从 formula/tags/xname 关键词 → angle_ontology code)。与 db.py infer_angle_code 双端一致。
const _ANGLE_KEYWORDS = [
  ["book_imbalance",       ["imbalance", "imb", "bsi", "ofi"]],
  ["add_cancel_imbalance", ["cancel_imb", "add_imb", "add_cancel_imb"]],
  ["add_cancel_pattern",   ["spoof", "layering", "cancel_pattern", "add_pattern"]],
  ["depth_shape",          ["depth_shape", "entropy", "skew", "hhi", "conc"]],
  ["depth_slope",          ["depth_slope", "book_slope", "slope"]],
  ["spread_structure",     ["spread", "bid_ask_spread"]],
  ["trade_imbalance",      ["trade_imb", "volume_imb", "tvi"]],
  ["trade_rhythm",         ["hawkes", "burst", "rhythm", "cluster"]],
  ["intensity_level",      ["intensity", "turnover", "active"]],
  ["volatility_regime",    ["vol_regime", "volatility", "vol_gate", "volregime", "vol burst", "vol regime"]],
  ["price_microstructure", ["microstructure", "roll", "autocorr"]],
  ["oi_anomaly",           ["oi_", "oi ", "open_interest", "oipersist", "oiresist", "oispike", "oiintensity"]],
];
function inferAngleCode(formula, tags, xname) {
  const text = [formula, ...(tags || []), xname].filter(Boolean).join(" ").toLowerCase();
  for (const [code, keywords] of _ANGLE_KEYWORDS) {
    if (keywords.some((kw) => text.includes(kw))) return code;
  }
  return null;
}

let _CONSTANTS = null;
function graphConstants() {
  // db.py 与 factor-db.mjs 共读 factor_db/graph_constants.json → 判据一处,防双端漂移
  if (_CONSTANTS === null) {
    _CONSTANTS = JSON.parse(fs.readFileSync(path.join(CWD, "factor_db", "graph_constants.json"), "utf-8"));
  }
  return _CONSTANTS;
}

let _db = null;

function findVec0So() {
  // 探测常见路径
  const candidates = [
    "/usr/lib/python3.9/site-packages/sqlite_vec/vec0.so",
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  // 用 venv python 探测
  try {
    const out = execSync(
      `${PY} -c "import sqlite_vec, os; print(os.path.join(os.path.dirname(sqlite_vec.__file__), 'vec0.so'))"`,
      { encoding: "utf8" }
    ).trim();
    if (fs.existsSync(out)) return out;
  } catch {}
  throw new Error("找不到 sqlite_vec/vec0.so，请先 pip install sqlite-vec");
}

// schema 版本追踪(与 factor_db/migrations.py 对齐;双端 CURRENT 一致性由 test_migrations 断言)。
// 版本里程碑 = py MIGRATIONS 的 name;现有 migrate* 已把结构补齐到最新 → 记录完整版本链。
const CURRENT_SCHEMA_VERSION = 6;
const SCHEMA_MILESTONES = [
  [1, "baseline"],
  [2, "graph_core"],
  [3, "graph_bounds"],
  [4, "angle"],
];

function migrateSchemaVersion() {
  // 空库(连 factors 都没有)由 py init_db 负责,mjs 不处理;只给已有数据的库记录版本。
  const fcols = _db.prepare("PRAGMA table_info(factors)").all();
  if (fcols.length === 0) return;
  _db.exec(`CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY, name TEXT NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)`);
  const row = _db.prepare("SELECT MAX(version) AS v FROM schema_version").get();
  if (!row || row.v == null) {
    // 史前库首次纳入版本管理:migrate* 已补齐结构 → 记录完整版本链到 CURRENT。
    const ins = _db.prepare("INSERT OR IGNORE INTO schema_version (version, name) VALUES (?, ?)");
    for (const [v, name] of SCHEMA_MILESTONES) ins.run(v, name);
  }
}

export function init({ dbPath = DB_PATH } = {}) {
  if (_db) return _db;
  _db = new DatabaseSync(dbPath, { allowExtension: true });
  _db.loadExtension(VEC0_SO);
  _db.exec("PRAGMA foreign_keys = ON");
  _db.exec("PRAGMA journal_mode = WAL");
  _db.exec("PRAGMA busy_timeout = 5000");
  migrateLessonsSchema();
  migrateIterationsSchema();
  migrateIdeasSchema();
  migrateCoverageView();
  migrateFactorIcDaily();
  migratePatternCards();
  migrateGraphSchema();
  migrateSchemaVersion();
  migrateQualitySchema();
  return _db;
}

// 知识图表结构幂等迁移：axioms / graph_edges + ideas.node_layer。
// 新库由 schema.sql 直接建；此函数给已存在的库在线补齐。与 db.py ensure_graph_schema 对齐。
function migrateGraphSchema() {
  const fcols = _db.prepare("PRAGMA table_info(factors)").all();
  if (fcols.length === 0) return; // 空库,schema.sql 尚未跑,跳过
  _db.exec(`
    CREATE TABLE IF NOT EXISTS axioms (
      id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
      category TEXT NOT NULL, statement TEXT NOT NULL, formal_form TEXT,
      expected_signature TEXT, source TEXT, falsifiable TEXT,
      created_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_axioms_category ON axioms(category);
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
    CREATE INDEX IF NOT EXISTS idx_edges_from      ON graph_edges(from_table, from_id);
    CREATE INDEX IF NOT EXISTS idx_edges_to        ON graph_edges(to_table, to_id);
    CREATE INDEX IF NOT EXISTS idx_edges_type      ON graph_edges(edge_type);
    CREATE INDEX IF NOT EXISTS idx_edges_type_from ON graph_edges(edge_type, from_table, from_id);
  `);
  // ideas.node_layer 列幂等加
  const icols = _db.prepare("PRAGMA table_info(ideas)").all().map((c) => c.name);
  if (icols.length > 0 && !icols.includes("node_layer")) {
    _db.exec("ALTER TABLE ideas ADD COLUMN node_layer TEXT DEFAULT 'HYPOTHESIS'");
  }
  migrateGraphEdgeBounds();
  migrateAngleSchema();
}

// graph_edges.edge_type CHECK 加 'BOUNDS'(SQLite 不能改 CHECK,需重建表)。幂等。
function migrateGraphEdgeBounds() {
  const row = _db.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_edges'").get();
  if (!row || !row.sql || row.sql.includes("BOUNDS")) return;
  _db.exec(`
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
  `);
}

// lessons 表 schema 迁移：旧版 5 种 type + 3 种 scope → 新版 2 种 type + 仅 factor scope
// idempotent：检测旧 CHECK 约束存在才执行，重建表会清空数据
function migrateLessonsSchema() {
  const row = _db.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='lessons'").get();
  if (!row || !row.sql) return;
  if (!row.sql.includes("next_direction")) return; // 新 schema，无需迁移

  _db.exec("DROP TRIGGER IF EXISTS lessons_fts_ai");
  _db.exec("DROP TRIGGER IF EXISTS lessons_fts_ad");
  _db.exec("DROP TRIGGER IF EXISTS lessons_fts_au");
  _db.exec("DROP TABLE IF EXISTS lessons_fts");
  _db.exec("DROP TABLE IF EXISTS lessons");
  _db.exec(`
    CREATE TABLE lessons (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      type          TEXT NOT NULL CHECK (type IN ('dead_end','success_pattern')),
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
    CREATE INDEX idx_lessons_type_scope ON lessons(type, scope);
    CREATE INDEX idx_lessons_factor     ON lessons(factor_xname);
    CREATE INDEX idx_lessons_idea       ON lessons(idea_id);
    CREATE VIRTUAL TABLE lessons_fts USING fts5(
      text, content='lessons', content_rowid='rowid', tokenize='trigram'
    );
    CREATE TRIGGER lessons_fts_ai AFTER INSERT ON lessons BEGIN
      INSERT INTO lessons_fts(rowid, text) VALUES (new.rowid, new.text);
    END;
    CREATE TRIGGER lessons_fts_ad AFTER DELETE ON lessons BEGIN
      INSERT INTO lessons_fts(lessons_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    END;
    CREATE TRIGGER lessons_fts_au AFTER UPDATE ON lessons BEGIN
      INSERT INTO lessons_fts(lessons_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
      INSERT INTO lessons_fts(rowid, text) VALUES (new.rowid, new.text);
    END;
  `);
  console.log("[factor-db] lessons 表已迁移到新 schema（type ∈ {dead_end, success_pattern}，scope 固定 factor，旧数据已清空）");
}

// iterations 表加 status/iterable 列（幂等）。
// to_xname 是 NOT NULL，open/in_progress 用自指占位（to=from_xname），status 作唯一状态判据。
// 演进树链查询只看 status='realized'，自指的 open/in_progress 行不参与（否则递归 CTE 死循环）。
function migrateIterationsSchema() {
  const cols = _db.prepare("PRAGMA table_info(iterations)").all().map((c) => c.name);
  if (cols.length === 0) return; // 表不存在(全新库,schema.sql 尚未跑),跳过
  if (!cols.includes("status")) {
    _db.exec("ALTER TABLE iterations ADD COLUMN status TEXT NOT NULL DEFAULT 'realized'");
  }
  if (!cols.includes("iterable")) {
    _db.exec("ALTER TABLE iterations ADD COLUMN iterable INTEGER NOT NULL DEFAULT 1");
  }
}

// ideas 表加论证链 + 支持度列（幂等迁移，给已存在的库补列）。
// argument_chain: 必然假设的结构化论证链 JSON
// support_score/evaluated_factor_count/support_score_computed_at: 假设级连续支持度（阶段2聚合）
function migrateIdeasSchema() {
  const cols = _db.prepare("PRAGMA table_info(ideas)").all().map((c) => c.name);
  if (cols.length === 0) return; // 表不存在(全新库,schema.sql 尚未跑),跳过
  if (!cols.includes("argument_chain")) {
    _db.exec("ALTER TABLE ideas ADD COLUMN argument_chain TEXT");
  }
  if (!cols.includes("support_score")) {
    _db.exec("ALTER TABLE ideas ADD COLUMN support_score REAL");
  }
  if (!cols.includes("evaluated_factor_count")) {
    _db.exec("ALTER TABLE ideas ADD COLUMN evaluated_factor_count INTEGER NOT NULL DEFAULT 0");
  }
  if (!cols.includes("support_score_computed_at")) {
    _db.exec("ALTER TABLE ideas ADD COLUMN support_score_computed_at TIMESTAMP");
  }
  if (!cols.includes("necessity_grade")) {
    _db.exec("ALTER TABLE ideas ADD COLUMN necessity_grade TEXT");
  }
}

// 覆盖地图 VIEW(幂等)。factors 表不存在则跳过(空库首次 init)——VIEW 依赖 factors/evals/ideas。
// coverageMap() 用内联 SQL 自给自足,VIEW 仅供直查/文档;不存在不影响功能。
// 数据源用 factor_ic_vec_meta:addEval 的 symbol/freq 恒为 NULL,真实 symbol/freq 只在 ic 向量表。
function migrateCoverageView() {
  const cols = _db.prepare("PRAGMA table_info(factors)").all();
  if (cols.length === 0) return; // 空库,schema.sql 尚未跑,跳过
  _db.exec(`
    CREATE VIEW IF NOT EXISTS coverage_map AS
    SELECT m.symbol, m.y_horizon, f.status, i.necessity_grade,
           COUNT(DISTINCT f.xname)                                AS searched_count,
           COUNT(DISTINCT CASE WHEN f.status='evaluated' THEN f.xname END) AS evaluated_count,
           COUNT(DISTINCT CASE WHEN f.status='dead_end'  THEN f.xname END) AS dead_end_count,
           AVG(f.latest_icir)                                    AS avg_icir,
           MAX(m.computed_at)                                    AS last_evaluated_ts
    FROM factor_ic_vec_meta m
    JOIN factors f ON f.xname = m.factor_xname
    LEFT JOIN factor_evals e2 ON e2.id = (
      SELECT id FROM factor_evals WHERE factor_xname = f.xname ORDER BY ts DESC LIMIT 1
    )
    LEFT JOIN ideas i ON i.id = e2.idea_id
    GROUP BY m.symbol, m.y_horizon, f.status, i.necessity_grade
  `);
}

// factor_ic_daily 表(幂等)。存原始日级 IC 序列(归一化前),供 residual_ic_strength 正交用。
// refresh_factor_ic_vectors.py 写入。factors 表不存在则跳过(空库)。
function migrateFactorIcDaily() {
  const cols = _db.prepare("PRAGMA table_info(factors)").all();
  if (cols.length === 0) return; // 空库,schema.sql 尚未跑,跳过
  _db.exec(`
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
  `);
}

// 归纳引擎地基:模式卡实体 + 七维受控词表 + 模式空间覆盖地图。
// pattern_cards = 统计扫描发现的异常模式(7 维坐标 + 证据 + 生命周期 raw→audited→archived→explained/absorbed)。
// pattern_dims  = 七维(F/T/C/S/Y/R)受控词表,预填盘口域化取值。
// pattern_coverage = 模式空间覆盖地图 C[f,s,y,h],任务生成器看它决定扫哪(与因子层 coverage_map VIEW 并存)。
// factors 表不存在则跳过(空库)。
function migratePatternCards() {
  const cols = _db.prepare("PRAGMA table_info(factors)").all();
  if (cols.length === 0) return; // 空库,schema.sql 尚未跑,跳过
  _db.exec(`
    CREATE TABLE IF NOT EXISTS pattern_cards (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      f_feature       TEXT NOT NULL,
      t_transform     TEXT NOT NULL,
      c_condition     TEXT,
      s_structure     TEXT NOT NULL,
      y_target        TEXT NOT NULL,
      h_horizon       INTEGER NOT NULL,
      r_reference     TEXT,
      strength        REAL,
      significance    REAL,
      n_samples       INTEGER,
      stability       REAL,
      evidence        TEXT,
      status          TEXT NOT NULL CHECK (status IN ('raw','audited','archived','explained','absorbed','deprecated')),
      detected_by     TEXT,
      detected_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      audit_result    TEXT,
      idea_id         INTEGER,
      absorbed_by_model TEXT,
      priority        REAL,
      mutated_from    INTEGER,
      FOREIGN KEY (idea_id) REFERENCES ideas(id),
      FOREIGN KEY (mutated_from) REFERENCES pattern_cards(id)
    );
    CREATE INDEX IF NOT EXISTS idx_pc_status ON pattern_cards(status);
    CREATE INDEX IF NOT EXISTS idx_pc_scene  ON pattern_cards(s_structure, y_target, h_horizon);
    CREATE INDEX IF NOT EXISTS idx_pc_feed   ON pattern_cards(status, priority) WHERE status='archived';

    CREATE TABLE IF NOT EXISTS pattern_dims (
      dim         TEXT NOT NULL,
      value       TEXT NOT NULL,
      description TEXT,
      PRIMARY KEY (dim, value)
    );

    CREATE TABLE IF NOT EXISTS pattern_coverage (
      f_feature         TEXT NOT NULL,
      s_structure       TEXT NOT NULL,
      y_target          TEXT NOT NULL,
      h_horizon         INTEGER NOT NULL,
      searched_count    INTEGER DEFAULT 0,
      archived_count    INTEGER DEFAULT 0,
      explained_count   INTEGER DEFAULT 0,
      avg_strength      REAL,
      last_searched_at  TIMESTAMP,
      PRIMARY KEY (f_feature, s_structure, y_target, h_horizon)
    );
  `);
  // 预填七维盘口域化受控词表(H 是整数,不入)。幂等。
  const dims = [
    ["F","ofi","订单流不平衡"],["F","imb","订单簿不平衡 bid/ask"],["F","depth_slope","深度斜率"],
    ["F","curvature","曲率"],["F","pressure","买卖压力"],["F","cancel_asym","撤单不对称"],
    ["F","add_asym","挂单不对称"],["F","concentration","集中度"],["F","spoof_imbalance","假单不平衡"],
    ["F","trade_imbalance","成交不平衡"],
    ["T","level","原值"],["T","ts_quantile","自身历史分位"],["T","cross_contract_rank","跨合约排名"],
    ["T","delta","变化"],["T","accel","加速度"],["T","duration","持续时间"],
    ["T","path_shape","路径形态"],["T","dist_struct","分布结构(偏度/峰度/熵)"],
    ["C","vol_regime","波动率 regime"],["C","session","时段(开盘/连续/收盘)"],
    ["C","direction","方向(涨/跌态)"],["C","activity","成交活跃度"],["C","basis_state","基差(升水/贴水)"],
    ["S","monotonic","单调"],["S","upper_tail","上尾异常"],["S","lower_tail","下尾异常"],
    ["S","threshold_break","阈值断裂"],["S","u_shape","U 型"],["S","inv_u_shape","倒 U 型"],
    ["S","sign_flip","符号反转"],["S","cond_amplify","条件增强"],["S","post_event_path","事件后路径"],
    ["S","regime_transition","状态转移"],["S","cross_horizon_nonmonotonic","跨 horizon 非单调"],
    ["S","residual_anomaly","残差异常"],
    ["Y","raw_return","原始收益"],["Y","max_upside","最大上涨"],["Y","max_drawdown","最大回撤"],
    ["Y","up_prob","上涨概率"],["Y","model_residual","模型残差(残差驱动接入点)"],
    ["R","self_history","自身历史"],["R","cross_contract","主力↔次月"],["R","model_prediction","相对已有模型(=残差)"],
  ];
  const ins = _db.prepare("INSERT OR IGNORE INTO pattern_dims (dim, value, description) VALUES (?, ?, ?)");
  for (const [d, v, desc] of dims) ins.run(d, v, desc);
}

function db() {
  if (!_db) init();
  return _db;
}

// ============ factors ============

// 读 .h 文件，fork python parse_frontmatter.py 解析 frontmatter，入库
// 返回写入的 xname；如 .h 无 frontmatter 或解析失败，返回 null
export function addFactorFromHFile(hFilePath, ideaId = null, opts = {}) {
  const status = opts.status || "draft";
  if (!VALID_STATUS.includes(status)) throw new Error(`invalid status: ${status}`);

  let meta;
  try {
    const json = execSync(
      `${PY} -c "import json,sys; sys.path.insert(0,'${CWD}');
from factor_db.parse_frontmatter import parse_frontmatter, extract_class_name, extract_template_default_param;
text = open(sys.argv[1]).read()
m = parse_frontmatter(text) or {}
if 'class_name' not in m:
    m['class_name'] = extract_class_name(text) or ''
if 'params' not in m:
    m['params'] = extract_template_default_param(text) or None
# date/datetime 转 str（YAML 解析 created_ts 为 date 对象）
for k,v in list(m.items()):
    if hasattr(v, 'isoformat'): m[k] = v.isoformat()
print(json.dumps(m, default=str, ensure_ascii=False))" "${hFilePath}"`,
      { encoding: "utf8" }
    ).trim();
    meta = JSON.parse(json);
  } catch (e) {
    console.error(`[factor-db] 解析 frontmatter 失败 ${hFilePath}: ${e.message}`);
    return null;
  }

  if (!meta.xname && !meta.class_name) {
    console.error(`[factor-db] 无法提取 xname/class_name: ${hFilePath}`);
    return null;
  }

  const xname = meta.xname || meta.class_name;
  const conn = db();
  const exists = conn.prepare("SELECT 1 FROM factors WHERE xname = ?").get(xname);
  if (exists) {
    // 已存在则更新 formula/tags（不覆盖 status/latest_*)
    if (meta.formula) {
      conn.prepare(
        `UPDATE factors SET formula_text = ?, last_updated_ts = CURRENT_TIMESTAMP WHERE xname = ?`
      ).run(meta.formula, xname);
    }
    return xname;
  }

  conn.prepare(
    `INSERT INTO factors (xname, class_name, file_path, formula_text, params, status, created_ts)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(
    xname,
    meta.class_name || null,
    path.basename(hFilePath),
    meta.formula || null,
    meta.params ? JSON.stringify(meta.params) : null,
    status,
    meta.created_ts || new Date().toISOString().slice(0, 10)
  );

  if (Array.isArray(meta.tags)) {
    for (const t of meta.tags) addTagBinding(xname, t);
  }
  if (ideaId != null) {
    conn.prepare(
      `INSERT OR IGNORE INTO idea_factor_links (idea_id, factor_xname) VALUES (?, ?)`
    ).run(ideaId, xname);
    // angle_code 回灌(优先 idea 的 properties.angle):
    const a = conn.prepare(
      `SELECT json_extract(properties,'$.angle') AS angle FROM graph_edges
       WHERE from_id=? AND edge_type='DERIVES_FROM'
         AND json_extract(properties,'$.angle') IS NOT NULL LIMIT 1`
    ).get(String(ideaId));
    if (a && a.angle) {
      conn.prepare(`UPDATE factors SET angle_code=? WHERE xname=?`).run(a.angle, xname);
    }
  }
  // angle_code 自动推断(解耦 explore):idea 无 angle 或无 idea 时,从 formula/tags/xname 推断
  const curAngle = conn.prepare("SELECT angle_code FROM factors WHERE xname=?").get(xname);
  if (!curAngle || !curAngle.angle_code) {
    const inferred = inferAngleCode(meta.formula, meta.tags, xname);
    if (inferred) {
      conn.prepare(`UPDATE factors SET angle_code=? WHERE xname=?`).run(inferred, xname);
    }
  }
  return xname;
}

export function updateFactorStatus(xname, status) {
  if (!VALID_STATUS.includes(status)) throw new Error(`invalid status: ${status}`);
  db().prepare(
    `UPDATE factors SET status = ?, last_updated_ts = CURRENT_TIMESTAMP WHERE xname = ?`
  ).run(status, xname);
}

function addTagBinding(xname, tagName) {
  const conn = db();
  conn.prepare(`INSERT OR IGNORE INTO tags (name) VALUES (?)`).run(tagName);
  const row = conn.prepare(`SELECT id FROM tags WHERE name = ?`).get(tagName);
  if (row) {
    conn.prepare(
      `INSERT OR IGNORE INTO factor_tags (factor_xname, tag_id) VALUES (?, ?)`
    ).run(xname, row.id);
  }
}

// 兜底：若 factors.formula_text 为空则从 state 补；tags 逐个绑定。幂等。
// 用于 persistVerdict 在 .h 无 frontmatter（addFactorFromHFile 提取不到）时，
// 保证 formula_text/tags 不缺。新因子入库三件套的"终点兜底"。
export function ensureFormulaTags(xname, formula, tags) {
  if (!xname) return;
  const conn = db();
  if (formula) {
    const row = conn.prepare("SELECT formula_text FROM factors WHERE xname = ?").get(xname);
    if (row && row.formula_text == null) {
      conn.prepare(
        "UPDATE factors SET formula_text = ?, last_updated_ts = CURRENT_TIMESTAMP WHERE xname = ?"
      ).run(formula, xname);
    }
  }
  if (Array.isArray(tags)) {
    for (const t of tags) {
      if (t) addTagBinding(xname, String(t));
    }
  }
}

// 补语义向量：spawn gen_embeddings.py --xname（幂等，读 factors 表 formula+tags+class_name
// 算 bge-small-zh emb 写 factors_vec + emb_generated_at）。
// 失败降级返回 {ok:false}，不抛——emb 不阻塞主入库流程，后续可批量补。
export async function generateEmbedding(xname) {
  if (!xname) return { ok: false, error: "xname 为空" };
  const { runPy } = await import("../infra/run-py.mjs");
  const script = path.join(CWD, "factor_db", "gen_embeddings.py");
  const result = await runPy(script, ["--xname", String(xname)], { timeoutSec: 120 });
  return {
    ok: result.exitCode === 0,
    exitCode: result.exitCode,
    stdout_tail: (result.stdout || "").slice(-300),
    stderr_head: (result.stderr || "").slice(0, 200),
  };
}

// ============ factor_evals ============

// metrics: { ic_mean, icir, sharpe, rank_ic }
// opts: { evalMetrics, conditionalReturns, significant, mode, status }
//   evalMetrics            — 7 维评估的 JSON 对象，存到 factor_evals.eval_metrics
//   conditionalReturns  — deep 分析的条件收益 JSON，存到 factor_evals.conditional_returns
//   significant         — 0/1，外部根据 verdict 决定（不再内部用 ICIR 阈值判断）
//   mode                — eval_mode 字段，默认 full
//   status              — 强制设 factors.status（"evaluated" / "dead_end"），不传则不动 factors 表
export function addEval(xname, ts, metrics, ideaId = null, rawPath = null, opts = {}) {
  const m = metrics || {};
  const conn = db();
  const mode = opts.mode || "full";
  const significant = opts.significant != null ? Number(opts.significant) : 0;
  const evalMetricsJson = opts.evalMetrics ? JSON.stringify(opts.evalMetrics) : null;
  const condRetJson = opts.conditionalReturns ? JSON.stringify(opts.conditionalReturns) : null;

  conn.prepare(
    `INSERT INTO factor_evals
       (factor_xname, idea_id, ts, symbol, freq, ic_mean, icir, sharpe, rank_ic,
        eval_metrics, conditional_returns, eval_mode, significant, raw_path)
     VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    xname, ideaId, ts,
    m.ic_mean ?? null, m.icir ?? null, m.sharpe ?? null, m.rank_ic ?? null,
    evalMetricsJson, condRetJson,
    mode,
    significant,
    rawPath
  );

  // 更新 factors 冗余字段（只在显式给定 status 时才动 status）
  if (opts.status) {
    if (!VALID_STATUS.includes(opts.status)) throw new Error(`invalid status: ${opts.status}`);
    conn.prepare(
      `UPDATE factors SET
         latest_ic = ?, latest_icir = ?, latest_sharpe = ?, latest_rank_ic = ?,
         last_updated_ts = ?, status = ?
       WHERE xname = ?`
    ).run(
      m.ic_mean ?? null, m.icir ?? null, m.sharpe ?? null, m.rank_ic ?? null,
      ts, opts.status, xname
    );
  } else {
    conn.prepare(
      `UPDATE factors SET
         latest_ic = ?, latest_icir = ?, latest_sharpe = ?, latest_rank_ic = ?,
         last_updated_ts = ?
       WHERE xname = ?`
    ).run(
      m.ic_mean ?? null, m.icir ?? null, m.sharpe ?? null, m.rank_ic ?? null,
      ts, xname
    );
  }
}

// ============ iterations ============

export function addIteration(fromXname, toXname, ideaId = null, changeNote = null, outcome = null, icirDelta = null) {
  db().prepare(
    `INSERT INTO iterations (from_xname, to_xname, idea_id, change_note, outcome, icir_delta)
     VALUES (?, ?, ?, ?, ?, ?)`
  ).run(fromXname, toXname, ideaId, changeNote, outcome, icirDelta);
}

// ===== 迭代管道: open(待接续) → in_progress(已接续成候选B) → realized(B跑完归档) =====
// evaluate 开建议(pass 精进 / dead_end 显式重试);brainstorm 检索 open 并接续成 B;
// B 的 evaluate 完成后 realize,iterations 表就此长出 from→to 演进链。
// to_xname NOT NULL → open 时填自指占位 from_xname,realize 时更新为真实 to。

// evaluate 调:开一个 open suggestion。同 (from, change) 已 open/in_progress → 幂等返回已有 id。
export function openIteration(fromXname, { ideaId = null, changeNote = null, reason = null, iterable = true } = {}) {
  const d = db();
  const existing = d.prepare(
    `SELECT id FROM iterations
     WHERE from_xname = ? AND change_note IS ? AND status IN ('open', 'in_progress')
     ORDER BY ts DESC LIMIT 1`
  ).get(fromXname, changeNote);
  if (existing) return existing.id;

  const info = d.prepare(
    `INSERT INTO iterations (from_xname, to_xname, idea_id, change_note, reason, status, iterable)
     VALUES (?, ?, ?, ?, ?, 'open', ?)`
  ).run(fromXname, fromXname, ideaId, changeNote, reason, iterable ? 1 : 0);  // to 自指占位
  return Number(info.lastInsertRowid);
}

// persist_candidates 调:接续候选 B 时 claim(open→in_progress)。
// 只改 status,不动 to_xname(保持自指占位)——B 这时还没入 factors 表,填 to=B 会违反外键。
// "哪个 B 认领了 suggestion" 记在 state.factors[i].suggestion_id;realize 时(B 已入库)才填真实 to。
export function claimIteration(iterId) {
  const d = db();
  const row = d.prepare("SELECT status FROM iterations WHERE id = ?").get(iterId);
  if (!row) throw new Error(`iteration id 不存在: ${iterId}`);
  if (row.status !== "open") {
    return { ok: false, error: `iteration ${iterId} 状态=${row.status},非 open 不可 claim` };
  }
  d.prepare("UPDATE iterations SET status = 'in_progress' WHERE id = ?").run(iterId);
  return { ok: true };
}

// B 的 evaluate 调(在 persist_factor 之后,B 已入 factors 表):归档(in_progress→realized)。
// 此时才填 to_xname=B(外键满足)、icir_delta。演进链 from→to 就此落定。
// outcome 由 icir_delta 自动推导(CHECK 约束 outcome ∈ improved/declined/neutral),调用方只传 icir_delta。
export function realizeIteration(iterId, toXname, { icirDelta = null } = {}) {
  const d = db();
  const row = d.prepare("SELECT status FROM iterations WHERE id = ?").get(iterId);
  if (!row) throw new Error(`iteration id 不存在: ${iterId}`);
  const outcome = icirDelta == null ? "neutral"
    : icirDelta > 0.02 ? "improved"
    : icirDelta < -0.02 ? "declined"
    : "neutral";
  d.prepare(
    "UPDATE iterations SET status = 'realized', to_xname = ?, outcome = ?, icir_delta = ? WHERE id = ?"
  ).run(toXname, outcome, icirDelta, iterId);
  return { ok: true, outcome };
}

// 失败回滚:research-loop 兜底调。接续候选 B 失败时 suggestion 回到 open 允许下次再接续。
// claim 没动 to_xname(仍占位),reopen 也只改 status。
export function reopenIteration(iterId) {
  const d = db();
  const row = d.prepare("SELECT status FROM iterations WHERE id = ?").get(iterId);
  if (!row) throw new Error(`iteration id 不存在: ${iterId}`);
  if (row.status !== "in_progress") {
    return { ok: false, error: `iteration ${iterId} 状态=${row.status},非 in_progress 不可 reopen` };
  }
  d.prepare("UPDATE iterations SET status = 'open' WHERE id = ?").run(iterId);
  return { ok: true };
}

// brainstorm 调:检索待接续建议,按 priority 排序。
// priority = (evaluated?2.0:0.5) × max(icir,0.1) × exp(-age_days/14) —— pass 精进优先于 dead_end 重试,强因子优先,老建议降权。
export function listOpenIterations({ topK = 5, sourceStatus = null } = {}) {
  const d = db();
  const sql = `SELECT i.id AS suggestion_id, i.from_xname, i.change_note, i.reason, i.idea_id, i.iterable, i.ts,
            f.status AS from_status, f.latest_icir AS from_icir, f.formula_text AS from_formula,
            (CASE WHEN f.status = 'evaluated' THEN 2.0 ELSE 0.5 END)
              * MAX(COALESCE(f.latest_icir, 0), 0.1)
              * EXP(-(julianday('now') - julianday(i.ts)) / 14.0) AS priority
     FROM iterations i
     JOIN factors f ON f.xname = i.from_xname
     WHERE i.status = 'open' ${sourceStatus ? "AND f.status = ?" : ""}
     ORDER BY priority DESC
     LIMIT ?`;
  return sourceStatus ? d.prepare(sql).all(sourceStatus, topK) : d.prepare(sql).all(topK);
}

// ============ lessons（仅 check_done 实验结果：dead_end 或 success_pattern）============

export function addLesson(type, text, { xname, ideaId = null, evidence = null } = {}) {
  if (!VALID_LESSON_TYPE.includes(type)) throw new Error(`invalid lesson type: ${type}`);
  if (!xname) throw new Error("lesson 必须绑 xname（scope 固定 factor）");

  const conn = db();
  const evidenceJson = evidence ? JSON.stringify(evidence) : null;

  // 幂等：同 (factor_xname, idea_id, type) 已有 → UPDATE 最新一条；否则 INSERT
  const existing = ideaId == null
    ? conn.prepare(
        `SELECT id FROM lessons
         WHERE factor_xname = ? AND idea_id IS NULL AND type = ?
         ORDER BY created_ts DESC LIMIT 1`
      ).get(xname, type)
    : conn.prepare(
        `SELECT id FROM lessons
         WHERE factor_xname = ? AND idea_id = ? AND type = ?
         ORDER BY created_ts DESC LIMIT 1`
      ).get(xname, ideaId, type);

  if (existing) {
    conn.prepare(
      `UPDATE lessons
       SET text = ?, evidence = ?, created_ts = CURRENT_TIMESTAMP
       WHERE id = ?`
    ).run(text, evidenceJson, existing.id);
    return existing.id;
  }

  const info = conn.prepare(
    `INSERT INTO lessons (type, scope, text, evidence, idea_id, factor_xname)
     VALUES (?, 'factor', ?, ?, ?, ?)`
  ).run(type, text, evidenceJson, ideaId, xname);
  return Number(info.lastInsertRowid);
}

// 批量写入原子 lesson（evaluate 输出）
export function addLessons(lessons, ideaId = null) {
  const ids = [];
  for (const l of lessons || []) {
    try {
      const id = addLesson(l.type, l.text, {
        xname: l.xname,
        ideaId: l.idea_id ?? ideaId,
        evidence: l.evidence,
      });
      ids.push(id);
    } catch (e) {
      console.error(`[factor-db] addLesson 跳过无效条目: ${e.message}; raw=${JSON.stringify(l).slice(0, 200)}`);
    }
  }
  return ids;
}

// ============ ideas ============

export function addIdea(text, parentIdeaId = null) {
  const info = db().prepare(
    `INSERT INTO ideas (text, parent_idea_id, status) VALUES (?, ?, 'open')`
  ).run(text, parentIdeaId);
  return Number(info.lastInsertRowid);
}

// 必然假设生成机专用：写 idea + 结构化论证链（argument_chain）。
// 与 addIdea 的区别：携带论证链。论证链是假设的属性，不是因子的。
//
// argument_chain 结构:
//   background_axioms:     [Σ...]                       S1 背景公理集
//   superadditive_coupling:{ A, B, C,                   S2 超加性耦合 (A∧B⊢C 且 A⊬C 且 B⊬C)
//                           entailment_proof,             A∧B 如何推出 C
//                           superadditivity_proof,        为何 A/B 单独推不出
//                           minimality }                  为何 C 是最小非平凡蕴含
//   constraint:            "..."                        S3 固化约束
//   uniqueness_proof:      { type, reasoning }          S4 (extremum|contraction|zero_dof|equivalence|minimal_sufficient)
//   competing_explanations:[{ rival, distinguishing_observation, exclusion_test }]
//   falsifiable_trace:     "..."                        可证伪痕迹（解→X 演绎预言）
// opts: { parentIdeaId, necessityGrade }
//   necessityGrade: 必然性分级 necessary|identification|conditional|draft
//     necessary = 过 S2+S4 真硬证; identification = S2 硬但 S4 退化为可识别标量(如 Roll s=2√(-Cov));
//     conditional = S2 有 S4 弱; draft = 待补
export function addHypothesis(text, argumentChain, opts = {}) {
  const { parentIdeaId = null, necessityGrade = null } = opts;
  const chainJson = argumentChain != null ? JSON.stringify(argumentChain) : null;
  const info = db().prepare(
    `INSERT INTO ideas (text, parent_idea_id, status, argument_chain, necessity_grade) VALUES (?, ?, 'open', ?, ?)`
  ).run(text, parentIdeaId, chainJson, necessityGrade);
  return Number(info.lastInsertRowid);
}

// 取假设的论证链 + 分级（reviewer-agent 审稿 / 忠实度判定 读用）。
export function getHypothesis(ideaId) {
  return db().prepare(
    `SELECT id, text, argument_chain, necessity_grade, support_score, evaluated_factor_count, status FROM ideas WHERE id = ?`
  ).get(ideaId);
}

// 聚合假设支持度（贝叶斯平滑，不绝对判断）。
// 因子级二元 verdict（evaluated=pass, dead_end=fail）→ 假设级连续分数。
// persistVerdict 每写一个因子 verdict 后调，重算该 idea 的 support_score。
//
// 贝叶斯平滑 (pass+k)/(total+2k)：小样本收缩向 0.5（1/1 不强判为 1.0，避免过拟合少样本）。
// 不转绝对判断（不判成立/否决）——分数即输出，假设级保留不确定性。
export function updateIdeaSupportScore(ideaId, k = 1) {
  if (ideaId == null) return { ok: false, error: "ideaId 为空" };
  const d = db();
  const rows = d.prepare(
    `SELECT f.status FROM idea_factor_links l
     JOIN factors f ON f.xname = l.factor_xname
     WHERE l.idea_id = ? AND f.status IN ('evaluated','dead_end')`
  ).all(ideaId);
  const total = rows.length;
  const pass = rows.filter((r) => r.status === "evaluated").length;
  const score = total === 0 ? null : (pass + k) / (total + 2 * k);
  d.prepare(
    `UPDATE ideas SET support_score = ?, evaluated_factor_count = ?, support_score_computed_at = CURRENT_TIMESTAMP WHERE id = ?`
  ).run(score, total, ideaId);
  return { ok: true, idea_id: ideaId, pass, total, score };
}

// ============ top-down 扫库源(找失效/未竟方向,喂 hypothesis-generator) ============

// 失效假设:support_score 低 + 有足够因子验证过的假设。
// "为什么这个假设错了"是下一轮反常的原料(失效回喂)。
export function discoverFailedHypotheses({ maxScore = 0.4, minEvaluated = 2, limit = 10 } = {}) {
  return db().prepare(
    `SELECT id, text, support_score, evaluated_factor_count, necessity_grade
     FROM ideas
     WHERE support_score IS NOT NULL AND support_score < ? AND evaluated_factor_count >= ?
     ORDER BY support_score ASC LIMIT ?`
  ).all(maxScore, minEvaluated, limit);
}

// 最近 dead_end:方向失效信号(避雷 + 失效回喂)。
export function discoverRecentDeadEnds({ limit = 10 } = {}) {
  return db().prepare(
    `SELECT id, text, factor_xname, idea_id, created_ts
     FROM lessons WHERE type = 'dead_end'
     ORDER BY created_ts DESC LIMIT ?`
  ).all(limit);
}

// ============ 覆盖地图(coverage map):系统第一次"看见自己挖过哪" ============
// 按 symbol×freq×status×necessity_grade 聚合已搜空间,标 thin/hot/stale/unexplored,
// 覆盖空白源 + brainstorm 选方向用。
// 口径:只统计跑过 ic_refresh 的因子(有评估结果 + ic 向量);draft/submitted 在途不计。

// 轴:symbol=品种, y_horizon=预测周期秒(1/5/10/60/300,真实有区分力), status=评估状态,
//      necessity_grade=假设硬度(真实库 ideas 多无论证链→常 NULL,当前无区分力但保留)。
// 注意:factor_ic_vec_meta.freq 实际存因子 spec(每因子独占,无聚合价值),不作为轴。
const COVERAGE_AXES = {
  symbol: "m.symbol",
  y_horizon: "m.y_horizon",
  status: "f.status",
  necessity_grade: "i.necessity_grade",
};
const DEFAULT_COVERAGE_AXES = ["symbol", "y_horizon", "status", "necessity_grade"];
const COVERAGE_STALE_DAYS = 60;

function daysSince(ts) {
  if (!ts) return Infinity;
  let s = String(ts).trim().replace(" ", "T");
  if (!/[zZ]$/.test(s) && !/[+-]\d\d:?\d\d$/.test(s)) s += "Z";  // 已带时区不加,否则补 Z(SQLite CURRENT_TIMESTAMP 无 Z)
  const t = Date.parse(s);
  if (Number.isNaN(t)) return Infinity;
  return (Date.now() - t) / 86400000;
}

function resolveAxes(reqAxes) {
  const axes = (Array.isArray(reqAxes) && reqAxes.length ? reqAxes : DEFAULT_COVERAGE_AXES)
    .filter((a) => COVERAGE_AXES[a]);
  return axes.length ? axes : DEFAULT_COVERAGE_AXES;
}

// 覆盖张量切片。每格: {<axes>, searched_count, evaluated_count, dead_end_count, avg_icir, last_evaluated_ts, gap_tags}
// gap_tags ∈ thin|hot|stale|normal(thin/hot/stale 可叠加)。
//   thin: 试过≤3 且 0 评估成功(欠探索/未见效)
//   hot:  evaluated≥1 且 avg_icir 高于全库 evaluated 均值(有效率热点,值得继续变异)
//   stale: 该格最近评估 > 60 天(可能 drift,待复验)
// opts.slice {symbol?,y_horizon?,status?,necessity_grade?};opts.groupBy 聚合轴子集;opts.minCount 只看试过≥此值。
export function coverageMap({ slice = {}, groupBy = DEFAULT_COVERAGE_AXES, minCount = 0 } = {}) {
  const d = db();
  const axes = resolveAxes(groupBy);
  const selectCols = axes.map((a) => `${COVERAGE_AXES[a]} AS ${a}`).join(", ");
  const groupCols = axes.map((a) => COVERAGE_AXES[a]).join(", ");

  const where = [];
  const params = [];
  for (const a of Object.keys(COVERAGE_AXES)) {
    if (slice[a] != null) {
      where.push(`${COVERAGE_AXES[a]} = ?`);
      params.push(slice[a]);
    }
  }
  const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
  if (minCount > 0) params.push(minCount);
  const havingSql = minCount > 0 ? `HAVING COUNT(DISTINCT f.xname) >= ?` : "";

  const rows = d.prepare(`
    SELECT ${selectCols},
           COUNT(DISTINCT f.xname)                                AS searched_count,
           COUNT(DISTINCT CASE WHEN f.status='evaluated' THEN f.xname END) AS evaluated_count,
           COUNT(DISTINCT CASE WHEN f.status='dead_end'  THEN f.xname END) AS dead_end_count,
           AVG(f.latest_icir)                                    AS avg_icir,
           MAX(m.computed_at)                                    AS last_evaluated_ts
    FROM factor_ic_vec_meta m
    JOIN factors f ON f.xname = m.factor_xname
    LEFT JOIN factor_evals e2 ON e2.id = (
      SELECT id FROM factor_evals WHERE factor_xname = f.xname ORDER BY ts DESC LIMIT 1
    )
    LEFT JOIN ideas i ON i.id = e2.idea_id
    ${whereSql}
    GROUP BY ${groupCols}
    ${havingSql}
    ORDER BY searched_count DESC
  `).all(...params);

  // 全库 evaluated 因子均 ICIR 作 hot 阈值(中位数的均值近似)
  const med = d.prepare(
    `SELECT AVG(latest_icir) AS a FROM factors WHERE status='evaluated' AND latest_icir IS NOT NULL`
  ).get();
  const medianIcir = med && med.a != null ? med.a : 0;

  return rows.map((r) => {
    const tags = [];
    if (r.searched_count <= 3 && r.evaluated_count === 0) tags.push("thin");
    if (r.evaluated_count >= 1 && r.avg_icir != null && r.avg_icir > medianIcir && r.avg_icir > 0) tags.push("hot");
    if (daysSince(r.last_evaluated_ts) > COVERAGE_STALE_DAYS) tags.push("stale");
    if (tags.length === 0) tags.push("normal");
    return { ...r, gap_tags: tags };
  });
}

// 覆盖空白/热点队列,供看覆盖空白当任务源(补现有 failed/open/dead_end 都是"已试边界"的盲区)。
// unexplored: symbol×freq×necessity_grade 组合里 evaluated=0(从没在该 品种×频率×假设硬度 验证成功)。
// thin/hot/stale: 从 coverageMap 筛,各取 top_k。每项带 suggestion 文本。
export function coverageGaps({ topK = 5 } = {}) {
  const d = db();
  const unexplored = d.prepare(`
    SELECT m.symbol, m.y_horizon, i.necessity_grade,
           COUNT(DISTINCT f.xname)                                AS searched_count,
           COUNT(DISTINCT CASE WHEN f.status='evaluated' THEN f.xname END) AS evaluated_count
    FROM factor_ic_vec_meta m
    JOIN factors f ON f.xname = m.factor_xname
    LEFT JOIN factor_evals e2 ON e2.id = (
      SELECT id FROM factor_evals WHERE factor_xname = f.xname ORDER BY ts DESC LIMIT 1
    )
    LEFT JOIN ideas i ON i.id = e2.idea_id
    GROUP BY m.symbol, m.y_horizon, i.necessity_grade
    HAVING evaluated_count = 0
    ORDER BY searched_count DESC
    LIMIT ?
  `).all(topK).map((r) => ({
    symbol: r.symbol, y_horizon: r.y_horizon, necessity_grade: r.necessity_grade,
    searched_count: r.searched_count, evaluated_count: r.evaluated_count,
    gap_tag: "unexplored",
    suggestion: `${r.symbol || "?"} × h=${r.y_horizon ?? "?"}s × ${r.necessity_grade || "any"} 维度空白(试过 ${r.searched_count} 个均无 evaluated),值得冷启动探索`,
  }));

  const cells = coverageMap();
  const pick = (tag) => cells
    .filter((c) => c.gap_tags.includes(tag))
    .slice(0, topK)
    .map((c) => ({
      symbol: c.symbol, y_horizon: c.y_horizon, status: c.status, necessity_grade: c.necessity_grade,
      searched_count: c.searched_count, evaluated_count: c.evaluated_count,
      avg_icir: c.avg_icir, last_evaluated_ts: c.last_evaluated_ts,
      gap_tag: tag,
      suggestion:
        tag === "hot"   ? `${c.symbol || "?"} × h=${c.y_horizon ?? "?"}s 高效热点(avg_icir=${Number(c.avg_icir ?? 0).toFixed(3)}),值得在该格继续变异`
      : tag === "thin" ? `${c.symbol || "?"} × h=${c.y_horizon ?? "?"}s × ${c.status} 欠探索(${c.searched_count} 个试过 0 评估成功),换轴或弃`
      :                   `${c.symbol || "?"} × h=${c.y_horizon ?? "?"}s 该格 ${Math.round(daysSince(c.last_evaluated_ts))} 天没动,可能 drift,待复验`,
    }));

  return { unexplored, thin: pick("thin"), hot: pick("hot"), stale: pick("stale") };
}

// ============ 查询 ============

export function countFactors() {
  return db().prepare("SELECT COUNT(*) AS n FROM factors").get().n;
}

export function countLessons() {
  return db().prepare("SELECT COUNT(*) AS n FROM lessons").get().n;
}

export function countEvaluated() {
  return db().prepare(
    `SELECT COUNT(*) AS n FROM factors WHERE status = 'evaluated'`
  ).get().n;
}

// xname 是否已登记（换名唯一性检查用，轻量不抛错）。
export function factorExists(xname) {
  return !!db().prepare("SELECT 1 FROM factors WHERE xname = ?").get(xname);
}

export function recentLessons(k = 10) {
  return db().prepare(
    `SELECT id, type, scope, text, idea_id, factor_xname, created_ts
     FROM lessons ORDER BY id DESC LIMIT ?`
  ).all(k);
}

export function recentFactors(k = 10) {
  return db().prepare(
    `SELECT xname, class_name, status, latest_ic, latest_icir, last_updated_ts
     FROM factors ORDER BY last_updated_ts DESC LIMIT ?`
  ).all(k);
}

// FTS5 全文检索 lessons（trigram, 中文友好）
export function searchLessons(query, k = 5, typeFilter = null) {
  const q = String(query || "").trim();
  if (q.length < 3) return recentLessons(k);

  // 切 trigram（兼容 lessons.mjs 老逻辑）
  const cleaned = q.replace(/\s+/g, "");
  const tokens = new Set();
  for (let i = 0; i <= cleaned.length - 3; i++) {
    tokens.add(cleaned.slice(i, i + 3));
    if (tokens.size >= 12) break;
  }
  if (tokens.size === 0) return recentLessons(k);

  const ftsQuery = [...tokens].map(t => `"${t.replace(/"/g, '""')}"`).join(" OR ");
  const sql = `
    SELECT l.id, l.type, l.scope, l.text, l.idea_id, l.factor_xname, l.created_ts,
           bm25(lessons_fts) AS score
    FROM lessons_fts f JOIN lessons l ON l.rowid = f.rowid
    WHERE lessons_fts MATCH ?
    ${typeFilter ? "AND l.type = ?" : ""}
    ORDER BY score LIMIT ?
  `;
  const params = typeFilter ? [ftsQuery, typeFilter, k] : [ftsQuery, k];
  return db().prepare(sql).all(...params);
}

// FTS5 检索 factors（formula/class_name）
export function searchFactors(query, k = 10) {
  const q = String(query || "").trim();
  if (q.length < 3) return recentFactors(k);

  const cleaned = q.replace(/\s+/g, "");
  const tokens = new Set();
  for (let i = 0; i <= cleaned.length - 3; i++) {
    tokens.add(cleaned.slice(i, i + 3));
    if (tokens.size >= 12) break;
  }
  if (tokens.size === 0) return recentFactors(k);

  const ftsQuery = [...tokens].map(t => `"${t.replace(/"/g, '""')}"`).join(" OR ");
  return db().prepare(
    `SELECT f.xname, f.class_name, f.status, f.latest_icir, f.formula_text,
            bm25(factors_fts) AS score
     FROM factors_fts ft JOIN factors f ON f.rowid = ft.rowid
     WHERE factors_fts MATCH ?
     ORDER BY score LIMIT ?`
  ).all(ftsQuery, k);
}

// 向量查重（query_emb 已 L2 normalize）
export function searchSimilarFactors(queryEmb, k = 10, { status = null, minIcir = null } = {}) {
  const buf = Buffer.from(new Float32Array(queryEmb).buffer);
  let sql = `
    SELECT v.xname, v.distance, f.status, f.latest_icir, f.latest_ic, f.formula_text
    FROM factors_vec v JOIN factors f ON f.xname = v.xname
    WHERE v.embedding MATCH ? AND k = ?
  `;
  const params = [buf, k];
  if (status) { sql += " AND f.status = ?"; params.push(status); }
  if (minIcir != null) { sql += " AND f.latest_icir >= ?"; params.push(minIcir); }
  sql += " AND f.deprecated_at IS NULL ORDER BY v.distance";
  return db().prepare(sql).all(...params);
}

// ============ metrics 抓取（从 daily_ic_results.txt 文本）============

export function extractMetrics(dailyIcPreview) {
  if (!dailyIcPreview) return {};
  const find = (re) => {
    const m = String(dailyIcPreview).match(re);
    return m ? Number(m[1]) : null;
  };
  const icMean = find(/IC[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)/i);
  const icir = find(/ICIR[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)/i);
  const sharpe = find(/Sharpe[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)/i);
  const rankIc = find(/Rank\s*IC[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)/i);
  return { ic_mean: icMean, icir, sharpe, rank_ic: rankIc };
}

// ============ 单因子详情 + 向量查重（从 factor-cli.mjs 迁移）============

// 单因子全貌：基本信息 + 最近 10 条 evals + tags + 迭代链（ancestors + descendants）
export function getFactorDetail(xname) {
  const d = db();
  const factor = d.prepare("SELECT * FROM factors WHERE xname = ?").get(xname);
  if (!factor) throw new Error(`xname 不存在: ${xname}`);
  const evals = d.prepare(
    "SELECT ts, ic_mean, icir, sharpe, eval_mode, significant FROM factor_evals WHERE factor_xname = ? ORDER BY ts DESC LIMIT 10"
  ).all(xname);
  const tags = d.prepare(
    "SELECT t.name FROM tags t JOIN factor_tags ft ON ft.tag_id = t.id WHERE ft.factor_xname = ?"
  ).all(xname).map(r => r.name);
  const ancestors = d.prepare(`
    WITH RECURSIVE chain AS (
      SELECT from_xname AS x, 1 AS depth FROM iterations WHERE to_xname = ? AND status = 'realized'
      UNION ALL
      SELECT i.from_xname, c.depth + 1 FROM iterations i JOIN chain c ON i.to_xname = c.x WHERE i.status = 'realized'
    )
    SELECT x AS xname, depth FROM chain ORDER BY depth
  `).all(xname);
  const descendants = d.prepare(`
    WITH RECURSIVE chain AS (
      SELECT to_xname AS x, 1 AS depth FROM iterations WHERE from_xname = ? AND status = 'realized'
      UNION ALL
      SELECT i.to_xname, c.depth + 1 FROM iterations i JOIN chain c ON i.from_xname = c.x WHERE i.status = 'realized'
    )
    SELECT x AS xname, depth FROM chain ORDER BY depth
  `).all(xname);
  return { factor, evals, tags, ancestors, descendants };
}

// 向量查重：给定 xname，找库内最相似的 k 个因子
export function getSimilarFactors(xname, k = 10) {
  const d = db();
  const row = d.prepare("SELECT embedding FROM factors_vec WHERE xname = ?").get(xname);
  if (!row) throw new Error(`xname 在 factors_vec 中不存在: ${xname}`);
  const emb = Array.from(new Float32Array(row.embedding.buffer, row.embedding.byteOffset, row.embedding.byteLength / 4));
  return searchSimilarFactors(emb, k);
}

// 语义检索：给定任意文本（idea/formula/自然语言），算 embedding 查相似因子。
// 内部 spawn python 跑 BAAI/bge-small-zh-v1.5（首次加载 ~30s，之后 10-30ms/条）。
export async function semanticSearchFactors(queryText, k = 10) {
  const trimmed = String(queryText || "").trim();
  if (!trimmed) return [];
  const { runPy } = await import("../infra/run-py.mjs");
  const script = path.join(CWD, "factor_db", "embed_query.py");
  const result = await runPy(script, ["--text", trimmed], { timeoutSec: 60 });
  if (result.exitCode !== 0) {
    throw new Error(`embed_query.py exit=${result.exitCode}: ${(result.stderr || "").slice(0, 200)}`);
  }
  const last = (result.stdout || "").trim().split("\n").pop();
  let parsed;
  try { parsed = JSON.parse(last); }
  catch { throw new Error(`embed_query.py 输出非 JSON: ${last.slice(0, 200)}`); }
  if (!Array.isArray(parsed.embedding) || parsed.embedding.length === 0) {
    throw new Error("embed_query.py 返回空 embedding");
  }
  return searchSimilarFactors(parsed.embedding, k);
}

// IC 行为冗余检索：找和 target 因子 IC 序列相似的库内因子（预测能力同涨同跌 = 真冗余）。
// 比 formula 文本语义检索更贴近业务；evaluate 用它量化"与已有因子相关性"。
export async function icCorrelateFactors(targetFactor, opts = {}) {
  const { symbol, freq, yHorizon, k = 20, minAbsPearson = 0.5, top = 15 } = opts;
  const { runPy } = await import("../infra/run-py.mjs");
  const script = path.join(CWD, "factor_db", "ic_correlate.py");
  const args = [
    "--target", String(targetFactor),
    "--k", String(k),
    "--min-abs-pearson", String(minAbsPearson),
    "--top", String(top),
  ];
  if (symbol) args.push("--symbol", String(symbol));
  if (freq) args.push("--freq", String(freq));
  if (yHorizon != null) args.push("--y-horizon", String(yHorizon));
  const result = await runPy(script, args, { timeoutSec: 30 });
  if (result.exitCode !== 0) {
    throw new Error(`ic_correlate.py exit=${result.exitCode}: ${(result.stderr || "").slice(0, 200)}`);
  }
  const last = (result.stdout || "").trim().split("\n").pop();
  try { return JSON.parse(last); }
  catch { throw new Error(`ic_correlate.py 输出非 JSON: ${last.slice(0, 200)}`); }
}

// IC 向量刷新：为单因子下载 dailyX + 算 IC 序列向量写入 factor_ic_vec。
// evaluate 在 check_done 后调用，使新因子可被 icCorrelateFactors 检索。
// 失败（下载/计算）返回 ok:false，调用方应降级跳过冗余检查（不阻塞主 verdict）。
export async function icRefreshFactor(xname, force = false) {
  const { runPy } = await import("../infra/run-py.mjs");
  const script = path.join(CWD, "factor_db", "refresh_factor_ic_vectors.py");
  const args = ["--xname", String(xname)];
  if (force) args.push("--force");
  const result = await runPy(script, args, { timeoutSec: 900 });
  return {
    ok: result.exitCode === 0,
    exitCode: result.exitCode,
    stdout_tail: (result.stdout || "").slice(-400),
    stderr_head: (result.stderr || "").slice(0, 200),
  };
}

// 残差 IC 强度:新因子日级 IC 序列在库内基底 IC 张成空间的残差比例(预测能力不被已有因子线性解释的程度)。
// 高=真新颖,低=冗余。补 factor_ic_correlate 的 pairwise(那个查"和某个最像",这个给"相对全库基底的新颖性标量")。
// spawn factor_db/residual_ic_strength.py(numpy 岭回归正交),模式同 icCorrelateFactors。
// 数据依赖 factor_ic_daily(refresh_factor_ic_vectors.py 入库);库空/无基底 → strength=1.0(残差=target 自身)。
export async function residualIcStrength(targetFactor, opts = {}) {
  const { symbol, freq, yHorizon, ridge = 1e-3, maxBase = 30 } = opts;
  const { runPy } = await import("../infra/run-py.mjs");
  const script = path.join(CWD, "factor_db", "residual_ic_strength.py");
  const args = ["--target", String(targetFactor), "--ridge", String(ridge), "--max-base", String(maxBase)];
  if (symbol) args.push("--symbol", String(symbol));
  if (freq) args.push("--freq", String(freq));
  if (yHorizon != null) args.push("--y-horizon", String(yHorizon));
  const result = await runPy(script, args, { timeoutSec: 30 });
  if (result.exitCode !== 0) {
    throw new Error(`residual_ic_strength.py exit=${result.exitCode}: ${(result.stderr || "").slice(0, 200)}`);
  }
  const last = (result.stdout || "").trim().split("\n").pop();
  try {
    return JSON.parse(last);
  } catch {
    throw new Error(`residual_ic_strength.py 输出非 JSON: ${last.slice(0, 200)}`);
  }
}

// 衔接①(归纳→演绎):拉 archived 高优先 + 未解释的模式卡,供 hypothesis-generator 解释。
export function feedPatternQueue(topN = 3) {
  return db().prepare(
    `SELECT id,f_feature,t_transform,c_condition,s_structure,y_target,h_horizon,r_reference,strength,priority
     FROM pattern_cards WHERE status='archived' AND idea_id IS NULL ORDER BY RANDOM() LIMIT ?`
  ).all(topN);
}

// 衔接①回写:hypothesis-generator 解释模式卡产 idea 后,回写 idea_id + status='explained'。
export function linkPatternIdea(patternCardId, ideaId) {
  const d = db();
  const row = d.prepare("SELECT status FROM pattern_cards WHERE id = ?").get(patternCardId);
  if (!row) throw new Error(`pattern_card id 不存在: ${patternCardId}`);
  if (row.status !== "archived") {
    return { ok: false, error: `pattern_card ${patternCardId} 状态=${row.status},非 archived 不可回写` };
  }
  d.prepare("UPDATE pattern_cards SET idea_id = ?, status = 'explained' WHERE id = ?").run(ideaId, patternCardId);
  return { ok: true };
}

// ============ 知识图（axioms / graph_edges）============
// 分层知识图。graph_edges 跨表软引用 (from_table, from_id)，from_id: factors 存 xname，其余存 integer id 字符串。
// 与 db.py 对齐。graph-engine 推理引擎经 MCP 工具读写此图。

const NODE_PK = {
  axioms: "id", ideas: "id", factors: "xname", lessons: "id",
};

// AXIOM 层：写公理。幂等（code 唯一）。expected_signature 接受 object/string。
export function addAxiom({ code, category, statement, formal_form = null, expected_signature = null, source = null, falsifiable = null }) {
  const d = db();
  const exist = d.prepare("SELECT id FROM axioms WHERE code = ?").get(code);
  if (exist) return exist.id;
  const es = expected_signature && typeof expected_signature === "object"
    ? JSON.stringify(expected_signature) : (expected_signature || null);
  const info = d.prepare(
    `INSERT OR IGNORE INTO axioms (code,category,statement,formal_form,expected_signature,source,falsifiable)
     VALUES (?,?,?,?,?,?,?)`
  ).run(code, category, statement, formal_form, es, source, falsifiable);
  return Number(info.lastInsertRowid) || d.prepare("SELECT id FROM axioms WHERE code = ?").get(code).id;
}

// 图边：幂等（UNIQUE 四元组+类型）。返回 edge id。
export function addGraphEdge({ from_table, from_id, to_table, to_id, edge_type, weight = null, properties = null }) {
  const d = db();
  const fid = String(from_id), tid = String(to_id);
  const exist = d.prepare(
    `SELECT id FROM graph_edges WHERE from_table=? AND from_id=? AND to_table=? AND to_id=? AND edge_type=?`
  ).get(from_table, fid, to_table, tid, edge_type);
  if (exist) return exist.id;
  const props = properties ? JSON.stringify(properties) : null;
  return Number(db().prepare(
    `INSERT OR IGNORE INTO graph_edges (from_table,from_id,to_table,to_id,edge_type,weight,properties)
     VALUES (?,?,?,?,?,?,?)`
  ).run(from_table, fid, to_table, tid, edge_type, weight, props).lastInsertRowid);
}

// 取节点完整行（按表主键）。
function nodeRow(table, id) {
  const pk = NODE_PK[table];
  if (!pk) return null;
  return db().prepare(`SELECT * FROM ${table} WHERE ${pk} = ?`).get(String(id));
}

// 查 CONTRADICTS 边。resolved=false 返回未解矛盾（resolve_contradiction 输入）。
export function queryContradictions({ resolved = false, axiom_code = null, limit = 5 } = {}) {
  const hasResolved = graphConstants().resolved_clause;
  let where = `ge.edge_type='CONTRADICTS' AND ${resolved ? "" : "NOT "}(${hasResolved})`;
  const params = [];
  if (axiom_code) { where += " AND a.code = ?"; params.push(axiom_code); }
  const rows = db().prepare(
    `SELECT ge.id AS edge_id, ge.weight, ge.properties,
            a.id AS axiom_id, a.code AS axiom_code, a.statement, a.formal_form, a.expected_signature
     FROM graph_edges ge
     JOIN axioms a ON a.id = ge.to_id AND ge.to_table='axioms'
     WHERE ${where} ORDER BY COALESCE(ge.weight,0) DESC LIMIT ?`
  ).all(...params, limit);
  return rows.map((r) => ({
    edge_id: r.edge_id, weight: r.weight, properties: r.properties,
    evidence: null,
    axiom: { id: r.axiom_id, code: r.axiom_code, statement: r.statement, formal_form: r.formal_form, expected_signature: r.expected_signature },
  }));
}

// 1 跳邻居。direction: out/in/both。
export function neighborhood({ table, node_id, edge_types = null, direction = "both", limit = 10 } = {}) {
  const clauses = [], params = [];
  if (direction === "out" || direction === "both") { clauses.push("(from_table=? AND from_id=?)"); params.push(table, String(node_id)); }
  if (direction === "in" || direction === "both") { clauses.push("(to_table=? AND to_id=?)"); params.push(table, String(node_id)); }
  let et = "";
  if (edge_types && edge_types.length) { et = ` AND edge_type IN (${edge_types.map(() => "?").join(",")})`; params.push(...edge_types); }
  const rows = db().prepare(
    `SELECT from_table,from_id,to_table,to_id,edge_type,weight,properties FROM graph_edges
     WHERE (${clauses.join(" OR ")})${et} LIMIT ?`
  ).all(...params, limit);
  return rows.map((r) => {
    const isFrom = r.from_table === table && String(r.from_id) === String(node_id);
    const [nt, ni] = isFrom ? [r.to_table, r.to_id] : [r.from_table, r.from_id];
    return { neighbor_table: nt, neighbor_id: ni, edge_type: r.edge_type, weight: r.weight,
             direction: isFrom ? "out" : "in", fields: nodeRow(nt, ni) };
  });
}

// 以节点为中心 depth 跳子图（BFS）。
export function getSubgraph({ table, node_id, depth = 2, edge_types = null, limit = 200 } = {}) {
  const etFilter = edge_types && edge_types.length
    ? ` AND edge_type IN (${edge_types.map(() => "?").join(",")})` : "";
  const etParams = edge_types && edge_types.length ? edge_types : [];
  const nodes = new Map();
  const edges = [];
  nodes.set(`${table}:${node_id}`, { table, id: String(node_id), depth: 0, fields: nodeRow(table, node_id) });
  let frontier = [[table, String(node_id)]];
  for (let d = 1; d <= depth && frontier.length; d++) {
    const clauses = [], params = [];
    for (const [ft, fid] of frontier) { clauses.push("(from_table=? AND from_id=?)"); params.push(ft, fid); }
    for (const [ft, fid] of frontier) { clauses.push("(to_table=? AND to_id=?)"); params.push(ft, fid); }
    const rows = db().prepare(
      `SELECT from_table,from_id,to_table,to_id,edge_type,weight,properties FROM graph_edges
       WHERE (${clauses.join(" OR ")})${etFilter} LIMIT ?`
    ).all(...params, ...etParams, limit);
    const next = [];
    for (const r of rows) {
      edges.push({ ...r });
      for (const [t, i] of [[r.from_table, r.from_id], [r.to_table, r.to_id]]) {
        const key = `${t}:${i}`;
        if (!nodes.has(key)) {
          const row = nodeRow(t, i);
          if (row) { nodes.set(key, { table: t, id: String(i), depth: d, fields: row }); next.push([t, String(i)]); }
        }
      }
    }
    frontier = next;
  }
  return { center: { table, id: String(node_id) }, nodes: [...nodes.values()], edges };
}

// REFUTES/SUPPORTS 指向同一目标的聚簇（generalize_from_refutation 输入）。
export function findRefutationClusters({ target_table = null, target_id = null, min_size = 3, limit = 5 } = {}) {
  let where = "edge_type IN ('REFUTES','SUPPORTS') AND to_table IN ('axioms','ideas')";
  const params = [];
  if (target_table) { where += " AND to_table = ?"; params.push(target_table); }
  if (target_id != null) { where += " AND to_id = ?"; params.push(String(target_id)); }
  const groups = db().prepare(
    `SELECT to_table,to_id,edge_type,COUNT(*) AS sz FROM graph_edges
     WHERE ${where} GROUP BY to_table,to_id,edge_type HAVING sz >= ? ORDER BY sz DESC LIMIT ?`
  ).all(...params, min_size, limit);
  return groups.map((g) => {
    const members = db().prepare(
      `SELECT from_table,from_id FROM graph_edges WHERE to_table=? AND to_id=? AND edge_type=?`
    ).all(g.to_table, g.to_id, g.edge_type);
    return { target_table: g.to_table, target_id: g.to_id, edge_type: g.edge_type, size: g.sz,
             target: nodeRow(g.to_table, g.to_id), members };
  });
}

// 图统计：各层节点/边计数/未解矛盾数（自转停止条件用）。
export function graphStats() {
  const d = db();
  const c = (sql) => d.prepare(sql).get().c;
  const edges_by_type = {};
  for (const r of d.prepare("SELECT edge_type, COUNT(*) AS c FROM graph_edges GROUP BY edge_type").all()) {
    edges_by_type[r.edge_type] = r.c;
  }
  return {
    axioms: c("SELECT COUNT(*) AS c FROM axioms"),
    derived: c("SELECT COUNT(*) AS c FROM ideas WHERE node_layer='DERIVED'"),
    hypothesis: c("SELECT COUNT(*) AS c FROM ideas WHERE node_layer='HYPOTHESIS' OR node_layer IS NULL"),
    evidence_lessons: c("SELECT COUNT(*) AS c FROM lessons WHERE type='success_pattern' AND deprecated_at IS NULL"),
    refutation_lessons: c("SELECT COUNT(*) AS c FROM lessons WHERE type='dead_end' AND deprecated_at IS NULL"),
    edges_by_type,
    total_edges: c("SELECT COUNT(*) AS c FROM graph_edges"),
    unresolved_contradictions: c(
      `SELECT COUNT(*) AS c FROM graph_edges WHERE edge_type='CONTRADICTS' AND NOT (${graphConstants().resolved_clause})`
    ),
  };
}

// 标记 CONTRADICTS 边已由某 idea 解决。
export function markContradictionResolved({ edge_id, idea_id }) {
  const d = db();
  const row = d.prepare("SELECT properties FROM graph_edges WHERE id = ?").get(edge_id);
  let props = {};
  try { props = row && row.properties ? JSON.parse(row.properties) : {}; } catch { props = {}; }
  props.resolved_by = idea_id;
  d.prepare("UPDATE graph_edges SET properties = ? WHERE id = ?").run(JSON.stringify(props), edge_id);
  return { ok: true };
}

// 标记 CONTRADICTS 边为「axiom 边界限定」(否定性结论:axiom 在此 regime 不完备)。
// 与 markContradictionResolved 对称:resolved=肯定解决(产 idea),bounded=否定解决(axiom 证伪)。
export function markContradictionBounded({ edge_id, regime, reason }) {
  const d = db();
  const row = d.prepare("SELECT properties FROM graph_edges WHERE id = ?").get(edge_id);
  let props = {};
  try { props = row && row.properties ? JSON.parse(row.properties) : {}; } catch { props = {}; }
  props.resolution = "bounded";
  props.regime = regime;
  props.reason = reason;
  d.prepare("UPDATE graph_edges SET properties = ? WHERE id = ?").run(JSON.stringify(props), edge_id);
  return { ok: true };
}

// 写节点：table='axioms'→addAxiom；table='ideas'→带 node_layer/argument_chain 的 idea。
export function addGraphNode({ table, data }) {
  if (table === "axioms") return addAxiom(data);
  if (table === "ideas") {
    const chain = data.argument_chain != null
      ? (typeof data.argument_chain === "string" ? data.argument_chain : JSON.stringify(data.argument_chain))
      : null;
    const info = db().prepare(
      `INSERT INTO ideas (text,parent_idea_id,status,argument_chain,necessity_grade,node_layer)
       VALUES (?,?,'open',?,?,?)`
    ).run(data.text, data.parent_idea_id ?? null, chain, data.necessity_grade ?? null, data.node_layer ?? "HYPOTHESIS");
    return Number(info.lastInsertRowid);
  }
  throw new Error(`addGraphNode 不支持表: ${table}`);
}

// ============ 信息角度元层(让 graph-engine 感知饱和/未探索,自动换角度)============
function migrateAngleSchema() {
  _db.exec(`CREATE TABLE IF NOT EXISTS angle_ontology (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, field_family TEXT NOT NULL,
    extraction TEXT NOT NULL, signal_target TEXT, theory_axiom TEXT, description TEXT)`);
  _db.exec("CREATE INDEX IF NOT EXISTS idx_angle_family ON angle_ontology(field_family)");
  const fcols = _db.prepare("PRAGMA table_info(factors)").all().map((c) => c.name);
  if (fcols.length > 0 && !fcols.includes("angle_code")) {
    _db.exec("ALTER TABLE factors ADD COLUMN angle_code TEXT");
  }
}

// factors.quality_score/quality_grade(多指标聚合分 v6)
function migrateQualitySchema() {
  const fcols = _db.prepare("PRAGMA table_info(factors)").all().map((c) => c.name);
  if (fcols.length > 0 && !fcols.includes("quality_score")) {
    _db.exec("ALTER TABLE factors ADD COLUMN quality_score REAL");
  }
  if (fcols.length > 0 && !fcols.includes("quality_grade")) {
    _db.exec("ALTER TABLE factors ADD COLUMN quality_grade TEXT");
  }
}

export function addAngle({ code, name, field_family, extraction, signal_target = null, theory_axiom = null, description = null }) {
  _db.prepare(`INSERT OR IGNORE INTO angle_ontology (code,name,field_family,extraction,signal_target,theory_axiom,description) VALUES (?,?,?,?,?,?,?)`)
    .run(code, name, field_family, extraction, signal_target, theory_axiom, description);
}

export function tagFactorAngle({ xname, angle_code }) {
  _db.prepare("UPDATE factors SET angle_code=? WHERE xname=?").run(angle_code, xname);
}

export function queryAngleCoverage() {
  const rows = _db.prepare(`
    SELECT a.code, a.name, a.field_family, a.extraction, a.signal_target, a.theory_axiom,
           COUNT(f.xname) AS n_factors,
           COALESCE(SUM(CASE WHEN f.status='dead_end' THEN 1 ELSE 0 END),0) AS n_dead_end,
           COALESCE(SUM(CASE WHEN f.status='evaluated' THEN 1 ELSE 0 END),0) AS n_evaluated,
           MAX(f.latest_icir) AS max_icir
    FROM angle_ontology a
    LEFT JOIN factors f ON f.angle_code=a.code AND f.deprecated_at IS NULL
    GROUP BY a.code,a.name,a.field_family,a.extraction,a.signal_target,a.theory_axiom
    ORDER BY n_factors ASC`).all();
  return rows.map((r) => {
    const n = r.n_factors, nd = r.n_dead_end;
    const sc = graphConstants().saturation;
    const saturation = n === 0 ? "unexplored" : (n >= sc.min_n_saturated && nd >= n * sc.dead_ratio_saturated ? "saturated" : (n <= sc.max_n_thin ? "thin" : "partial"));
    return { ...r, saturation };
  });
}

// ============ 操作选择(3 操作数据驱动打分,与 db.py select_graph_operation 双端一致) ============
// 操作层只 3 个: generalize(归纳) / fill(维护) / explore(拓展)
// 方法论(反例/成功/正交/对比)是 graph-reasoner 推理时自选,不在此打分。
// score = trigger × diversity,无魔数 if-else。
const _CLUSTER_SCALE = 10.0;
const _GAP_SCALE = 5.0;
const _DIV_PENALTY = 0.7;
const _OP_MAP = {
  "generalize_from_refutation": "generalize", "generalize_from_success": "generalize",
  "refutation_correction": "generalize", "orthogonal_branch": "generalize",
  "fill_chain_gap": "fill", "explore_uncovered_angle": "explore",
  "resolve_contradiction": "generalize", "trace_verification": "generalize",
};

export function queryRecentOperations(n = 10) {
  return _db.prepare(
    `SELECT json_extract(properties,'$.via') AS via FROM graph_edges
     WHERE edge_type='DERIVES_FROM' AND json_extract(properties,'$.via') IS NOT NULL
     ORDER BY id DESC LIMIT ?`
  ).all(n).map((r) => _OP_MAP[r.via] || r.via).filter(Boolean);
}

function _countFillGaps() {
  const axcodes = new Set(_db.prepare("SELECT code FROM axioms").all().map((r) => r.code));
  const ideaIds = new Set(_db.prepare("SELECT CAST(id AS TEXT) AS id FROM ideas").all().map((r) => r.id));
  let n = 0;
  for (const row of _db.prepare(
    "SELECT id, argument_chain FROM ideas WHERE node_layer='DERIVED' AND argument_chain IS NOT NULL"
  ).all()) {
    const ch = JSON.parse(row.argument_chain);
    for (const a of (ch.background_axioms || [])) {
      if (!axcodes.has(a) && !ideaIds.has(a)) n++;
    }
    const comp = ch.competing_explanations || [];
    if (comp.length < 2) n++;
  }
  return n;
}

function _maxAngleCluster() {
  const row = _db.prepare(
    `SELECT MAX(n) as mx FROM (SELECT COUNT(*) n FROM factors
     WHERE status='dead_end' AND deprecated_at IS NULL AND angle_code IS NOT NULL
     GROUP BY angle_code)`
  ).get();
  return row && row.mx ? Number(row.mx) : 0;
}

export function selectGraphOperation() {
  const coverage = queryAngleCoverage();
  const recent = queryRecentOperations(10);
  const nFresh = coverage.filter((a) => a.saturation === "unexplored" || a.saturation === "thin").length;
  const nSaturated = coverage.filter((a) => a.saturation === "saturated").length;
  const total = Math.max(coverage.length, 1);

  // trigger strength(连续)
  const clusters = findRefutationClusters({ min_size: 3, limit: 5 });
  const maxIdeaCluster = clusters.length ? Math.max(...clusters.map((c) => c.size)) : 0;
  const maxAngleCluster = _maxAngleCluster();
  const maxCluster = Math.max(maxIdeaCluster, maxAngleCluster);
  const nGaps = _countFillGaps();

  const trigger = {
    generalize: Math.min(1.0, maxCluster / _CLUSTER_SCALE),
    fill: Math.min(1.0, nGaps / _GAP_SCALE),
    explore: (nFresh / total) * (nSaturated / total),
  };

  // diversity bonus + score
  const r2 = (v) => Math.round(v * 1000) / 1000;
  const scores = {};
  for (const op of Object.keys(trigger)) {
    const ratio = recent.length ? recent.filter((o) => o === op).length / recent.length : 0;
    const diversity = 1.0 - ratio * _DIV_PENALTY;
    scores[op] = r2(trigger[op] * diversity);
  }

  const best = Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0];
  return {
    recommended: best,
    score: scores[best],
    scores,
    trigger: Object.fromEntries(Object.entries(trigger).map(([k, v]) => [k, r2(v)])),
    max_cluster: maxCluster,
    n_gaps: nGaps,
    n_fresh: nFresh,
    n_saturated: nSaturated,
    recent_operations: recent,
    fresh_angles: coverage.filter((a) => a.saturation === "unexplored" || a.saturation === "thin").map((a) => a.code).sort(),
    saturated_angles: coverage.filter((a) => a.saturation === "saturated").map((a) => a.code).sort(),
  };
}
