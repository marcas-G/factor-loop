// 端到端验证 factor-db 的写入路径（不调 LLM，模拟 research-loop 的关键 DB 调用）
import * as factorDb from "./factor-db.mjs";
import fs from "node:fs";
import path from "node:path";

const CWD = "/home/lgao/work/quant";
const TMP_H = path.join(CWD, "factors", "_t4_smoke_test_factor.h");

// 准备：写一个测试用的 .h 文件（带 frontmatter）
const FACTOR_CODE = `// ---
// xname: T4SmokeTest_w5
// class_name: T4SmokeTest
// file: _t4_smoke_test_factor.h
// formula: |
//   alpha = rolling_mean(mid_price, 5)
// description: |
//   T4 端到端测试用，可删除
// tags: [test, smoke]
// params: {window: 5}
// parent_xname: null
// idea_id: null
// status: draft
// created_ts: 2026-06-18
// ---
#pragma once
class T4SmokeTest : public FeedIndicator {};
`;

console.log("=== 1. 准备测试 .h ===");
fs.writeFileSync(TMP_H, FACTOR_CODE);
console.log("写入:", TMP_H);

console.log("\n=== 2. addIdea ===");
const ideaId = factorDb.addIdea("T4 smoke test idea");
console.log("ideaId:", ideaId);

console.log("\n=== 3. addFactorFromHFile（应解析 frontmatter 入库）===");
const xname = factorDb.addFactorFromHFile(TMP_H, ideaId, { status: "evaluated" });
console.log("xname:", xname);

console.log("\n=== 4. addEval（模拟评估完成 ICIR=2.5）===");
factorDb.addEval(xname, new Date().toISOString(),
  { ic_mean: 0.04, icir: 2.5, sharpe: 1.8, rank_ic: 0.05 },
  ideaId, "/tmp/test_eval_output", "full"
);
console.log("写入 factor_evals + 更新 latest_*");

console.log("\n=== 5. addIteration（模拟 retry 改代码后重 submit）===");
// fromXname 必须先存在（FK 约束）：手动插入一个父因子
import { DatabaseSync as _DB } from "node:sqlite";
const _db = new _DB(path.join(CWD, "factors.db"));
_db.prepare("INSERT INTO factors (xname, status) VALUES (?, 'dead_end')").run("T4SmokeTest_v0");
factorDb.addIteration("T4SmokeTest_v0", xname, ideaId, "fix deque init", "improved", 0.5);
console.log(`写入 iterations: T4SmokeTest_v0 → ${xname}`);

console.log("\n=== 6. addLessons（模拟 evaluate 输出原子 lesson，仅 check_done）===");
const lessons = [
  { type: "success_pattern", xname, text: "[T4SmokeTest] ICIR=2.5 实验成功且信号强", evidence: { xname, icir: 2.5 } },
  { type: "dead_end", xname: "T4SmokeTest_v0", text: "[T4SmokeTest] 测试 dead_end 类 lesson（ICIR=0.3）", evidence: { xname: "T4SmokeTest_v0", icir: 0.3 } },
  { type: "next_direction", text: "应当被新 schema 拒绝（已废弃 type）" },
];
const ids = factorDb.addLessons(lessons, ideaId);
console.log("写入 lesson ids:", ids);

console.log("\n=== 7. 验证写入结果 ===");
console.log("factors 总数:", factorDb.countFactors());
console.log("evaluated 总数:", factorDb.countEvaluated());
console.log("lessons 总数:", factorDb.countLessons());

// 查询校验
import { DatabaseSync } from "node:sqlite";
const db = new DatabaseSync(path.join(CWD, "factors.db"), { allowExtension: true });
db.loadExtension("/home/lgao/.local/lib/python3.9/site-packages/sqlite_vec/vec0.so");
const f = db.prepare("SELECT status, latest_icir, latest_ic FROM factors WHERE xname = ?").get(xname);
console.log(`factors.${xname}: status=${f.status} IC=${f.latest_ic} ICIR=${f.latest_icir}`);
const ev = db.prepare("SELECT ic_mean, icir, eval_mode FROM factor_evals WHERE factor_xname = ? ORDER BY id DESC LIMIT 1").get(xname);
console.log(`factor_evals: ic=${ev.ic_mean} icir=${ev.icir} mode=${ev.eval_mode}`);
const iter = db.prepare("SELECT from_xname, to_xname, outcome, icir_delta FROM iterations WHERE to_xname = ?").get(xname);
console.log(`iterations: ${iter.from_xname} → ${iter.to_xname} outcome=${iter.outcome} delta=${iter.icir_delta}`);
const ls = db.prepare("SELECT type, scope, text FROM lessons WHERE idea_id = ? ORDER BY id").all(ideaId);
console.log(`lessons (idea_id=${ideaId}):`);
for (const l of ls) console.log(`  [${l.type}/${l.scope}] ${l.text}`);

console.log("\n=== 8. extractMetrics 测试 ===");
const m = factorDb.extractMetrics("IC: 0.038\nICIR: 2.8\nSharpe: 1.9\nRank IC: 0.04");
console.log("解析结果:", m);

console.log("\n=== 清理 ===");
db.prepare("DELETE FROM factor_tags WHERE factor_xname = ?").run(xname);
db.prepare("DELETE FROM factor_evals WHERE factor_xname = ?").run(xname);
db.prepare("DELETE FROM iterations WHERE from_xname = ? OR to_xname = ?").run(xname, xname);
db.prepare("DELETE FROM idea_factor_links WHERE factor_xname = ?").run(xname);
// 先删 lessons（FK 引用 factors），再删 factors
db.prepare("DELETE FROM lessons WHERE idea_id = ? OR text LIKE ?").run(ideaId, "%T4SmokeTest%");
db.prepare("DELETE FROM factors WHERE xname IN (?, ?)").run(xname, "T4SmokeTest_v0");
db.prepare("DELETE FROM ideas WHERE id = ?").run(ideaId);
db.prepare("DELETE FROM tags WHERE name IN ('test', 'smoke')").run();
fs.unlinkSync(TMP_H);
console.log("已清理测试数据 + 删除 .h");

console.log("\n=== ALL OK ===");
