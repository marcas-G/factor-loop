import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as factorDb from "../../lib/factor-db.mjs";

const SCHEMA = fs.readFileSync(
  path.resolve(import.meta.dirname, "../../../core/db/schema.sql"),
  "utf8"
);

// factor-db.mjs 的 _db 是 module-level 单例,所有 test 共用一个 tmp db。
// 用不同 xname + 相对断言避免相互干扰。
let _init = false;
function setup() {
  if (_init) return;
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "iter-test-"));
  factorDb.init({ dbPath: path.join(tmp, "t.db") });
  const d = factorDb.init();
  d.exec(SCHEMA);
  _init = true;
}
function addFactor(xname, status, icir) {
  const d = factorDb.init();
  d.prepare("INSERT OR REPLACE INTO factors (xname, status, latest_icir) VALUES (?, ?, ?)")
    .run(xname, status, icir);
}

test("openIteration 开 open + 幂等(同 from+change 返回同 id)", () => {
  setup();
  addFactor("A_open", "evaluated", 3.0);
  const id1 = factorDb.openIteration("A_open", { changeNote: "换 horizon" });
  const id2 = factorDb.openIteration("A_open", { changeNote: "换 horizon" });
  assert.equal(id1, id2, "同 from+change 应幂等返回同 id");
  const id3 = factorDb.openIteration("A_open", { changeNote: "换品种" });
  assert.notEqual(id1, id3, "不同 change 应新建");
});

test("claimIteration: open→in_progress;非 open 不可 claim", () => {
  setup();
  addFactor("A_claim", "evaluated", 2.0);
  const id = factorDb.openIteration("A_claim", { changeNote: "c_claim" });
  const r = factorDb.claimIteration(id);
  assert.equal(r.ok, true);
  const r2 = factorDb.claimIteration(id);  // 已 in_progress
  assert.equal(r2.ok, false, "非 open 不可 claim");
});

test("realizeIteration: outcome 由 icir_delta 自动推导", () => {
  setup();
  addFactor("A_realize", "evaluated", 2.0);
  addFactor("B_realize", "evaluated", 1.0);

  // improved: delta > 0.02
  const id1 = factorDb.openIteration("A_realize", { changeNote: "imp" });
  factorDb.claimIteration(id1);
  const r1 = factorDb.realizeIteration(id1, "B_realize", { icirDelta: 1.5 });
  assert.equal(r1.outcome, "improved");

  // declined: delta < -0.02
  const id2 = factorDb.openIteration("A_realize", { changeNote: "dec" });
  factorDb.claimIteration(id2);
  const r2 = factorDb.realizeIteration(id2, "B_realize", { icirDelta: -1.0 });
  assert.equal(r2.outcome, "declined");

  // neutral: |delta| ≤ 0.02
  const id3 = factorDb.openIteration("A_realize", { changeNote: "neu" });
  factorDb.claimIteration(id3);
  const r3 = factorDb.realizeIteration(id3, "B_realize", { icirDelta: 0.01 });
  assert.equal(r3.outcome, "neutral");
});

test("reopenIteration: in_progress→open;非 in_progress 不可 reopen", () => {
  setup();
  addFactor("A_reopen", "evaluated", 2.0);
  const id = factorDb.openIteration("A_reopen", { changeNote: "c_reopen" });
  factorDb.claimIteration(id);
  const r = factorDb.reopenIteration(id);
  assert.equal(r.ok, true);
  const r2 = factorDb.reopenIteration(id);  // 已 open
  assert.equal(r2.ok, false, "非 in_progress 不可 reopen");
});

test("listOpenIterations: priority 排序(evaluated强因子 > dead_end弱因子)", () => {
  setup();
  addFactor("Hi_eval", "evaluated", 5.0);    // pri = 2.0 × 5.0 × decay
  addFactor("Lo_dead", "dead_end", 0.3);     // pri = 0.5 × 0.1(bound) × decay
  factorDb.openIteration("Hi_eval", { changeNote: "精进" });
  factorDb.openIteration("Lo_dead", { changeNote: "重试" });
  const list = factorDb.listOpenIterations({ topK: 50 });
  const hiIdx = list.findIndex((r) => r.from_xname === "Hi_eval");
  const loIdx = list.findIndex((r) => r.from_xname === "Lo_dead");
  assert.ok(hiIdx >= 0 && loIdx >= 0, "两者都应在 open 列表");
  assert.ok(hiIdx < loIdx, "evaluated 强因子 priority 应高于 dead_end 弱因子");
});
