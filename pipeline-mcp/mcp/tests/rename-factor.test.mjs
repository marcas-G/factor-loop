import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import { toSnake, nextUniqueXname, renameFactorH } from "../../stages/rename-factor.mjs";
import { isAllZeroFromScreening, maxZeroRatioFromScreening } from "../../lib/metrics.mjs";

test("toSnake: PascalCase → snake_case（含缩写词 BHHI/BPDiff）", () => {
  assert.equal(toSnake("TradeRunVolAccel"), "trade_run_vol_accel");
  assert.equal(toSnake("TradeRunVolAccel2"), "trade_run_vol_accel2");
  assert.equal(toSnake("BHHI"), "bhhi");                            // 全大写缩写不拆
  assert.equal(toSnake("BPDiff"), "bp_diff");                       // 缩写 BP + Diff
  assert.equal(toSnake("BPDiffSkew"), "bp_diff_skew");
  assert.equal(toSnake("CrossFeedCancelCoherenceGate"), "cross_feed_cancel_coherence_gate");
});

test("nextUniqueXname: 剥离已有数字尾缀后递增，跳过已存在", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "factors-test-"));
  // 无冲突：→ 2
  assert.equal(nextUniqueXname("TradeRunVolAccel", tmpDir, null), "TradeRunVolAccel2");
  // 文件已存在 → 跳到 3
  fs.writeFileSync(path.join(tmpDir, "TradeRunVolAccel2.h"), "// mock");
  assert.equal(nextUniqueXname("TradeRunVolAccel", tmpDir, null), "TradeRunVolAccel3");
  // 剥离已有尾缀：TradeRunVolAccel5 → base TradeRunVolAccel → 2(存在)→3
  assert.equal(nextUniqueXname("TradeRunVolAccel5", tmpDir, null), "TradeRunVolAccel3");
  // existsInDb 注入命中 → 跳过
  assert.equal(nextUniqueXname("X", tmpDir, (x) => x === "X2"), "X3");
});

test("renameFactorH: 改 class/xname frontmatter/names stem，旧 token 无独立残留", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "factors-test-"));
  const oldFile = path.join(tmpDir, "TradeRunVolAccel.h");
  fs.writeFileSync(oldFile, `// ---
// xname: TradeRunVolAccel
// class_name: TradeRunVolAccel
// tags: [trade_price, volume]
// ---
#pragma once
class TradeRunVolAccel : public FeedIndicator {
public:
  static const std::vector<std::string> names() {
    std::string p = "ls5";
    return { "trade_run_vol_accel_" + p };
  }
};
`);
  const { newXname, newFile } = renameFactorH("TradeRunVolAccel", oldFile, tmpDir, null);
  assert.equal(newXname, "TradeRunVolAccel2");
  assert.equal(newFile, path.join(tmpDir, "TradeRunVolAccel2.h"));
  assert.ok(fs.existsSync(newFile));
  const content = fs.readFileSync(newFile, "utf8");
  // 新 token 出现
  assert.match(content, /\bclass TradeRunVolAccel2 :/);
  assert.match(content, /\/\/ xname: TradeRunVolAccel2/);
  assert.match(content, /"trade_run_vol_accel2_"/);
  // 旧 token 无独立残留（\b 边界：TradeRunVolAccel2 不算 TradeRunVolAccel 残留）
  assert.equal(/\bTradeRunVolAccel\b/.test(content), false);
  assert.equal(/\btrade_run_vol_accel\b/.test(content), false);
});

test("isAllZeroFromScreening: zero_ratio max>=0.999 → true", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "check-test-"));
  const featureKey = "TestFactor";
  const dir = path.join(tmpDir, featureKey, "dailyX", `${featureKey}_feval`);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "screening.csv"), "zero_ratio\n1.0\n0.5\n");
  assert.equal(isAllZeroFromScreening(tmpDir, featureKey), true);
});

test("isAllZeroFromScreening: 全 <0.999 → false", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "check-test-"));
  const featureKey = "TestFactor";
  const dir = path.join(tmpDir, featureKey, "dailyX", `${featureKey}_feval`);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "screening.csv"), "zero_ratio\n0.5\n0.3\n");
  assert.equal(isAllZeroFromScreening(tmpDir, featureKey), false);
});

test("isAllZeroFromScreening: 文件缺失 → false", () => {
  assert.equal(isAllZeroFromScreening("/nonexistent-path", "X"), false);
});

test("maxZeroRatioFromScreening: 返回 max zero_ratio(factor2 稀疏场景 0.996)", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "check-test-"));
  const featureKey = "TestFactor";
  const dir = path.join(tmpDir, featureKey, "dailyX", `${featureKey}_feval`);
  fs.mkdirSync(dir, { recursive: true });
  // 模拟 factor 2: 99.6% 为零(zero_ratio=0.996)→ 应判 too_small(稀疏 rewrite) 而非 missing(transient 重试)
  fs.writeFileSync(path.join(dir, "screening.csv"), "zero_ratio\n0.996\n0.95\n");
  const z = maxZeroRatioFromScreening(tmpDir, featureKey);
  assert.ok(z != null && Math.abs(z - 0.996) < 1e-9, `expected ~0.996, got ${z}`);
});

test("maxZeroRatioFromScreening: 文件缺失 → null", () => {
  assert.equal(maxZeroRatioFromScreening("/nonexistent-path", "X"), null);
});
