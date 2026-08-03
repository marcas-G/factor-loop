// 组 5: 写库工具（2 个）。复用 stages/persist.mjs 的 persistVerdict 函数。

import * as factorDb from "../../lib/factor-db.mjs";
import { persistVerdict } from "../../stages/persist.mjs";
import { runLoad, runApply } from "../lib/run-store.mjs";

export const persistIdeaSchema = {
  name: "persist_idea",
  description: "把一条研究 idea 写入 ideas 表。",
  inputSchema: {
    type: "object",
    properties: { text: { type: "string" } },
    required: ["text"],
  },
};
export async function persistIdeaHandler({ text }) {
  const id = factorDb.addIdea(text);
  return { id };
}

// persist_factor: evaluate 阶段 verdict 落库。
// 工具内部从 state 读 factor/factorFile/checkResult，Claude 只需传 (run_id, factor_index, verdict)。
// verdict=pass → factors+evals+success_pattern lesson；verdict=fail → factors(dead_end)+dead_end lesson。
// 仅对 failureLayer=check_done 有效，其它返回 {ok: false, error}。
export const persistFactorSchema = {
  name: "persist_factor",
  description:
    "因子入库。mode=prepare: 只入 factors 表占位(status=draft, 解锁 assess 路径B ingest 的 FK, 不写 eval/lesson/不定 verdict); mode=commit(默认): 按 verdict 写 eval/lesson/定 status。工具内部从 state.json 读 factor/factorFile/checkResult/retryInfo/ideaId。",
  inputSchema: {
    type: "object",
    properties: {
      run_id: { type: "string", description: "研究 run id" },
      factor_index: { type: "integer", description: "state.factors 数组下标（从 0 开始）" },
      mode: { type: "string", enum: ["prepare", "commit"], description: "prepare=入表占位不定verdict; commit=按verdict落库(默认)" },
      verdict: {
        type: "object",
        description: "commit 模式必填: verdict 对象 {verdict:'pass'|'fail', key_strengths, key_weaknesses, suggested_iteration}。prepare 模式省略",
      },
    },
    required: ["run_id", "factor_index"],
  },
};
export async function persistFactorHandler({ run_id, factor_index, verdict, mode = "commit" }) {
  const state = await runLoad(run_id);
  if (factor_index < 0 || factor_index >= state.factors.length) {
    return { ok: false, error: `factor_index 越界: ${factor_index} (factors.length=${state.factors.length})` };
  }
  const f = state.factors[factor_index];
  if (f.failure_layer !== "check_done") {
    return { ok: false, error: `factor[${factor_index}] failure_layer=${f.failure_layer} 非 check_done，不入库` };
  }
  if (!f.factor_file) {
    return { ok: false, error: `factor[${factor_index}].factor_file 为空（run-factor-agent 未写入）` };
  }

  const factor = {
    name: f.name,
    formula: f.formula,
    hypothesis: f.hypothesis,
    intuition: f.intuition || null,
    categories: f.categories || [],
    tags: f.tags || [],
  };
  const checkResult = {
    failureLayer: f.failure_layer,
    features: f.name,
    evidence: f.evidence || {},
    checkOutput: null,
  };
  const retryInfo = f.last_rewrite || null;
  const ideaId = state.idea_id ?? null;

  return persistVerdict(factor, f.factor_file, checkResult, retryInfo, verdict, ideaId, mode);
}

// persist_candidates: brainstorm 一次性持久化 idea + N 候选。
// 替代"逐候选 run_save 4-5 次"——那种模式 LLM 输出大 JSON 后多次调用易停止 + 点路径覆盖丢 schema。
// 本工具内部: addIdea → map 候选补全 schema(status/factor_file/...) + 保留 intuition/db_research 等 → run_save 整体写。
// LLM 只调一次。
export const persistCandidatesSchema = {
  name: "persist_candidates",
  description:
    "brainstorm 一次性持久化：存 idea + 完整候选 factors。把 brainstorm 输出的候选 JSON 整体传入，工具内部 persist_idea + run_save factors(补全 status/factor_file 等 schema 字段，保留 intuition/diff_check/coord_usage/params/db_research)。只调一次，替代逐候选 run_save。",
  inputSchema: {
    type: "object",
    properties: {
      run_id: { type: "string", description: "研究 run id" },
      idea_text: { type: "string", description: "研究 idea 文本" },
      factors: {
        type: "array",
        description: "候选因子数组，每项含 name/formula/intuition/diff_check/coord_usage/categories/params/db_research",
      },
    },
    required: ["run_id", "idea_text", "factors"],
  },
};
export async function persistCandidatesHandler({ run_id, idea_text, factors }) {
  const ideaId = factorDb.addIdea(idea_text);
  const fullFactors = (factors || []).map((f) => ({
    name: f.name,
    formula: f.formula || null,
    hypothesis: f.hypothesis || [f.intuition, f.diff_check, f.coord_usage].filter(Boolean).join("\n\n") || null,
    categories: f.categories || [],
    tags: f.tags || [],
    coordinates: f.coordinates || null,
    intuition: f.intuition || null,
    diff_check: f.diff_check || null,
    coord_usage: f.coord_usage || null,
    params: f.params || {},
    db_research: f.db_research || null,
    // 迭代接续: brainstorm 接续 open suggestion 时带上(供 persist claim + evaluate realize)
    suggestion_id: f.suggestion_id ?? null,
    iterates_from: f.iterates_from ?? null,
    // schema 必需字段（runInit 同款，避免后续 run-factor-agent 读 undefined）
    factor_file: null,
    status: "pending",
    failure_layer: null,
    retry_trace: [],
    evidence: null,
    verdict: null,
    persisted: null,
  }));
  // 迭代接续: 候选带 suggestion_id 时 claim(open→in_progress)。claim 不阻塞——失败(被别人先 claim/已 realized)只记录。
  const claimed = [];
  for (const f of fullFactors) {
    if (f.suggestion_id != null) {
      try {
        const r = factorDb.claimIteration(f.suggestion_id);
        claimed.push({ suggestion_id: f.suggestion_id, iterates_from: f.iterates_from, ...r });
      } catch (e) {
        claimed.push({ suggestion_id: f.suggestion_id, error: e.message });
      }
    }
  }
  // 用 runApply 整体写 idea/idea_id/factors：runSave 的防御会拒绝顶级 factors 数组覆盖
  // （brainstorm 是"初始化式"写入，factors 从无到有，需绕过该防御）。仍走串行链避免并发冲突。
  await runApply(run_id, (state) => {
    state.idea = idea_text;
    state.idea_id = ideaId;
    state.factors = fullFactors;
  });
  return { idea_id: ideaId, n_factors: fullFactors.length, claimed };
}

export const ALL_PERSIST_SCHEMAS = [persistIdeaSchema, persistFactorSchema, persistCandidatesSchema];
export const ALL_PERSIST_HANDLERS = {
  persist_idea: persistIdeaHandler,
  persist_factor: persistFactorHandler,
  persist_candidates: persistCandidatesHandler,
};
