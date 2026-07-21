import { test } from "node:test";
import assert from "node:assert";

import * as graph from "../tools/graph-traversal.mjs";
import * as factorDb from "../tools/factor-db.mjs";
import * as persist from "../tools/persist.mjs";
import * as hypothesis from "../tools/hypothesis-chain.mjs";
import * as discover from "../tools/discover.mjs";
import * as platform from "../tools/platform.mjs";
import * as state from "../tools/state.mjs";

// server.mjs 聚合的 7 组(health 单独,不在 ALL_ 聚合)
const GROUPS = [
  ["graph", graph.ALL_GRAPH_TRAVERSAL_SCHEMAS, graph.ALL_GRAPH_TRAVERSAL_HANDLERS],
  ["factor-db", factorDb.ALL_FACTOR_DB_SCHEMAS, factorDb.ALL_FACTOR_DB_HANDLERS],
  ["persist", persist.ALL_PERSIST_SCHEMAS, persist.ALL_PERSIST_HANDLERS],
  ["hypothesis", hypothesis.ALL_HYPOTHESIS_SCHEMAS, hypothesis.ALL_HYPOTHESIS_HANDLERS],
  ["discover", discover.ALL_DISCOVER_SCHEMAS, discover.ALL_DISCOVER_HANDLERS],
  ["platform", platform.ALL_PLATFORM_SCHEMAS, platform.ALL_PLATFORM_HANDLERS],
  ["state", state.ALL_STATE_SCHEMAS, state.ALL_STATE_HANDLERS],
];

test("每组: 每个 schema.name 有对应函数 handler(不漏)", () => {
  for (const [name, schemas, handlers] of GROUPS) {
    assert.ok(schemas.length > 0, `${name} 无 schema`);
    for (const s of schemas) {
      assert.equal(typeof s.name, "string", `${name} schema 缺 name`);
      assert.ok(s.name.length > 0, `${name} schema.name 空`);
      assert.equal(typeof handlers[s.name], "function", `${name}.${s.name} handler 缺或非函数`);
    }
  }
});

test("每组 schema.name 唯一(无重复注册)", () => {
  for (const [name, schemas] of GROUPS) {
    const names = schemas.map((s) => s.name);
    assert.equal(new Set(names).size, names.length, `${name} 有重复 schema.name: ${names}`);
  }
});

test("MCP 工具总数 = 44(7 组;health 另 +1 = 45)", () => {
  const sum = GROUPS.reduce((a, [, s]) => a + s.length, 0);
  assert.equal(sum, 44, `7 组应 44(graph15+factor-db16+persist3+hypothesis2+discover2+platform2+state4),实际 ${sum}`);
});
