import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as factorDb from "../../lib/factor-db.mjs";
import * as tools from "../tools/hypothesis-chain.mjs";

const SCHEMA_SQL_PATH = path.resolve(import.meta.dirname, "../../../core/db/schema.sql");

// 用临时 sqlite 做隔离测试（参考 persist.test.mjs 模式）。
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

// 一个合法的必然假设论证链（Kyle 式：超加性耦合 + extremum 唯一性）
const VALID_CHAIN = {
  background_axioms: ["市场半强式有效", "存在噪声交易者可藏订单"],
  superadditive_coupling: {
    A: "最大化信息租金",
    B: "不瞬时暴露价格",
    C: "分批均匀交易",
    entailment_proof: "最大化要求全仓,但全仓暴露→矛盾,只有匀散能同时满足",
    superadditivity_proof: "A单独⊢全仓,B单独⊢不交易,只有A∧B⊢匀散",
    minimality: "匀散是满足双约束的最弱策略,无更弱解",
  },
  constraint: "最大化信息租金 ∧ 不瞬时暴露价格",
  uniqueness_proof: {
    type: "extremum",
    reasoning: "期望利润函数在可行域(交易速率受噪声流约束)内严格凹,严格凹函数有唯一极大",
  },
  competing_explanations: [
    { rival: "做市商被动报价", distinguishing_observation: "订单流方向性", exclusion_test: "看主动成交方向" },
  ],
  falsifiable_trace: "价格冲击线性 Δp=λe,λ在交易窗口内恒定",
};

test("persist_argument_chain 写入并返回 idea_id", async () => {
  setupTempDb();
  const result = await tools.persistArgumentChainHandler({
    text: "知情者必然分批均匀交易,价格冲击线性",
    argument_chain: VALID_CHAIN,
  });
  assert.equal(typeof result.idea_id, "number");
  assert.ok(result.idea_id > 0);
});

test("hypothesis_get 读回论证链(JSON 反序列化往返)", async () => {
  setupTempDb();
  const { idea_id } = await tools.persistArgumentChainHandler({
    text: "测试假设",
    argument_chain: VALID_CHAIN,
  });
  const r = await tools.getHypothesisHandler({ idea_id });
  assert.equal(r.ok, true);
  assert.equal(r.id, idea_id);
  assert.equal(r.text, "测试假设");
  assert.deepEqual(r.argument_chain, VALID_CHAIN);
  assert.equal(r.argument_chain.uniqueness_proof.type, "extremum");
  assert.equal(r.status, "open");
});

test("hypothesis_get 不存在的 idea_id 返回 ok:false", async () => {
  setupTempDb();
  const r = await tools.getHypothesisHandler({ idea_id: 999999 });
  assert.equal(r.ok, false);
});

test("schema 名称正确", () => {
  const names = tools.ALL_HYPOTHESIS_SCHEMAS.map((s) => s.name);
  assert.deepEqual(names.sort(), ["hypothesis_get", "persist_argument_chain"]);
});

test("argument_chain 落在 ideas 表(非 factors 表)——层级正确", async () => {
  setupTempDb();
  const { idea_id } = await tools.persistArgumentChainHandler({
    text: "层级测试",
    argument_chain: VALID_CHAIN,
  });
  // 直接查 ideas 表,确认 argument_chain 列有值 + support_score 默认值正确
  const d = factorDb.init();
  const row = d.prepare(
    "SELECT argument_chain, support_score, evaluated_factor_count FROM ideas WHERE id = ?"
  ).get(idea_id);
  assert.ok(row.argument_chain != null, "argument_chain 应在 ideas 表有值");
  const chain = JSON.parse(row.argument_chain);
  assert.equal(chain.uniqueness_proof.type, "extremum");
  assert.equal(row.evaluated_factor_count, 0);
  assert.equal(row.support_score, null);
});

