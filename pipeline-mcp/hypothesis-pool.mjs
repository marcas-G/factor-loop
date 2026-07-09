import fs from "node:fs";
import path from "node:path";

// ============================================================
// hypothesis-pool.mjs — 假设生成框架(第二种 idea 来源,和 inspiration-pool 同构)
// 机制同构 inspiration-pool:PROFIT_SOURCES × DIMENSIONS × COMPATIBILITY × 权重 → sampleCoordinates
// 内容来自 .claude/hypothesis-framework.md(tick 因子本质分析框架),结构化核心,不丢信息
// ============================================================

// L1 利润来源(对标 META_HEURISTICS;候选清单,非穷尽/不互斥——见 framework §2)
export const PROFIT_SOURCES = [
  { id:"L1", name:"别人的机械反应",   who_loses:"止损/强平/追涨者",         constraint:"机械反应存在 ∧ 收益>推价成本",       valid_500ms:true },
  { id:"L2", name:"流动性补偿",       who_loses:"逆向选择承担方(价差/返佣)", constraint:"价差收益>逆向选择损失",             valid_500ms:true },
  { id:"L3", name:"信息优势",         who_loses:"信息滞后者",               constraint:"信息优势>获取成本 ∧ 未泄露",        valid_500ms:true },
  { id:"L4", name:"速度优势",         who_loses:"慢方",                     constraint:"速度差存在",                       valid_500ms:false },  // 500ms 失效
  { id:"L5", name:"风险溢价",         who_loses:"风险补偿承担方",           constraint:"承担风险有补偿",                   valid_500ms:"短周期几近为零" },
];

// L2 三道门槛(校验清单,framework §4 总纲)
export const GATES = [
  { id:"G1", name:"闭环闭合",                check:"必须回答赚谁的什么钱,不停在意图/代理/行为" },
  { id:"G2", name:"因果链完整(含微观E)",     check:"七节填满;E 可分解到分量,禁聚合净量" },
  { id:"G3", name:"复杂度可控",              check:"n≥2 需机制逻辑可复述,不能算子硬拼" },
];

// L3 因果链七节(framework §3)
export const CAUSAL_CHAIN = [
  { node:"①", name:"行动者", desc:"谁(赚方)" },
  { node:"②", name:"动机",   desc:"赚谁的什么钱(L1-L5)+ 闭环约束" },
  { node:"③", name:"触发",   desc:"什么条件下行动(含上下文 C)" },
  { node:"④", name:"行动",   desc:"做什么(下单/撤单/移档)" },
  { node:"⑤", name:"痕迹E",  desc:"t-1→t 可分解微观事件,只用分量" },
  { node:"⑥", name:"反推",   desc:"E∧C → 预测对象(方向/分布/状态/路径)" },
  { node:"⑦", name:"失效",   desc:"闭环约束何时断" },
];

// L4 微观E 分量清单(framework §3 ⑤ + §5.2)
export const MICRO_E = [
  "add_i(加单,各档)",
  "cancel_i(撤单,各档)",
  "各档 bid/ask price Δ",
  "各档 bid/ask size Δ",
  "Δtotal_volume(成交量)",
  "Δturnover(成交额)",
  "Δopen_interest(持仓)",
  "dt(快照间隔)",
  "Δlast_trade_price(成交价)",
];

// L5 假设构造维度(对标 inspiration-pool DIMENSIONS,维度换成框架的)
export const DIMENSIONS = {
  actor:      ["做市商","知情者","止损/强平者","hunter/点火者","套利者","持仓大户","散户跟风"],
  micro_e:    MICRO_E,
  prediction: ["方向","分布(波动率)","状态(regime)","路径(先延续后反转)"],
  horizon:    ["1s","5s","10s","60s","300s"],
  context:    ["连续竞价常态","集合竞价","夜盘","关键位附近","高波动regime","低波动压缩","流动性薄","大单冲击后"],
};

// 权重持久化(对标 inspiration-pool,独立文件不混)
const WEIGHTS_FILE = path.join(import.meta.dirname, ".hypothesis-weights.json");

function loadWeights() {
  try { return JSON.parse(fs.readFileSync(WEIGHTS_FILE, "utf8")); } catch { return {}; }
}
function saveWeights(weights) {
  fs.writeFileSync(WEIGHTS_FILE, JSON.stringify(weights, null, 2));
}

// 语义约束(对标 COMPATIBILITY_RULES):过滤不合框架的组合
// 每条规则 return false = 拒绝该组合
const COMPATIBILITY_RULES = [
  // 1. L4 速度:500ms 失效,直接拒绝
  (c) => c.profit_source !== "L4",
  // 2. L5 风险溢价:短周期几近为零,短 horizon 拒绝
  (c) => !(c.profit_source === "L5" && ["1s","5s","10s"].includes(c.horizon)),
  // 3. actor 必须和 profit_source 匹配(闭环自洽,framework §2 闭合判据)
  (c) => {
    const { profit_source: L, actor: a } = c;
    if (L === "L1" && !/止损|强平|hunter|点火|散户/.test(a)) return false;
    if (L === "L2" && !/做市商/.test(a)) return false;
    if (L === "L3" && !/知情|做市商|大户/.test(a)) return false;
    if (L === "L5" && !/持仓|套利/.test(a)) return false;
    return true;
  },
  // 4. 路径预测需长 horizon(多步演化)
  (c) => !(c.prediction === "路径(先延续后反转)" && ["1s","5s"].includes(c.horizon)),
  // 5. add/cancel 分量需挂单行为 actor(加撤是挂单方行为)
  (c) => {
    const { micro_e: e, actor: a } = c;
    if (/add_i|cancel_i/.test(e) && !/做市商|知情|hunter|大户/.test(a)) return false;
    return true;
  },
];

