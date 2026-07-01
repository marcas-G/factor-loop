// 组 3: 平台调用工具（submit/check）。生产模式调真实 python；测试用 QUANT_MCP_MOCK_PLATFORM=1 mock。

import { submitFactorProgrammatic } from "../../stages/submit.mjs";
import { checkFactorProgrammatic } from "../../stages/check.mjs";
import { runSave, runLoad } from "../lib/run-store.mjs";

export const submitFactorSchema = {
  name: "submit_factor",
  description: "把因子推送到量化平台（调 featuretool.py submit）。返回 {ok, features, error}。",
  inputSchema: {
    type: "object",
    properties: {
      xname: { type: "string", description: "因子类名" },
      factorFile: { type: "string", description: ".h 文件绝对路径" },
      categories: { type: "array", items: { type: "string" } },
      params: { type: "object" },
    },
    required: ["xname", "factorFile"],
  },
};
export async function submitFactorHandler({ xname, factorFile, categories = [], params = {} }) {
  if (process.env.QUANT_MCP_MOCK_PLATFORM === "1") {
    return { ok: true, features: xname, raw: "[MOCK] submit skipped", attempts: 1 };
  }
  const factor = { name: xname, categories, params };
  return submitFactorProgrammatic(factor, factorFile);
}

export const checkFactorSchema = {
  name: "check_factor",
  description:
    "检查因子评估结果（调 factor_check.py run + 抓 evidence + 诊断）。工具内部直接把完整 evidence + failure_layer 落到 state（不经 agent 手，避免 LLM 二次加工丢字段）。返回给调用方的只有路由信息 {failureLayer, summary}，不含 evidence。",
  inputSchema: {
    type: "object",
    properties: {
      xname: { type: "string" },
      submitRef: { type: "object", description: "submit_factor 的返回值 {ok, features}" },
      checkOutput: { type: "string", description: "check 输出目录绝对路径" },
      run_id: { type: "string", description: "研究 run id（用于内部 run_save evidence）" },
      factor_index: { type: "integer", description: "state.factors 下标（用于内部 run_save）" },
    },
    required: ["xname", "submitRef", "checkOutput", "run_id", "factor_index"],
  },
};
export async function checkFactorHandler({ xname, submitRef, checkOutput, run_id, factor_index }) {
  let result;
  if (process.env.QUANT_MCP_MOCK_PLATFORM === "1") {
    result = {
      ok: true,
      failureLayer: "check_done",
      checkOutput,
      dailyIcPath: `${checkOutput}/mock_daily_ic.txt`,
      dailyIcSize: 4096,
      summary: `[MOCK] ${xname} 检查通过`,
      evidence: {
        reason: "mock",
        seven_dim_summary: {
          factor_level: { n_pairs: 10, keep: 5, watch: 3, reject: 2, best_score: 0.85, best_pair: "X1-Y1" },
          seven_dim_best: { screening: { ic_mean: 0.038, icir: 2.1 } },
          deep_best: { conditional_sharpe: 1.8, monthly_icir: 2.5, rank_ic_max: 0.05 },
          failure_reasons: {},
        },
      },
    };
  } else {
    let factor = { name: xname };
    if (run_id && factor_index != null) {
      try {
        const state = await runLoad(run_id);
        factor = state?.factors?.[factor_index] || factor;
      } catch { /* runLoad 失败则回退用 xname */ }
    }
    result = await checkFactorProgrammatic(factor, submitRef, checkOutput);
  }

  // 关键：完整 evidence 原样落 state，不经 agent 手——避免 LLM 二次加工导致 stdout_tail 丢失/字段被改
  if (run_id && factor_index != null) {
    await runSave(run_id, {
      [`factors.${factor_index}.failure_layer`]: result.failureLayer,
      [`factors.${factor_index}.evidence`]: result.evidence,
    });
  }

  // 返回给 agent 的只有路由信息（不含 evidence）
  return { failureLayer: result.failureLayer, summary: result.summary };
}

export const ALL_PLATFORM_SCHEMAS = [submitFactorSchema, checkFactorSchema];
export const ALL_PLATFORM_HANDLERS = {
  submit_factor: submitFactorHandler,
  check_factor: checkFactorHandler,
};
