import { test } from "node:test";
import assert from "node:assert";
import { healthSchema, healthHandler } from "../tools/health.mjs";

test("healthSchema 是合法的 MCP tool definition", () => {
  assert.equal(healthSchema.name, "health");
  assert.equal(healthSchema.description.length > 0, true);
  assert.deepEqual(healthSchema.inputSchema, { type: "object", properties: {} });
});

test("healthHandler 返回 ok=true 和时间戳", async () => {
  const result = await healthHandler({});
  assert.equal(result.ok, true);
  assert.equal(typeof result.ts, "string");
  assert.equal(result.ts.length > 0, true);
});
