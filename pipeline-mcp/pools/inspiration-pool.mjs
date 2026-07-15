import fs from "node:fs";
import path from "node:path";

// L1 元启发池：跨领域思维模式，提供"怎么想"的方向
export const META_HEURISTICS = [
  // A. 变换视角
  { id: "A1", name: "反转", hint: "把信号方向反过来。多头预测能否作为空头预警？", guide: "反着想——哪些市场机制下反向版本反而更稳定。" },
  { id: "A2", name: "极值化", hint: "在历史极值（最大成交量、最大波动、最大持仓变化）时信号表现？", guide: "极值状态下参与者结构变化（套保进场、止损触发），信号可能换一套规律。" },
  { id: "A3", name: "反事实", hint: "如果这个信号不存在，市场会有什么不同？", guide: "反事实揭示信号在解释什么——流动性提供？知情交易？噪声？" },
  { id: "A4", name: "缩放", hint: "把信号从 tick 压到日 / 从日拉到 tick，行为差异？", guide: "不同尺度下参与者不同——tick 是高频做市商主导，日是机构主导。" },
  { id: "A5", name: "去趋势", hint: "去掉整体趋势后，信号还有预测力吗？", guide: "区分'预测趋势'还是'预测均值回归'——去趋势后才知道。" },

  // B. 边界与极端状态
  { id: "B1", name: "失效边界", hint: "在什么状态下信号会失效？前兆是什么？", guide: "失效前兆本身就是另一个可交易信号。" },
  { id: "B2", name: "极端状态测试", hint: "涨跌停附近、主力换月、夜盘开盘、政策发布——信号行为？", guide: "极端状态下的稳定性比平均 IC 更重要。" },
  { id: "B3", name: "流动性约束", hint: "流动性极差时，信号是否还能用？", guide: "流动性差时成本爆炸——理论 IC 高不代表能赚钱。" },
  { id: "B4", name: "尾部风险", hint: "信号在大亏损时的表现——是不是单向亏损？", guide: "单向亏损意味着信号在特定状态完全失效，比平均 Sharpe 更值得警惕。" },

  // C. 关系与传导
  { id: "C1", name: "跨类比迁移", hint: "把 X 品种的微观结构套到 Y 上（螺纹→铁矿、原油→PTA）。", guide: "同板块品种微观结构有共性，但参与者结构差异会改变信号强度。" },
  { id: "C2", name: "上下游传导", hint: "产业链上下游谁先动？滞后多久？", guide: "上游通常领先下游——但这种关系会随产业政策变化。" },
  { id: "C3", name: "替代品套利", hint: "豆油-棕榈-菜油的相对强弱，价差何时回归？", guide: "替代品价差有均值回归特性，但极端供需下会单边走。" },
  { id: "C4", name: "跨期结构", hint: "近月-远月信号差异，曲线形态变化。", guide: "近月反映现货，远月反映预期——差异本身就是期限结构信号。" },
  { id: "C5", name: "跨市场", hint: "内盘 vs 外盘（LME、CBOT、新加坡铁矿）信号传导。", guide: "内外盘联动有时差——夜盘是国内吸收外盘变化的关键时段。" },

  // D. 时间动态
  { id: "D1", name: "衰减曲线", hint: "信号预测力随时间衰减？最佳 hold time？", guide: "衰减曲线形态是因子的'指纹'——陡降 vs 平缓区别巨大。" },
  { id: "D2", name: "季节性", hint: "日内 / 周内 / 月度季节性——开盘、收盘、午休前后。", guide: "国内期货有独特节奏——夜盘开盘、午休、收盘前 30 分钟参与者结构不同。" },
  { id: "D3", name: "状态切换", hint: "趋势 vs 震荡——信号不同状态下表现。", guide: "同一信号在趋势和震荡下可能完全相反——必须分状态测。" },
  { id: "D4", name: "持续 vs 反转", hint: "信号预测短还是长？持续还是反转？", guide: "高频多为反转（流动性补偿），低频多为持续（信息扩散）。" },

  // E. 信息论与统计
  { id: "E1", name: "稀疏性", hint: "信号是不是只少数样本点有效？大部分时间是噪声？", guide: "稀疏信号需要状态过滤——只在特定条件下激活。" },
  { id: "E2", name: "非线性", hint: "信号和收益是线性还是有阈值效应？", guide: "阈值效应意味着极端值才有用——平均 IC 会低估真实价值。" },
  { id: "E3", name: "条件独立", hint: "信号和现有因子正交还是冗余？", guide: "跟现有因子相关性 > 0.7 基本就是冗余——挖出来也没增量。" },
  { id: "E4", name: "信息泄露", hint: "有没有未来函数风险？", guide: "L2 数据预处理最易踩——撤单时间戳对齐、主力换月点、夜盘归属。" },

  // F. 行为与博弈
  { id: "F1", name: "持仓者结构", hint: "套保 vs 投机 vs 套利——他们的行为模式。", guide: "套保盘有周期性（交割前），投机盘追随事件，套利盘关注价差。" },
  { id: "F2", name: "大单意图", hint: "大单是建仓还是诱多/诱空？", guide: "拆单痕迹、冰山订单、盘前盘后行为——意图比方向更难识别。" },
  { id: "F3", name: "撤单行为", hint: "撤单方向不对称性暴露什么意图？", guide: "撤单比成交更早暴露意图——撤买多于撤卖往往预示空头建仓。" },
  { id: "F4", name: "集体行为", hint: "跨品种盘口联动——是不是有知情交易者在建仓？", guide: "同板块多品种同步异动通常是大资金在配置——领先单品种信号。" },
  { id: "F5", name: "博弈反转", hint: "当大家都用这个信号时，它会反向失效吗？", guide: "因子拥挤是真实风险——一旦被广泛使用，反向会成为新 alpha。" },

  // G. 方法论
  { id: "G1", name: "简化", hint: "能不能用最简单的形式表达？", guide: "复杂因子过拟合风险高——简化版本往往更稳健。" },
  { id: "G2", name: "稳健性扫描", hint: "参数稍微变一下，信号还在吗？", guide: "参数 ±20% 还有效的因子才是真因子。" },
  { id: "G3", name: "失败案例", hint: "历史上最惨的几次亏损，分别什么原因？", guide: "失败案例比成功案例更有信息——它们揭示因子的脆弱点。" },
];

