// 组 1: factor-db 查询工具（6 个）。直接复用 factor-db.mjs 的函数。
// 服务启动时调 factorDb.init()。

import * as factorDb from "../../factor-db.mjs";

export const factorSearchSchema = {
  name: "factor_search",
  description: "全文检索 lessons（trigram 分词，中文/英文混合 OK）。返回 type/scope/text 等字段。用于找历史经验。",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "检索词（≥3 字）" },
      k: { type: "number", description: "返回条数，默认 5", default: 5 },
    },
    required: ["query"],
  },
};
export async function factorSearchHandler({ query, k = 5 }) {
  return factorDb.searchLessons(query, k);
}

export const factorRecentLessonsSchema = {
  name: "factor_recent_lessons",
  description: "最近 k 条 lesson（按时间倒序），看最近经验积累。",
  inputSchema: {
    type: "object",
    properties: { k: { type: "number", default: 10 } },
  },
};
export async function factorRecentLessonsHandler({ k = 10 }) {
  return factorDb.recentLessons(k);
}

export const factorListSchema = {
  name: "factor_list",
  description: "列最近 k 个因子（含 status / latest_icir / formula_text），看最近研究方向。",
  inputSchema: {
    type: "object",
    properties: { k: { type: "number", default: 20 } },
  },
};
export async function factorListHandler({ k = 20 }) {
  return factorDb.recentFactors(k);
}

export const factorDetailSchema = {
  name: "factor_detail",
  description: "单因子全貌：基本信息 + 评估历史 + 迭代链 + tags。看一个因子的完整演进。",
  inputSchema: {
    type: "object",
    properties: { xname: { type: "string" } },
    required: ["xname"],
  },
};
export async function factorDetailHandler({ xname }) {
  return factorDb.getFactorDetail(xname);
}

export const factorSimilarSchema = {
  name: "factor_similar",
  description: "向量查重：给定 xname，找库内最相似的 k 个因子（基于 formula 语义 embedding）。",
  inputSchema: {
    type: "object",
    properties: {
      xname: { type: "string" },
      k: { type: "number", default: 10 },
    },
    required: ["xname"],
  },
};
export async function factorSimilarHandler({ xname, k = 10 }) {
  return factorDb.getSimilarFactors(xname, k);
}

export const factorSemanticSearchSchema = {
  name: "factor_semantic_search",
  description:
    "语义检索：给定任意文本（idea / 公式 / 自然语言），用 bge-small-zh-v1.5 算 embedding，向量检索库内最相似的 k 个因子。brainstorm 阶段查相似/查重方向用这个，不要再用 factor_search 抽关键词。",
  inputSchema: {
    type: "object",
    properties: {
      query_text: { type: "string", description: "查询文本（idea 全文 / formula 片段 / 任意描述）" },
      k: { type: "number", default: 10 },
    },
    required: ["query_text"],
  },
};
export async function factorSemanticSearchHandler({ query_text, k = 10 }) {
  return factorDb.semanticSearchFactors(query_text, k);
}

export const factorCountsSchema = {
  name: "factor_counts",
  description: "库规模摸底：返回 {factors, lessons, evaluated} 三个总数。",
  inputSchema: { type: "object", properties: {} },
};
export async function factorCountsHandler() {
  return {
    factors: factorDb.countFactors(),
    lessons: factorDb.countLessons(),
    evaluated: factorDb.countEvaluated(),
  };
}

export const factorIcCorrelateSchema = {
  name: "factor_ic_correlate",
  description:
    "IC 行为冗余检索：找和 target 因子 IC 序列相似的库内因子（预测能力同涨同跌=真冗余，比 formula 文本语义更贴近业务）。需 target 已有 IC 向量（先 factor_ic_refresh）。只给 target 时遍历其所有 (symbol,freq,y_horizon) 场景并按 |pearson| 聚合。",
  inputSchema: {
    type: "object",
    required: ["target"],
    properties: {
      target: { type: "string", description: "目标因子 xname" },
      symbol: { type: "string", description: "可选，限定 symbol" },
      freq: { type: "string", description: "可选，限定 freq" },
      y_horizon: { type: "number", description: "可选，限定 y_horizon" },
      k: { type: "number", description: "ANN 粗筛数/场景，默认 20", default: 20 },
      min_abs_pearson: { type: "number", description: "冗余阈值 |pearson|，默认 0.5", default: 0.5 },
    },
  },
};
export async function factorIcCorrelateHandler({ target, symbol, freq, y_horizon, k, min_abs_pearson }) {
  return factorDb.icCorrelateFactors(target, {
    symbol, freq, yHorizon: y_horizon, k, minAbsPearson: min_abs_pearson,
  });
}

export const factorIcRefreshSchema = {
  name: "factor_ic_refresh",
  description:
    "刷新单因子 IC 向量（下载 dailyX + 算 IC 序列向量写入 factor_ic_vec）。evaluate 在 check_done 后调用，使新因子可被 factor_ic_correlate 检索。失败返回 ok:false，调用方应降级跳过冗余检查、不阻塞主 verdict。",
  inputSchema: {
    type: "object",
    required: ["xname"],
    properties: {
      xname: { type: "string", description: "因子 xname" },
      force: { type: "boolean", description: "已有也重算，默认 false", default: false },
    },
  },
};
export async function factorIcRefreshHandler({ xname, force = false }) {
  return factorDb.icRefreshFactor(xname, force);
}

export const ALL_FACTOR_DB_SCHEMAS = [
  factorSearchSchema,
  factorRecentLessonsSchema,
  factorListSchema,
  factorDetailSchema,
  factorSimilarSchema,
  factorSemanticSearchSchema,
  factorCountsSchema,
  factorIcCorrelateSchema,
  factorIcRefreshSchema,
];

export const ALL_FACTOR_DB_HANDLERS = {
  factor_search: factorSearchHandler,
  factor_recent_lessons: factorRecentLessonsHandler,
  factor_list: factorListHandler,
  factor_detail: factorDetailHandler,
  factor_similar: factorSimilarHandler,
  factor_semantic_search: factorSemanticSearchHandler,
  factor_counts: factorCountsHandler,
  factor_ic_correlate: factorIcCorrelateHandler,
  factor_ic_refresh: factorIcRefreshHandler,
};
