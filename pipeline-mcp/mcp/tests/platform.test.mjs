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