// L2 维度取值池：6 个正交维度
export const DIMENSIONS = {
  data_source: [
    "多档盘口（10 档买卖价量）",
    "逐笔成交（价、量、方向、时间）",
    "逐笔委托（价、量、方向）— L2 独有",
    "撤单流（撤单价、量、方向、时延）— L2 独有",
    "成交量剖面（按价位的量分布）",
    "持仓量及变化",
    "跨合约数据（近月、远月、主力、次主力同步）",
    "跨品种数据（产业链、替代品同步）",
    "集合竞价数据（开盘前、收盘前盘口）",
    "涨跌停板附近盘口",
    "大单识别（量阈值过滤）",
    "毫秒/微秒级时间戳细粒度",
  ],
  microstructure_operator: [
    "OFI（订单流不平衡）",
    "盘口压力比（bid/ask depth ratio）",
    "主买卖占比",
    "撤单方向不对称",
    "大单冲击",
    "Kyle lambda（价格冲击系数）",
    "VPIN（成交量知情概率）",
    "多档盘口'质量'（近档 vs 远档挂单比）",
    "集合竞价模式",
    "spoofing 检测（虚假挂单）",
    "撮合速度（成交频率瞬间变化）",
    "价差动态（spread 波动与压缩）",
  ],
  time_scale: [
    "tick（毫秒）",
    "秒级（1s / 5s / 10s）",
    "1 分钟",
    "5 分钟",
    "15 分钟",
    "30 分钟",
    "60 分钟",
    "日内分段（夜盘开盘 / 早盘 / 上午 / 下午 / 收盘前 30 分钟）",
    "跨日（持仓过夜）",
    "跨周",
  ],
  relation: [
    "单品种",
    "同品种跨期（近月-远月、主力-次主力）",
    "产业链上下游（螺纹-铁矿-焦煤-焦炭）",
    "替代品（豆油-棕榈-菜油）",
    "同板块（化工、有色、黑色）",
    "全市场情绪（多品种综合）",
    "内外盘联动（沪铜-LME铜、新加坡铁矿-大连铁矿）",
    "股期联动（IF/IH/IC vs 指数）",
    "商品'风险偏好'代理（与股票、债券相关性）",
    "跨周期对齐（不同时间尺度信号叠加）",
  ],
  transform: [
    // —— 基础时序 ——
    "原始值（level）",
    "一阶差分",
    "二阶差分（加速度）",
    "对数收益",
    "滞后项（lag）",
    "EMA / WMA（指数/加权移动平均）",
    "滚动均值",
    "滚动标准差",
    "滚动偏度/峰度",
    "滚动极值（滚动 min/max）",
    "自相关 ACF / PACF、AR 系数",
    // —— 标准化 / 分布变换 ——
    "z-score",
    "排名（rank）",
    "分位数",
    "去极值 winsorize / MAD",
    "Box-Cox / Yeo-Johnson 正态化",
    "分位数变换（映射到正态）",
    "sigmoid / tanh 压缩",
    // —— 回归 / 统计建模 ——
    "OLS / 稳健回归 beta、残差",
    "滚动回归（时变 beta）",
    "GARCH / EGARCH 波动率建模",
    "PCA / 统计因子模型",
    "分位数回归",
    "协整残差",
    // —— 信号处理 ——
    "哈尔小波",
    "HP 滤波（趋势-周期分解）",
    "卡尔曼滤波（隐状态估计）",
    "傅里叶 / STFT（频域分解）",
    "希尔伯特变换（瞬时相位/幅度）",
    // —— 信息论 ——
    "信息熵",
    "互信息",
    "KL 散度（分布漂移）",
    "转移熵（信息流方向）",
    // —— 非线性 / 阈值 ——
    "阈值分段（piecewise）",
    "指示函数 / 哑变量（事件触发）",
    "符号变换、绝对值",
    "多项式展开",
    "交互项（A×B）",
    // —— 距离 / 相似 ——
    "DTW（动态时间规整）",
    "马氏距离",
    "余弦相似度",
  ],
  state: [
    "高波动 vs 低波动（波动率分位）",
    "主力换月期（换月前后 N 天）",
    "政策窗口（会议、数据发布前后）",
    "夜盘 vs 日盘",
    "涨跌停板附近",
    "大单冲击后",
    "趋势 vs 震荡",
    "季节性月份（农产品收获季等）",
    "流动性紧缩期",
    "极端价格区域（创 N 日新高/新低）",
  ],
};

