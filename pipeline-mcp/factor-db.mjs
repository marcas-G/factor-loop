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
const CWD = path.resolve(import.meta.dirname, "..");
const DB_PATH = path.join(CWD, "factors.db");
// 所有 python 调用统一走独立 venv（系统 python3 缺 sqlite_vec）
const VENV_PY = process.env.QUANT_VENV_PY || "/home/lgao/quant-venv/bin/python";
const PY = fs.existsSync(VENV_PY) ? VENV_PY : "python3";
const VEC0_SO = findVec0So();

// status 取值（与 schema.sql CHECK 约束一致）
const VALID_STATUS = ["draft", "submitted", "evaluated", "failed", "dead_end"];
const VALID_LESSON_TYPE = ["dead_end", "success_pattern"];
const VALID_LESSON_SCOPE = ["factor"];

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

export function init({ dbPath = DB_PATH } = {}) {
  if (_db) return _db;
  _db = new DatabaseSync(dbPath, { allowExtension: true });
  _db.loadExtension(VEC0_SO);
  _db.exec("PRAGMA foreign_keys = ON");
  migrateLessonsSchema();
  return _db;
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
  const { runPy } = await import("./run-py.mjs");
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
// opts: { sevenDim, conditionalReturns, significant, mode, status }
//   sevenDim            — 7 维评估的 JSON 对象，存到 factor_evals.seven_dim
//   conditionalReturns  — deep 分析的条件收益 JSON，存到 factor_evals.conditional_returns
//   significant         — 0/1，外部根据 verdict 决定（不再内部用 ICIR 阈值判断）
//   mode                — eval_mode 字段，默认 full
//   status              — 强制设 factors.status（"evaluated" / "dead_end"），不传则不动 factors 表
export function addEval(xname, ts, metrics, ideaId = null, rawPath = null, opts = {}) {
  const m = metrics || {};
  const conn = db();
  const mode = opts.mode || "full";
  const significant = opts.significant != null ? Number(opts.significant) : 0;
  const sevenDimJson = opts.sevenDim ? JSON.stringify(opts.sevenDim) : null;
  const condRetJson = opts.conditionalReturns ? JSON.stringify(opts.conditionalReturns) : null;

  conn.prepare(
    `INSERT INTO factor_evals
       (factor_xname, idea_id, ts, symbol, freq, ic_mean, icir, sharpe, rank_ic,
        seven_dim, conditional_returns, eval_mode, significant, raw_path)
     VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    xname, ideaId, ts,
    m.ic_mean ?? null, m.icir ?? null, m.sharpe ?? null, m.rank_ic ?? null,
    sevenDimJson, condRetJson,
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
      SELECT from_xname AS x, 1 AS depth FROM iterations WHERE to_xname = ?
      UNION ALL
      SELECT i.from_xname, c.depth + 1 FROM iterations i JOIN chain c ON i.to_xname = c.x
    )
    SELECT x AS xname, depth FROM chain ORDER BY depth
  `).all(xname);
  const descendants = d.prepare(`
    WITH RECURSIVE chain AS (
      SELECT to_xname AS x, 1 AS depth FROM iterations WHERE from_xname = ?
      UNION ALL
      SELECT i.to_xname, c.depth + 1 FROM iterations i JOIN chain c ON i.from_xname = c.x
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
  const { runPy } = await import("./run-py.mjs");
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
  const { runPy } = await import("./run-py.mjs");
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
  const { runPy } = await import("./run-py.mjs");
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
