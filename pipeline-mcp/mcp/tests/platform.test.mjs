import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as tools from "../tools/platform.mjs";

test("submit_factor 在 mock 模式返回 ok=true", async () => {
  process.env.QUANT_MCP_MOCK_PLATFORM = "1";
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "quant-mcp-test-"));
  const factorFile = path.join(tmpDir, "Test.h");
  fs.writeFileSync(factorFile, `// xname: Test\n#pragma once\nclass Test {};`);
  const result = await tools.submitFactorHandler({
    xname: "Test",
    factorFile,
    categories: ["IF"],
    params: {},
  });
  assert.equal(result.ok, true);
  assert.equal(typeof result.features, "string");
  delete process.env.QUANT_MCP_MOCK_PLATFORM;
});

test("check_factor mock：返回 {failureLayer,summary}，evidence 落 state", async () => {
  process.env.QUANT_MCP_MOCK_PLATFORM = "1";
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-"));
  process.env.QUANT_MCP_RUNS_ROOT = tmpRoot;
  const { runInit, runLoad } = await import("../lib/run-store.mjs");
  const { run_id } = await runInit({ factors: [{ name: "Test" }] });
  const result = await tools.checkFactorHandler({
    xname: "Test",
    submitRef: { features: "Test", ok: true },
    checkOutput: "/tmp/dummy",
    run_id,
    factor_index: 0,
  });
  assert.equal(result.failureLayer, "check_done");
  assert.equal(typeof result.summary, "string");
  assert.equal("evidence" in result, false); // 返回值不含 evidence
  // evidence 由工具内部 run_save 落 state（不经 agent 手）
  const state = await runLoad(run_id);
  assert.equal(typeof state.factors[0].evidence, "object");
  assert.equal(state.factors[0].failure_layer, "check_done");
  delete process.env.QUANT_MCP_MOCK_PLATFORM;
  delete process.env.QUANT_MCP_RUNS_ROOT;
});

test("platform schema 名称正确", () => {
  const names = tools.ALL_PLATFORM_SCHEMAS.map(s => s.name);
  assert.deepEqual(names.sort(), ["check_factor", "submit_factor"]);
});

test("retryWithRename: 换名 + 重 submit + 重 check 成功 → 返回新结果", async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "factors-test-"));
  const oldFile = path.join(tmpDir, "Foo.h");
  fs.writeFileSync(oldFile, `// xname: Foo\n#pragma once\nclass Foo {};`);
  const factor = { name: "Foo", factor_file: oldFile, categories: ["AG"], params: {} };
  const submitFn = async (f) => ({ ok: true, features: f.name });
  const checkFn = async () => ({ failureLayer: "check_done", evidence: { reason: "mock" }, summary: "done" });
  const retried = await tools.retryWithRename({ xname: "Foo", factor, checkOutput: tmpDir, submitFn, checkFn });
  assert.ok(retried, "应返回重试结果");
  assert.equal(retried.result.failureLayer, "check_done");
  assert.equal(retried.result._renameInfo.newXname, "Foo2");
  assert.ok(fs.existsSync(path.join(tmpDir, "Foo2.h")));
});

test("retryWithRename: 新 check 仍 missing → null（真代码问题不自愈）", async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "factors-test-"));
  const oldFile = path.join(tmpDir, "Bar.h");
  fs.writeFileSync(oldFile, `// xname: Bar\n#pragma once\nclass Bar {};`);
  const factor = { name: "Bar", factor_file: oldFile };
  const submitFn = async (f) => ({ ok: true, features: f.name });
  const checkFn = async () => ({ failureLayer: "check_output_missing", evidence: {}, summary: "still missing" });
  const retried = await tools.retryWithRename({ xname: "Bar", factor, checkOutput: tmpDir, submitFn, checkFn });
  assert.equal(retried, null);
});

test("check_factor mock：DAG 缓存陷阱自愈（首次 missing+全零 → 换名 → check_done）", async () => {
  process.env.QUANT_MCP_MOCK_PLATFORM = "1";
  process.env.QUANT_MCP_MOCK_ZERO_FIRST = "1";
  const { setRunsRoot, runInit, runLoad } = await import("../lib/run-store.mjs");
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-"));
  setRunsRoot(tmpRoot);
  // factor 需有 factor_file（retryWithRename 依赖）+ categories/params（重 submit 用）
  const factorsDir = fs.mkdtempSync(path.join(os.tmpdir(), "factors-"));
  const factorFile = path.join(factorsDir, "CacheTrap.h");
  fs.writeFileSync(factorFile, `// xname: CacheTrap\n#pragma once\nclass CacheTrap {};`);
  const { run_id } = await runInit({ factors: [{ name: "CacheTrap" }] });
  // runInit 不保留 factor_file/categories/params（由 agent 后续 run_save 写，模拟之）
  const { runSave } = await import("../lib/run-store.mjs");
  await runSave(run_id, {
    "factors.0.factor_file": factorFile,
    "factors.0.categories": ["AG"],
    "factors.0.params": {},
  });
  const checkOutput = path.join(os.tmpdir(), `check-${run_id}`);
  const result = await tools.checkFactorHandler({
    xname: "CacheTrap",
    submitRef: { features: "CacheTrap", ok: true },
    checkOutput,
    run_id,
    factor_index: 0,
  });
  // 救回 check_done
  assert.equal(result.failureLayer, "check_done");
  // state：name/xname/factor_file 更新为新名 + retry_trace 含 dag_cache_rename
  const state = await runLoad(run_id);
  assert.equal(state.factors[0].name, "CacheTrap2");
  assert.equal(state.factors[0].xname, "CacheTrap2");
  assert.match(state.factors[0].factor_file, /CacheTrap2\.h$/);
  const renameTrace = state.factors[0].retry_trace.find(t => t.fix === "dag_cache_rename");
  assert.ok(renameTrace, "retry_trace 应含 dag_cache_rename 记录");
  assert.match(renameTrace.summary, /CacheTrap→CacheTrap2/);
  delete process.env.QUANT_MCP_MOCK_PLATFORM;
  delete process.env.QUANT_MCP_MOCK_ZERO_FIRST;
});