// 权重持久化：{ __meta__: {id: w}, dim_name: {value: w} }
// 权重文件与本文件同目录(pipeline-mcp 根),自动跟随 clone 位置
const WEIGHTS_FILE = path.join(import.meta.dirname, ".inspiration-weights.json");

function loadWeights() {
  try {
    return JSON.parse(fs.readFileSync(WEIGHTS_FILE, "utf8"));
  } catch {
    return {};
  }
}

function saveWeights(weights) {
  fs.writeFileSync(WEIGHTS_FILE, JSON.stringify(weights, null, 2));
}

// 语义约束：过滤不通的组合
// 每条规则 return false = 拒绝该组合
const COMPATIBILITY_RULES = [
  // 1. 算子颗粒度 vs 数据源：算子需要的细粒度必须在数据源里
  // 注意：用精确字段名匹配，避免"成交量剖面"被"成交"误匹配
  (c) => {
    const { data_source: ds, microstructure_operator: op } = c;
    const needOrderbook = /OFI|盘口压力|多档.*质量|撮合速度|价差动态|集合竞价|spoofing/.test(op);
    const needTrade = /VPIN|Kyle lambda|大单冲击|主买卖/.test(op);
    const needCancel = /撤单/.test(op);
    if (needOrderbook && !/多档盘口|集合竞价数据|涨跌停板.*盘口/.test(ds)) return false;
    if (needTrade && !/逐笔成交|大单识别/.test(ds)) return false;
    if (needCancel && !/撤单流/.test(ds)) return false;
    return true;
  },
  // 2. 关系层 vs 数据源：跨合约/跨资产关系必须配对应数据
  //    弱约束关系（同板块/全市场/风险偏好）放宽——单品种数据可作为代理
  (c) => {
    const { relation: rel, data_source: ds } = c;
    const needCrossContract = /跨期|近月|远月|主力.*次主/.test(rel);
    const needCrossProduct = /上下游|替代品|内外盘|股期/.test(rel);
    if (needCrossContract && !/跨合约/.test(ds)) return false;
    if (needCrossProduct && !/跨品种/.test(ds)) return false;
    return true;
  },
  // 3. 状态 vs 数据源
  (c) => {
    const { state: st, data_source: ds } = c;
    if (/换月/.test(st) && !/跨合约/.test(ds)) return false;
    return true;
  },
  // 4. 多变量变换 vs 关系层：需要至少两个变量/序列的变换,单品种拒绝
  (c) => {
    const { transform: tf, relation: rel } = c;
    const needMultiVar = /互信息|协整|小波|信息熵|PCA|因子模型|Fama-MacBeth|DTW|马氏距离|余弦相似|转移熵|交互项/.test(tf);
    if (needMultiVar && rel === "单品种") return false;
    return true;
  },
  // 5. 微观算子 vs 时间尺度：OFI、撤单、主买卖等 tick/秒级算子，用在跨日/跨周无意义
  (c) => {
    const { microstructure_operator: op, time_scale: ts } = c;
    const isMicro = /OFI|撤单|主买卖|盘口压力|多档.*质量|撮合速度|价差动态|spoofing|集合竞价|VPIN|Kyle lambda|大单冲击/.test(op);
    if (isMicro && /跨日|跨周/.test(ts)) return false;
    return true;
  },
  // 6. 低频变换 vs 时间尺度：需要长窗口样本的变换,短尺度拒绝(卡尔曼可在线递推,不约束)
  (c) => {
    const { transform: tf, time_scale: ts } = c;
    const isLowFreq = /协整|小波|GARCH|EGARCH|HP 滤波|傅里叶|STFT|希尔伯特|PCA|因子模型|分位数回归/.test(tf);
    if (isLowFreq && /tick|秒级|1 分钟|5 分钟/.test(ts)) return false;
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

function getMetaWeights(weights, invert = false) {
  const metaW = weights.__meta__ || {};
  return META_HEURISTICS.map(m => {
    const w = typeof metaW[m.id] === "number" ? metaW[m.id] : 1.0;
    return invert ? 1 / Math.max(w, 0.1) : w;
  });
}

// 主采样函数
// mode: "weighted" | "adversarial" | "random" | "mixed"（默认）
// mixed = 70% weighted / 20% adversarial / 10% random
// 返回 n 组坐标：{ meta, dims: {data_source, microstructure_operator, time_scale, relation, transform, state} }
export function sampleCoordinates(n = 3, { mode = "mixed" } = {}) {
  const weights = loadWeights();
  const result = [];
  // 通过率约 7%（R1 算子-数据源规则最严，单独拒绝率 78%），n*30 时 P(抽不满)≈4.5%
  // n*100 把 P(抽不满) 压到 < 0.01%，且采样本身是毫秒级，不拖性能
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

    const meta = weightedPick(
      META_HEURISTICS,
      useWeight ? getMetaWeights(weights, invert) : META_HEURISTICS.map(() => 1.0)
    );

    const coords = { meta_id: meta.id };
    for (const dimName of Object.keys(DIMENSIONS)) {
      const items = DIMENSIONS[dimName];
      const w = useWeight ? getDimWeights(dimName, items, weights, invert) : items.map(() => 1.0);
      coords[dimName] = weightedPick(items, w);
    }

    if (!isCompatible(coords)) continue;

    result.push({
      meta,
      dims: {
        data_source: coords.data_source,
        microstructure_operator: coords.microstructure_operator,
        time_scale: coords.time_scale,
        relation: coords.relation,
        transform: coords.transform,
        state: coords.state,
      },
    });
  }

  return result;
}

// 坐标 → prompt 片段（旧版，保留供调试/审计用）
export function formatCoordinates(coordsList) {
  return coordsList.map((c, i) => {
    const m = c.meta;
    const d = c.dims;
    return `候选 ${i + 1}
- 元启发：${m.name} - ${m.hint}
  引导思考：${m.guide}
- 数据来源：${d.data_source}
- 微观结构算子：${d.microstructure_operator}
- 时间尺度：${d.time_scale}
- 关系层：${d.relation}
- 变换方法：${d.transform}
- 状态环境：${d.state}`;
  }).join("\n\n");
}

// 权重回写：验证后调用，实现 backprop
// score: 因子验证得分，>0 好，<0 差（建议传入归一化后的 IC 或 Sharpe）
export function updateWeights(coords, score, lr = 0.1) {
  if (!coords || !coords.meta || !coords.dims) return;
  const weights = loadWeights();
  if (!weights.__meta__) weights.__meta__ = {};

  const sign = Math.sign(score);
  const magnitude = Math.min(Math.abs(score), 2);
  const factor = 1 + lr * sign * magnitude;

  const oldMetaW = weights.__meta__[coords.meta.id] || 1.0;
  weights.__meta__[coords.meta.id] = Math.max(0.1, Math.min(5.0, oldMetaW * factor));

  for (const [dimName, value] of Object.entries(coords.dims)) {
    if (!weights[dimName]) weights[dimName] = {};
    const oldW = weights[dimName][value] || 1.0;
    weights[dimName][value] = Math.max(0.1, Math.min(5.0, oldW * factor));
  }

  saveWeights(weights);
}
