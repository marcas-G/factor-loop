import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as factorDb from "../../factor-db.mjs";
import * as tools from "../tools/persist.mjs";

const SCHEMA_SQL_PATH = path.resolve(import.meta.dirname, "../../../factor_db/schema.sql");

// 用临时 sqlite 做隔离测试（参考 factor-db.test.mjs 模式）。
// factor-db.mjs 的 _db 是 module-level 单例（init 短路），首个 init 决定 dbPath。
let _initialized = false;
function setupTempDb() {
  if (_initialized) return;
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "quant-mcp-test-"));
  const dbPath = path.join(tmpDir, "test.db");
  factorDb.init({ dbPath });
  const d = factorDb.init();
  d.exec(fs.readFileSync(SCHEMA_SQL_PATH, "utf8"));
  _initialized = true;
}

// 写一个最小合法 .h 文件（addFactorFromHFile 会调 python3 parse_frontmatter）。
// 本测试组的 submit_failed 路径在 persistVerdict 内短路，不会真正调用解析，
// 所以这里只保证文件存在、格式接近合法即可。
function writeMockFactorFile(dir, name) {
  const content = `// xname: ${name}
// formula: test formula
// params: {}
/*
XCLASS ${name} : public FeedIndicator<...>
*/
#pragma once
class ${name} {};`;
  const p = path.join(dir, `${name}.h`);
  fs.writeFileSync(p, content);
  return p;
}

test("persist_idea 返回 idea id", async () => {
  setupTempDb();
  const result = await tools.persistIdeaHandler({ text: "测试 idea" });
  assert.equal(typeof result.id, "number");
  assert.ok(result.id > 0);
});

test("persist_factor 对 failureLayer != check_done 返回 {ok:false}", async () => {
  setupTempDb();
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-"));
  process.env.QUANT_MCP_RUNS_ROOT = tmpRoot;
  const { runInit, runSave } = await import("../lib/run-store.mjs");
  // 建 run，把 factor[0] 设成 submit_failed（非 check_done）
  const { run_id } = await runInit({ factors: [{ name: "TestAlpha" }] });
  await runSave(run_id, { "factors.0.failure_layer": "submit_failed" });
  const result = await tools.persistFactorHandler({
    run_id,
    factor_index: 0,
    verdict: { verdict: "pass" },
  });
  assert.equal(result.ok, false);
  assert.match(result.error, /check_done/);
  delete process.env.QUANT_MCP_RUNS_ROOT;
});

test("persist schema 名称正确", () => {
  const names = tools.ALL_PERSIST_SCHEMAS.map((s) => s.name);
  assert.deepEqual(names.sort(), ["persist_candidates", "persist_factor", "persist_idea"]);
});

test("persist_candidates 写入 state.idea/idea_id/factors[].name（不丢 schema 字段）", async () => {
  setupTempDb();
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-"));
  const { setRunsRoot, runInit, runLoad } = await import("../lib/run-store.mjs");
  setRunsRoot(tmpRoot);
  const { run_id } = await runInit({});
  const result = await tools.persistCandidatesHandler({
    run_id,
    idea_text: "测试 idea 文本",
    factors: [{
      name: "TestFactor",
      formula: "f = x",
      intuition: "直觉假设",
      diff_check: "退化差异",
      coord_usage: "坐标用法",
      categories: ["AG", "CU"],
      tags: ["trade_price", "volume"],
      params: { L: 50 },
      db_research: { searched: ["x"], found_dead_ends: [], found_similar: [], borrowed_from: "无" },
    }],
  });
  assert.ok(result.idea_id > 0);
  assert.equal(result.n_factors, 1);
  const state = await runLoad(run_id);
  // 关键: idea/idea_id 必须落盘（原 bug: runSave 拒顶级 factors 导致整 patch 丢失）
  assert.equal(state.idea, "测试 idea 文本");
  assert.equal(state.idea_id, result.idea_id);
  // 关键: factors[].name 等 schema 字段必须落盘（原 bug: persist_factor 读不到 name）
  assert.equal(state.factors[0].name, "TestFactor");
  assert.equal(state.factors[0].formula, "f = x");
  assert.equal(state.factors[0].hypothesis, "直觉假设\n\n退化差异\n\n坐标用法");
  assert.deepEqual(state.factors[0].categories, ["AG", "CU"]);
  assert.deepEqual(state.factors[0].tags, ["trade_price", "volume"]);
  assert.equal(state.factors[0].status, "pending");
});