function isCompatible(coords) {
  return COMPATIBILITY_RULES.every(rule => rule(coords));
}

function weightedPick(items, weights) {
  const total = weights.reduce((a, b) => a + b, 0);
  if (total <= 0) return items[Math.floor(Math.random() * items.length)];
  let r = Math.random() * total;
  for (let i = 0; i < items.length; i++) {
    r -= weights[i];
    if (r <= 0) return items[i];
  }
  return items[items.length - 1];
}

function getDimWeights(dimName, items, weights, invert = false) {
  const dimW = weights[dimName] || {};
  return items.map(it => {
    const w = typeof dimW[it] === "number" ? dimW[it] : 1.0;
    return invert ? 1 / Math.max(w, 0.1) : w;
  });
}

function getProfitWeights(weights, invert = false) {
  const pw = weights.__profit__ || {};
  return PROFIT_SOURCES.map(p => {
    const w = typeof pw[p.id] === "number" ? pw[p.id] : 1.0;
    return invert ? 1 / Math.max(w, 0.1) : w;
  });
}

// 主采样函数(对标 inspiration-pool sampleCoordinates)
// mode: "weighted" | "adversarial" | "random" | "mixed"(默认)
// mixed = 70% weighted / 20% adversarial / 10% random
// 返回 n 组假设构造 coords
export function sampleCoordinates(n = 1, { mode = "mixed" } = {}) {
  const weights = loadWeights();
  const result = [];
  const maxTries = n * 100;
  let tries = 0;

  while (result.length < n && tries < maxTries) {
    tries++;

    let currentMode = mode;
    if (mode === "mixed") {
      const r = Math.random();
      currentMode = r < 0.7 ? "weighted" : r < 0.9 ? "adversarial" : "random";
    }
    const invert = currentMode === "adversarial";
    const useWeight = currentMode !== "random";

    const ps = weightedPick(
      PROFIT_SOURCES,
      useWeight ? getProfitWeights(weights, invert) : PROFIT_SOURCES.map(() => 1.0)
    );

    const coords = { profit_source: ps.id };
    for (const dimName of Object.keys(DIMENSIONS)) {
      const items = DIMENSIONS[dimName];
      const w = useWeight ? getDimWeights(dimName, items, weights, invert) : items.map(() => 1.0);
      coords[dimName] = weightedPick(items, w);
    }

    if (!isCompatible(coords)) continue;

    result.push({
      profit_source: { id: ps.id, name: ps.name, who_loses: ps.who_loses, constraint: ps.constraint },
      actor:      coords.actor,
      micro_e:    coords.micro_e,
      prediction: coords.prediction,
      horizon:    coords.horizon,
      context:    coords.context,
    });
  }

  return result;
}

// coords → prompt 片段(给 LLM 的结构化输入,对标 formatCoordinates)
export function formatCoordinates(coordsList) {
  return coordsList.map((c, i) => `候选 ${i + 1}
- 利润来源:${c.profit_source.id} ${c.profit_source.name}(赚:${c.profit_source.who_loses};约束:${c.profit_source.constraint})
- 行动者:${c.actor}
- 微观E分量:${c.micro_e}
- 预测对象:${c.prediction}
- horizon:${c.horizon}
- 上下文:${c.context}

按 .claude/hypothesis-framework.md 三道门槛(G1 闭环闭合 / G2 因果链含微观E / G3 复杂度)构造 1 个合规假设,产出 30-80 字 idea 文本。E 必须落到分量,禁聚合净量(净+10 可能是 加15撤5 或 加12撤10,含义不同)。`).join("\n\n");
}

// 权重回写(对标 updateWeights,验证后 backprop)
// score: 因子验证得分,>0 好,<0 差(建议传入归一化后的 IC 或 Sharpe)
export function updateWeights(coords, score, lr = 0.1) {
  if (!coords || !coords.profit_source) return;
  const weights = loadWeights();
  if (!weights.__profit__) weights.__profit__ = {};

  const sign = Math.sign(score);
  const magnitude = Math.min(Math.abs(score), 2);
  const factor = 1 + lr * sign * magnitude;

  const oldW = weights.__profit__[coords.profit_source.id] || 1.0;
  weights.__profit__[coords.profit_source.id] = Math.max(0.1, Math.min(5.0, oldW * factor));

  for (const dimName of ["actor", "micro_e", "prediction", "horizon", "context"]) {
    if (!weights[dimName]) weights[dimName] = {};
    const old = weights[dimName][coords[dimName]] || 1.0;
    weights[dimName][coords[dimName]] = Math.max(0.1, Math.min(5.0, old * factor));
  }

  saveWeights(weights);
}
