import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as factorDb from "../../lib/factor-db.mjs";
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

// 回归:persist_factor 删除"入库后否决"后,pass 忠实落 evaluated、不再被内部冗余检查降级;
// fail 落 dead_end。锁定"工具不再改 agent 的 verdict"。
test("persist_factor pass 忠实落 evaluated(不内部降级)", async () => {
  setupTempDb();
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-"));
  const { setRunsRoot, runInit, runSave } = await import("../lib/run-store.mjs");
  setRunsRoot(tmpRoot);
  const factorFile = writeMockFactorFile(tmpRoot, "TestPassFactor");
  const { run_id } = await runInit({ factors: [{ name: "TestPassFactor" }] });
  await runSave(run_id, {
    "factors.0.failure_layer": "check_done",
    "factors.0.factor_file": factorFile,
    "factors.0.evidence": {
      eval_metrics: {
        core_metrics: { screening: { ic_mean: 0.05, icir: 3.0, spearman: 0.04 } },
        deep_best: { rank_ic_max: 0.05 },
      },
    },
  });
  const result = await tools.persistFactorHandler({
    run_id,
    factor_index: 0,
    verdict: { verdict: "pass", key_strengths: ["正交新颖"], key_weaknesses: [] },
  });
  assert.equal(result.status, "evaluated", "pass 应落 evaluated,不被内部冗余否决降级");
  assert.equal(result.xname, "TestPassFactor");
  assert.ok(result.lessonId > 0);
});

test("persist_factor fail 落 dead_end", async () => {
  setupTempDb();
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-"));
  const { setRunsRoot, runInit, runSave } = await import("../lib/run-store.mjs");
  setRunsRoot(tmpRoot);
  const factorFile = writeMockFactorFile(tmpRoot, "TestFailFactor");
  const { run_id } = await runInit({ factors: [{ name: "TestFailFactor" }] });
  await runSave(run_id, {
    "factors.0.failure_layer": "check_done",
    "factors.0.factor_file": factorFile,
    "factors.0.evidence": {
      eval_metrics: {
        core_metrics: { screening: { ic_mean: 0.01, icir: 0.5 } },
        deep_best: { rank_ic_max: 0.01 },
      },
    },
  });
  const result = await tools.persistFactorHandler({
    run_id,
    factor_index: 0,
    verdict: { verdict: "fail", key_strengths: [], key_weaknesses: ["冗余"], suggested_iteration: "换品种" },
  });
  assert.equal(result.status, "dead_end");
  assert.ok(result.lessonId > 0);
});

// 回归:assess "先 persist 入库 → 查正交发现冗余 → 二次 persist 改判" 依赖 persist_factor
// 二次调用幂等改判(addFactorFromHFile 幂等 + 追加 eval + 更新 status + support 重算)。
test("persist_factor 二次调用改判(pass→fail 更新 status)", async () => {
  setupTempDb();
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-"));
  const { setRunsRoot, runInit, runSave } = await import("../lib/run-store.mjs");
  setRunsRoot(tmpRoot);
  const factorFile = writeMockFactorFile(tmpRoot, "TestFlipFactor");
  const { run_id } = await runInit({ factors: [{ name: "TestFlipFactor" }] });
  await runSave(run_id, {
    "factors.0.failure_layer": "check_done",
    "factors.0.factor_file": factorFile,
    "factors.0.evidence": {
      eval_metrics: {
        core_metrics: { screening: { ic_mean: 0.05, icir: 3.0, spearman: 0.04 } },
        deep_best: { rank_ic_max: 0.05 },
      },
    },
  });
  // 第一次:初判 pass → evaluated
  const r1 = await tools.persistFactorHandler({
    run_id,
    factor_index: 0,
    verdict: { verdict: "pass", key_strengths: ["正交"], key_weaknesses: [] },
  });
  assert.equal(r1.status, "evaluated");
  // 第二次:入库后正交检查发现冗余,改判 fail → dead_end(幂等不报错)
  const r2 = await tools.persistFactorHandler({
    run_id,
    factor_index: 0,
    verdict: { verdict: "fail", key_strengths: [], key_weaknesses: ["IC 行为冗余 vs X |r|=0.8"] },
  });
  assert.equal(r2.status, "dead_end", "二次 persist 应把 status 从 evaluated 改判为 dead_end");
});

// 回归:assess 新流程 prepare(入表占位 draft, 不写 eval/lesson)→ 查正交 → commit(定 verdict)。
test("persist_factor prepare→commit(prepare 占位不写eval, commit 定verdict)", async () => {
  setupTempDb();
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-"));
  const { setRunsRoot, runInit, runSave } = await import("../lib/run-store.mjs");
  setRunsRoot(tmpRoot);
  const factorFile = writeMockFactorFile(tmpRoot, "TestPrepareFactor");
  const { run_id } = await runInit({ factors: [{ name: "TestPrepareFactor" }] });
  await runSave(run_id, {
    "factors.0.failure_layer": "check_done",
    "factors.0.factor_file": factorFile,
    "factors.0.evidence": {
      eval_metrics: {
        core_metrics: { screening: { ic_mean: 0.05, icir: 3.0, spearman: 0.04 } },
        deep_best: { rank_ic_max: 0.05 },
      },
    },
  });
  // prepare: 入表 draft, 不写 eval/lesson, 不定 verdict
  const rp = await tools.persistFactorHandler({ run_id, factor_index: 0, mode: "prepare" });
  assert.equal(rp.mode, "prepare");
  assert.equal(rp.status, "draft");
  assert.equal(rp.xname, "TestPrepareFactor");
  // commit: 定 verdict pass → evaluated(draft→evaluated)
  const rc = await tools.persistFactorHandler({
    run_id,
    factor_index: 0,
    mode: "commit",
    verdict: { verdict: "pass", key_strengths: ["正交"], key_weaknesses: [] },
  });
  assert.equal(rc.status, "evaluated");
  assert.ok(rc.lessonId > 0);
});
