// 组 1: factor-db 查询工具（6 个）。直接复用 factor-db.mjs 的函数。
// 服务启动时调 factorDb.init()。

import * as factorDb from "../../lib/factor-db.mjs";

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

// ===== 迭代管道:evaluate 开建议 → brainstorm 检索接续 → realize 归档 → research-loop 失败 reopen =====
export const openIterationSchema = {
  name: "iteration_open",
  description:
    "evaluate 阶段开一个迭代建议(open suggestion):把当前因子的 suggested_iteration(换 horizon/品种/窗口)登记成待接续建议。pass 精进 / dead_end 显式重试用这个;dead_end 无救方向不用这个(改走 dead_end lesson 避雷)。同 (from,change) 已 open 则幂等返回已有 id。",
  inputSchema: {
    type: "object",
    properties: {
      from_xname: { type: "string", description: "源因子 xname(当前 evaluate 的因子)" },
      change_note: { type: "string", description: "建议的改动(如 '换 60s horizon' / '换品种 CU')" },
      reason: { type: "string", description: "为什么这么改(基于 7 维数据的依据)" },
      iterable: { type: "boolean", default: true, description: "是否值得接续(pass/有重试价值=true,无救=false)" },
      idea_id: { type: "number" },
    },
    required: ["from_xname", "change_note"],
  },
};
export async function openIterationHandler({ from_xname, change_note, reason, iterable = true, idea_id }) {
  return {
    suggestion_id: factorDb.openIteration(from_xname, { changeNote: change_note, reason, iterable, ideaId: idea_id }),
  };
}

export const realizeIterationSchema = {
  name: "iteration_realize",
  description:
    "接续因子 B 的 evaluate 阶段归档(在 persist_factor 之后调用,B 已入库):建议 in_progress→realized,填 to_xname=B、icir_delta。outcome 由 icir_delta 自动推导(improved/declined/neutral)。演进链 from→to 就此落定。",
  inputSchema: {
    type: "object",
    properties: {
      suggestion_id: { type: "number", description: "iteration_open 返回的 id(从 state.factors[i].suggestion_id 取)" },
      to_xname: { type: "string", description: "接续因子 B 的 xname(当前 evaluate 的因子)" },
      icir_delta: { type: "number", description: "B.latest_icir - A.latest_icir(正=提升)" },
    },
    required: ["suggestion_id", "to_xname"],
  },
};
export async function realizeIterationHandler({ suggestion_id, to_xname, icir_delta }) {
  return factorDb.realizeIteration(suggestion_id, to_xname, { icirDelta: icir_delta });
}

export const reopenIterationSchema = {
  name: "iteration_reopen",
  description:
    "失败回滚(research-loop 兜底用):接续候选 B 最终 status=failed 时,建议 in_progress→open,允许下次再接续。只在 in_progress 状态有效。",
  inputSchema: {
    type: "object",
    properties: { suggestion_id: { type: "number" } },
    required: ["suggestion_id"],
  },
};
export async function reopenIterationHandler({ suggestion_id }) {
  return factorDb.reopenIteration(suggestion_id);
}

export const listOpenIterationsSchema = {
  name: "iteration_list_open",
  description:
    "brainstorm 检索待接续的迭代建议(open suggestions),按 priority 降序。priority=(evaluated?2.0:0.5) × max(icir,0.1) × exp(-age/14)——pass 精进优先、强因子优先、老建议降权。接续高 priority 建选作为本轮候选之一。",
  inputSchema: {
    type: "object",
    properties: {
      top_k: { type: "number", default: 5 },
      source_status: { type: "string", enum: ["evaluated", "dead_end"], description: "可选,只看某类源因子的建议" },
    },
  },
};
export async function listOpenIterationsHandler({ top_k = 5, source_status }) {
  return factorDb.listOpenIterations({ topK: top_k, sourceStatus: source_status });
}

export const coverageMapSchema = {
  name: "coverage_map",
  description:
    "覆盖地图:按 symbol×y_horizon×status×necessity_grade 聚合已搜空间,每格标 gap_tags(thin/hot/stale/normal)。"
    + "看哪片欠探索(thin)/高效热点(hot)/该复验(stale)。覆盖空白源、brainstorm 选方向参考。"
    + "口径:只统计跑过 ic_refresh 的因子。",
  inputSchema: {
    type: "object",
    properties: {
      slice: { type: "object", description: "可选过滤 {symbol?, y_horizon?, status?, necessity_grade?}" },
      group_by: {
        type: "array",
        items: { type: "string", enum: ["symbol", "y_horizon", "status", "necessity_grade"] },
        description: "聚合轴子集,默认全 4 轴",
      },
      min_count: { type: "number", default: 0, description: "只看 searched_count≥此值的格子" },
    },
  },
};
export async function coverageMapHandler({ slice, group_by, min_count }) {
  return factorDb.coverageMap({ slice, groupBy: group_by, minCount: min_count });
}

export const coverageGapsSchema = {
  name: "coverage_gaps",
  description:
    "覆盖空白/热点队列:unexplored(品种×频率×假设硬度 从无 evaluated)→ thin → hot → stale 各取 top_k。"
    + "覆盖空白/热点队列(补 failed/open/dead_end 都是'已试边界'的盲区,这个是'从没试过的空白')。",
  inputSchema: {
    type: "object",
    properties: { top_k: { type: "number", default: 5 } },
  },
};
export async function coverageGapsHandler({ top_k }) {
  return factorDb.coverageGaps({ topK: top_k });
}

export const residualIcStrengthSchema = {
  name: "factor_residual_ic_strength",
  description:
    "残差 IC 强度:新因子日级 IC 序列在库内基底 IC 张成空间的残差比例(预测能力不被已有因子线性解释的程度)。"
    + "高=真新颖,低=冗余。补 factor_ic_correlate(pairwise 查'和某个最像')——这个给'相对全库基底的新颖性标量'。"
    + "evaluate 第三维正交增强。依赖 factor_ic_daily(refresh 入库);库空/无基底 → strength=1.0。",
  inputSchema: {
    type: "object",
    required: ["target"],
    properties: {
      target: { type: "string", description: "目标因子 xname" },
      symbol: { type: "string", description: "可选,限定场景" },
      freq: { type: "string", description: "可选,限定场景" },
      y_horizon: { type: "number", description: "可选,限定场景" },
      ridge: { type: "number", default: 0.001, description: "岭回归正则(防基底共线);IC 幅度小默认 1e-3" },
      max_base: { type: "number", default: 30, description: "基底因子数上限(按 |pearson| 选最能解释 target 的代表)" },
    },
  },
};
export async function residualIcStrengthHandler({ target, symbol, freq, y_horizon, ridge, max_base }) {
  return factorDb.residualIcStrength(target, {
    symbol, freq, yHorizon: y_horizon, ridge, maxBase: max_base,
  });
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
  openIterationSchema,
  realizeIterationSchema,
  reopenIterationSchema,
  listOpenIterationsSchema,
  coverageMapSchema,
  coverageGapsSchema,
  residualIcStrengthSchema,
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
  iteration_open: openIterationHandler,
  iteration_realize: realizeIterationHandler,
  iteration_reopen: reopenIterationHandler,
  iteration_list_open: listOpenIterationsHandler,
  coverage_map: coverageMapHandler,
  coverage_gaps: coverageGapsHandler,
  factor_residual_ic_strength: residualIcStrengthHandler,
};
