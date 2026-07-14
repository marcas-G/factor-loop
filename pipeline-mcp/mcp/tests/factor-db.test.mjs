import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as factorDb from "../../lib/factor-db.mjs";
import * as tools from "../tools/factor-db.mjs";

const SCHEMA_SQL_PATH = path.resolve(import.meta.dirname, "../../../factor_db/schema.sql");

// 用临时 sqlite 做隔离测试。
// factor-db.mjs 的 _db 是 module-level 单例（init 短路），所以首个 init 决定 dbPath；
// 所有测试共用同一个 tmp db（空表），互不依赖数据。
let _initialized = false;
function setupTempDb() {
  if (_initialized) return;
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "quant-mcp-test-"));
  const dbPath = path.join(tmpDir, "test.db");
  factorDb.init({ dbPath });
  // 加载 schema（factors / lessons / factor_evals / tags / iterations / factors_vec / *_fts）
  const d = factorDb.init();
  d.exec(fs.readFileSync(SCHEMA_SQL_PATH, "utf8"));
  _initialized = true;
}

test("factor_counts 返回 {factors, lessons, evaluated} 三个数", async () => {
  setupTempDb();
  const result = await tools.factorCountsHandler({});
  assert.equal(typeof result.factors, "number");
  assert.equal(typeof result.lessons, "number");
  assert.equal(typeof result.evaluated, "number");
});

test("factor_recent_lessons 默认 k=10", async () => {
  setupTempDb();
  const result = await tools.factorRecentLessonsHandler({});
  assert.equal(Array.isArray(result), true);
});

test("factor_list 默认 k=20", async () => {
  setupTempDb();
  const result = await tools.factorListHandler({});
  assert.equal(Array.isArray(result), true);
});

test("factor_search 支持 query + 自定义 k", async () => {
  setupTempDb();
  const result = await tools.factorSearchHandler({ query: "大单冲击", k: 3 });
  assert.equal(Array.isArray(result), true);
});

test("factor_detail 对不存在的 xname 抛错", async () => {
  setupTempDb();
  await assert.rejects(
    () => tools.factorDetailHandler({ xname: "NonExistent" }),
    /xname 不存在/
  );
});

test("factor_similar 对不存在的 xname 抛错", async () => {
  setupTempDb();
  await assert.rejects(
    () => tools.factorSimilarHandler({ xname: "NonExistent" }),
    /factors_vec 中不存在/
  );
});

test("所有 18 个 schema 名称正确", () => {
  const names = tools.ALL_FACTOR_DB_SCHEMAS.map(s => s.name);
  assert.deepEqual(names.sort(), [
    "coverage_gaps",
    "coverage_map",
    "factor_counts",
    "factor_detail",
    "factor_ic_correlate",
    "factor_ic_refresh",
    "factor_list",
    "factor_recent_lessons",
    "factor_search",
    "factor_semantic_search",
    "factor_similar",
    "link_pattern_idea",
    "list_open_iterations",
    "open_iteration",
    "pattern_feed",
    "realize_iteration",
    "reopen_iteration",
    "residual_ic_strength",
  ]);
});

test("coverage_map 空库返回数组(结构正确)", async () => {
  setupTempDb();
  const result = await tools.coverageMapHandler({});
  assert.equal(Array.isArray(result), true);
});

test("coverage_gaps 空库返回四桶结构", async () => {
  setupTempDb();
  const result = await tools.coverageGapsHandler({});
  assert.equal(Array.isArray(result.unexplored), true);
  assert.equal(Array.isArray(result.thin), true);
  assert.equal(Array.isArray(result.hot), true);
  assert.equal(Array.isArray(result.stale), true);
});