test("necessity_grade 落库 + 读回", async () => {
  setupTempDb();
  const { idea_id } = await tools.persistArgumentChainHandler({
    text: "identification 级假设(Roll 式)",
    argument_chain: VALID_CHAIN,
    necessity_grade: "identification",
  });
  const r = await tools.getHypothesisHandler({ idea_id });
  assert.equal(r.necessity_grade, "identification");
  // 直接查 ideas 表确认 necessity_grade 列有值
  const d = factorDb.init();
  const row = d.prepare("SELECT necessity_grade FROM ideas WHERE id = ?").get(idea_id);
  assert.equal(row.necessity_grade, "identification");
});

test("necessity_grade 缺省为 null（向后兼容）", async () => {
  setupTempDb();
  const { idea_id } = await tools.persistArgumentChainHandler({
    text: "未分级假设",
    argument_chain: VALID_CHAIN,
  });
  const r = await tools.getHypothesisHandler({ idea_id });
  assert.equal(r.necessity_grade, null);
});

test("updateIdeaSupportScore 贝叶斯聚合(1pass/1fail=0.5)", async () => {
  setupTempDb();
  const { idea_id } = await tools.persistArgumentChainHandler({
    text: "支持度测试假设", argument_chain: VALID_CHAIN,
  });
  const d = factorDb.init();
  // 模拟 2 因子挂该 idea: 一 evaluated(pass) 一 dead_end(fail)
  d.prepare("INSERT INTO factors (xname, status) VALUES (?, 'evaluated')").run("Fpass");
  d.prepare("INSERT INTO factors (xname, status) VALUES (?, 'dead_end')").run("Ffail");
  d.prepare("INSERT INTO idea_factor_links (idea_id, factor_xname) VALUES (?, 'Fpass')").run(idea_id);
  d.prepare("INSERT INTO idea_factor_links (idea_id, factor_xname) VALUES (?, 'Ffail')").run(idea_id);
  const r = factorDb.updateIdeaSupportScore(idea_id);
  assert.equal(r.pass, 1);
  assert.equal(r.total, 2);
  assert.ok(Math.abs(r.score - 0.5) < 1e-9, `score 应 0.5, got ${r.score}`);
  const h = factorDb.getHypothesis(idea_id);
  assert.equal(h.evaluated_factor_count, 2);
  assert.ok(Math.abs(h.support_score - 0.5) < 1e-9);
});

test("updateIdeaSupportScore 小样本收缩(1/1 不强判 1.0)", async () => {
  setupTempDb();
  const { idea_id } = await tools.persistArgumentChainHandler({
    text: "小样本测试", argument_chain: VALID_CHAIN,
  });
  const d = factorDb.init();
  d.prepare("INSERT INTO factors (xname, status) VALUES (?, 'evaluated')").run("F1");
  d.prepare("INSERT INTO idea_factor_links (idea_id, factor_xname) VALUES (?, 'F1')").run(idea_id);
  // 1/1 pass → 贝叶斯 (1+1)/(1+2)=0.667,非 1.0(小样本收缩向 0.5)
  const r = factorDb.updateIdeaSupportScore(idea_id);
  assert.equal(r.pass, 1);
  assert.equal(r.total, 1);
  assert.ok(Math.abs(r.score - 2/3) < 1e-9, `score 应 0.667, got ${r.score}`);
});

test("updateIdeaSupportScore 无因子时 score=null", async () => {
  setupTempDb();
  const { idea_id } = await tools.persistArgumentChainHandler({
    text: "无因子假设", argument_chain: VALID_CHAIN,
  });
  const r = factorDb.updateIdeaSupportScore(idea_id);
  assert.equal(r.total, 0);
  assert.equal(r.score, null);
});

test("migrateIdeasSchema 幂等：重复 init 不报错不丢列", () => {
  setupTempDb();
  // init 内部短路(_db 已设),再调 migrateIdeasSchema 的等价检查
  const d = factorDb.init();
  const cols = d.prepare("PRAGMA table_info(ideas)").all().map((c) => c.name);
  for (const col of ["argument_chain", "support_score", "evaluated_factor_count", "support_score_computed_at"]) {
    assert.ok(cols.includes(col), `ideas 表应有列 ${col}`);
  }
});
