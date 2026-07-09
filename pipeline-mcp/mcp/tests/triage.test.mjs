import { test } from "node:test";
import assert from "node:assert";

import { triageFailure } from "../../airflow-log.mjs";
import { decideFailureLayer } from "../../stages/check.mjs";

// —— 纯函数：合成 triage 对象覆盖各决策分支（不依赖网络） ——
const triage = (o) => ({ triaged: true, dagState: "failed", signals: { compile: [], crash: [], traceback: [], exit_codes: [] }, exitCode: null, rootTask: "t", locus: "setup", causeText: "", rawTail: "", ...o });

test("decideFailureLayer: compile locus + 编译错 → compile_failed", () => {
  const d = decideFailureLayer(triage({ locus: "compile", rootTask: "GenerateXs.build_model", signals: { compile: ["F.h:9: error: x"], crash: [], traceback: [], exit_codes: [] }, causeText: "F.h:9: error: x" }));
  assert.equal(d.layer, "compile_failed");
  assert.match(d.diagnosis.nature, /编译失败/);
});

test("decideFailureLayer: runtime locus + exit 134 → factor_runtime_crash", () => {
  const d = decideFailureLayer(triage({ locus: "runtime", rootTask: "GenerateXs.generate_xy", exitCode: 134, signals: { compile: [], crash: ["Aborted (core dumped)"], traceback: [], exit_codes: ["134=SIGABRT"] } }));
  assert.equal(d.layer, "factor_runtime_crash");
  assert.match(d.diagnosis.nature, /运行期崩溃/);
  // 诊断必须点名最常见的"容器未 resize 越界"
  assert.match(d.diagnosis.root_cause_candidates.join(" "), /resize/);
});

test("decideFailureLayer: runtime locus + SIGSEGV 139 → factor_runtime_crash", () => {
  const d = decideFailureLayer(triage({ locus: "runtime", rootTask: "GenerateXs.generate_xy", exitCode: 139, signals: { compile: [], crash: ["Segmentation fault"], traceback: [], exit_codes: ["139=SIGSEGV"] } }));
  assert.equal(d.layer, "factor_runtime_crash");
});

test("decideFailureLayer: runtime locus + 非崩溃 exit≠0 → factor_runtime_error", () => {
  const d = decideFailureLayer(triage({ locus: "runtime", rootTask: "GenerateXs.generate_xy", exitCode: 1, signals: { compile: [], crash: [], traceback: [], exit_codes: ["1=non-zero"] } }));
  assert.equal(d.layer, "factor_runtime_error");
});

test("decideFailureLayer: setup/infra locus + 信号 → platform_transient（不重写因子）", () => {
  // 实现语义：有确凿信号(exitCode/signals)才 platform_transient；无信号不甩锅平台
  const d = decideFailureLayer(triage({ locus: "setup", rootTask: "GenerateXs.zip_xy_files", exitCode: 1, signals: { compile: [], crash: [], traceback: [], exit_codes: ["1=zip 失败"] } }));
  assert.equal(d.layer, "platform_transient");
  assert.equal(d.diagnosis, null);
});

test("decideFailureLayer: setup/infra locus + 无信号 → check_failed（不甩锅平台）", () => {
  // signals 全空 + exitCode null（log 缺失/分诊失败）→ check_failed，避免无据甩锅平台
  const d = decideFailureLayer(triage({ locus: "setup", rootTask: "GenerateXs.configs", exitCode: null }));
  assert.equal(d.layer, "check_failed");
});

// —— 端到端：真实 Airflow 日志 → triageFailure → decideFailureLayer ——
// 这两个因子本轮真实失败过（run e9hmsv）：f0 运行期 SIGABRT、f1 编译错。
test("真实 f0 SectorDepthPressureRankPolar → factor_runtime_crash", async () => {
  const tg = await triageFailure({ factorName: "SectorDepthPressureRankPolar" });
  if (!tg.ok || !tg.triaged) { console.log("  [skip] f0 dag 不可分诊（可能已重跑/清理）:", tg._reason || tg.dagState); return; }
  assert.equal(tg.locus, "runtime", `f0 根因应是 runtime locus(generate_xy)，实际 ${tg.locus}`);
  assert.equal(tg.exitCode, 134, `f0 exitCode 应 134，实际 ${tg.exitCode}`);
  const d = decideFailureLayer(tg);
  assert.equal(d.layer, "factor_runtime_crash", `f0 应判 factor_runtime_crash，实际 ${d.layer}`);
  assert.ok((tg.causeText || "").length > 0, "f0 causeText 不应为空（旧版会空 stderr）");
  console.log("  f0 causeText:", tg.causeText.replace(/\n/g, " | "));
});

test("真实 f1 ExtremeZoneDepthRankFlip → compile_failed", async () => {
  const tg = await triageFailure({ factorName: "ExtremeZoneDepthRankFlip" });
  if (!tg.ok || !tg.triaged) { console.log("  [skip] f1 dag 不可分诊:", tg._reason || tg.dagState); return; }
  assert.equal(tg.locus, "compile", `f1 根因应是 compile locus(build_model)，实际 ${tg.locus}`);
  assert.ok(tg.signals.compile.length >= 1, "f1 应抽到编译错");
  const d = decideFailureLayer(tg);
  assert.equal(d.layer, "compile_failed", `f1 应判 compile_failed，实际 ${d.layer}`);
});
