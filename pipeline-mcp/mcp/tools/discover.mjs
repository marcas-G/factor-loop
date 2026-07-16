// 组 7: 扫库源的 top-down 扫库工具(纯读 factors.db)。
// discover_failed_hypotheses: 失效假设(support_score 低 + 已验证过)
// discover_recent_dead_ends: 最近 dead_end(方向失效信号)
// open_iterations 复用现有 iteration_list_open(iterations 模块),不在此重复。
//
// 这两个 + iteration_list_open 是 top-down 扫库源(理论驱动)。

import * as factorDb from "../../lib/factor-db.mjs";

export const discoverFailedHypothesesSchema = {
  name: "discover_failed_hypotheses",
  description:
    "扫库源 top-down 源:扫失效假设(support_score 低 + 已有因子验证过)。这些'为什么假设错了'是下一轮反常的原料(失效回喂)。返回按 support_score 升序。",
  inputSchema: {
    type: "object",
    properties: {
      max_score: { type: "number", description: "support_score 上限阈值,默认 0.4", default: 0.4 },
      min_evaluated: { type: "integer", description: "最少已评估因子数,默认 2(避免少样本)", default: 2 },
      limit: { type: "integer", default: 10 },
    },
  },
};
export async function discoverFailedHypothesesHandler({ max_score, min_evaluated, limit }) {
  const failed = factorDb.discoverFailedHypotheses({
    maxScore: max_score ?? 0.4,
    minEvaluated: min_evaluated ?? 2,
    limit: limit ?? 10,
  });
  return { count: failed.length, failed };
}

export const discoverRecentDeadEndsSchema = {
  name: "discover_recent_dead_ends",
  description:
    "扫库源 top-down 源:最近 dead_end lessons(方向失效信号)。用于避雷 + 失效回喂(失效方向暴露的矛盾是反常)。",
  inputSchema: {
    type: "object",
    properties: { limit: { type: "integer", default: 10 } },
  },
};
export async function discoverRecentDeadEndsHandler({ limit }) {
  const deadEnds = factorDb.discoverRecentDeadEnds({ limit: limit ?? 10 });
  return { count: deadEnds.length, dead_ends: deadEnds };
}

export const ALL_DISCOVER_SCHEMAS = [discoverFailedHypothesesSchema, discoverRecentDeadEndsSchema];
export const ALL_DISCOVER_HANDLERS = {
  discover_failed_hypotheses: discoverFailedHypothesesHandler,
  discover_recent_dead_ends: discoverRecentDeadEndsHandler,
};
