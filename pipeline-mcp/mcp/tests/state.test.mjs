import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import { runInit, runLoad, runSave, runList, setRunsRoot } from "../lib/run-store.mjs";

function useTempRunsRoot() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-test-"));
  setRunsRoot(tmp);
  return tmp;
}

test("runInit 创建新 run_id 和 state.json", async () => {
  useTempRunsRoot();
  const { run_id } = await runInit({ idea: "测试 idea" });
  assert.equal(typeof run_id, "string");
  assert.match(run_id, /^\d{4}-\d{2}-\d{2}-/);
  const state = await runLoad(run_id);
  assert.equal(state.idea, "测试 idea");
  assert.equal(state.status, "running");
});

test("runSave 浅 merge 顶级字段", async () => {
  useTempRunsRoot();
  const { run_id } = await runInit({ idea: "x" });
  await runSave(run_id, { status: "paused", note: "中断" });
  const state = await runLoad(run_id);
  assert.equal(state.status, "paused");
  assert.equal(state.note, "中断");
  assert.equal(state.idea, "x"); // 原字段保留
});

test("runSave 路径式 patch（factors.0.failure_layer）", async () => {
  useTempRunsRoot();
  const { run_id } = await runInit({ idea: "x", factors: [
    { name: "A" }, { name: "B" },
  ] });
  await runSave(run_id, { "factors.0.failure_layer": "check_done" });
  const state = await runLoad(run_id);
  assert.equal(state.factors[0].failure_layer, "check_done");
  assert.equal(state.factors[1].name, "B"); // 未动
});

test("runList 列所有 run（按 started_at 倒序）", async () => {
  useTempRunsRoot();
  await runInit({ idea: "first" });
  await new Promise(r => setTimeout(r, 10));
  await runInit({ idea: "second" });
  const list = await runList();
  assert.equal(list.length, 2);
  assert.equal(list[0].idea, "second"); // 最新的在前
});

test("runLoad 对不存在的 run_id 抛错", async () => {
  useTempRunsRoot();
  await assert.rejects(() => runLoad("9999-01-01-nonexistent"), /不存在/);
});
