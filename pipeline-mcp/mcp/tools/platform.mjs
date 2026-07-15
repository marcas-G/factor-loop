// 组 3: 平台调用工具（submit/check）。生产模式调真实 python；测试用 QUANT_MCP_MOCK_PLATFORM=1 mock。

import fs from "node:fs";
import path from "node:path";

import { submitFactorProgrammatic } from "../../stages/submit.mjs";
import { checkFactorProgrammatic } from "../../stages/check.mjs";
import { renameFactorH } from "../../stages/rename-factor.mjs";
import { isAllZeroFromScreening } from "../../lib/metrics.mjs";
import { runSave, runLoad } from "../lib/run-store.mjs";
import * as factorDb from "../../lib/factor-db.mjs";

export const submitFactorSchema = {
  name: "platform_submit_factor",
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
  name: "platform_check_factor",
  description:
    "检查因子评估结果（调 factor_check.py run + 抓 evidence + 诊断）。工具内部直接把完整 evidence + failure_layer 落到 state（不经 agent 手，避免 LLM 二次加工丢字段）。返回给调用方的只有路由信息 {failureLayer, summary}，不含 evidence。check_output_missing + 因子值全零时自动换名重试一次（DAG 缓存陷阱自愈）。",
  inputSchema: {
    type: "object",
    properties: {
      xname: { type: "string" },
      submitRef: { type: "object", description: "platform_submit_factor 的返回值 {ok, features}" },
      checkOutput: { type: "string", description: "check 输出目录绝对路径" },
      run_id: { type: "string", description: "研究 run id（用于内部 run_save evidence）" },
      factor_index: { type: "integer", description: "state.factors 下标（用于内部 run_save）" },
    },
    required: ["xname", "submitRef", "checkOutput", "run_id", "factor_index"],
  },
};
export async function checkFactorHandler({ xname, submitRef, checkOutput, run_id, factor_index }) {
  const isMock = process.env.QUANT_MCP_MOCK_PLATFORM === "1";
  let result;
  let factor = { name: xname };

  // 统一 load state（MOCK + 真实都需要 factor.factor_file 做 featureKey + 换名重试）
  if (run_id && factor_index != null) {
    try {
      const state = await runLoad(run_id);
      factor = state?.factors?.[factor_index] || factor;
    } catch { /* runLoad 失败回退用 xname */ }
  }

  // submit/check 通道：MOCK 用 mock fn，真实用 programmatic。retryWithRename 复用同一通道。
  let submitFn, checkFn;

  if (isMock) {
    submitFn = (f /*, fFile */) => ({ ok: true, features: f.name, raw: "[MOCK] submit skipped", attempts: 1 });
    checkFn = (f, _s, co) => _mockCheckResult(f.name, co, { done: true });
    // 首次 result：MOCK_ZERO_FIRST 模拟 check_output_missing + 全零 screening.csv（测 DAG 缓存陷阱自愈）
    if (process.env.QUANT_MCP_MOCK_ZERO_FIRST === "1") {
      const featureKey = factor.factor_file ? path.basename(factor.factor_file, ".h") : xname;
      _writeMockZeroScreening(checkOutput, featureKey);
      result = _mockCheckResult(xname, checkOutput, { done: false });
    } else {
      result = _mockCheckResult(xname, checkOutput, { done: true });
    }
  } else {
    submitFn = submitFactorProgrammatic;
    checkFn = checkFactorProgrammatic;
    result = await checkFn(factor, submitRef, checkOutput);
  }

  // —— DAG 缓存陷阱自愈：check_output_missing + 因子值全零 → 自动换名重试一次 ——
  // 同 xname/features 签名重提交不触发平台 DAG 重算（缓存命中）→ 换 xname 强制重跑。
  if (result.failureLayer === "check_output_missing" && factor.factor_file) {
    const featureKey = path.basename(factor.factor_file, ".h");
    if (isAllZeroFromScreening(checkOutput, featureKey)) {
      const retried = await retryWithRename({ xname, factor, checkOutput, submitFn, checkFn });
      if (retried) result = retried.result;
      // retried 为 null → 重试无效（仍全零/missing），保留原 result 让 agent 走 quality rewrite
    }
  }

  // 关键：完整 evidence 原样落 state，不经 agent 手——避免 LLM 二次加工导致 stdout_tail 丢失/字段被改
  if (run_id && factor_index != null) {
    const patch = {
      [`factors.${factor_index}.failure_layer`]: result.failureLayer,
      [`factors.${factor_index}.evidence`]: result.evidence,
    };
    // 换名成功 → 更新 name/xname/factor_file + retry_trace 追加 dag_cache_rename 记录
    if (result._renameInfo) {
      const ri = result._renameInfo;
      const prevTrace = Array.isArray(factor.retry_trace) ? factor.retry_trace : [];
      patch[`factors.${factor_index}.name`] = ri.newXname;
      patch[`factors.${factor_index}.xname`] = ri.newXname;
      patch[`factors.${factor_index}.factor_file`] = ri.newFile;
      patch[`factors.${factor_index}.retry_trace`] = [...prevTrace, {
        attempt: prevTrace.length + 1,
        failure_layer: "check_output_missing",
        fix: "dag_cache_rename",
        summary: `全零 check_output_missing 疑似 DAG 缓存命中 → 换名 ${ri.oldXname}→${ri.newXname} 强制重跑`,
      }];
    }
    await runSave(run_id, patch);
  }

  // 返回给 agent 的只有路由信息（不含 evidence / _renameInfo）
  return { failureLayer: result.failureLayer, summary: result.summary };
}

// DAG 缓存陷阱自愈：换名 + 重 submit + 重 check。
// 成功（新结果非 check_output_missing）返回 { result }（result._renameInfo 含 old/new/newFile），否则 null。
// submitFn/checkFn 由调用方注入（真实=programmatic，MOCK=mock fn），便于测试。
export async function retryWithRename({ xname, factor, checkOutput, submitFn, checkFn }) {
  const factorsDir = path.dirname(factor.factor_file);
  const existsInDb = (x) => { try { return factorDb.factorExists(x); } catch { return false; } };

  let rename;
  try {
    rename = renameFactorH(xname, factor.factor_file, factorsDir, existsInDb);
  } catch (e) {
    console.error(`  [check] 换名失败(${xname}): ${e.message}`);
    return null;
  }
  console.log(`  [check] DAG 缓存陷阱自愈: ${xname} → ${rename.newXname}（全零 check_output_missing）`);

  const newSubmit = await submitFn(
    { name: rename.newXname, categories: factor.categories || [], params: factor.params || {} },
    rename.newFile
  );
  if (!newSubmit || !newSubmit.ok) {
    console.error(`  [check] 换名后 submit 失败: ${newSubmit?.error || "未知"}`);
    return null;
  }

  const newCheckOutput = path.join(path.dirname(checkOutput), `${rename.newXname}_check`);
  const newResult = await checkFn(
    { name: rename.newXname, factor_file: rename.newFile },
    newSubmit,
    newCheckOutput
  );
  // 仍 check_output_missing → 重试无效（真代码问题，如 feed().trade() 恒0），不自愈
  if (newResult.failureLayer === "check_output_missing") {
    console.log(`  [check] 换名 ${rename.newXname} 后仍 check_output_missing → 真代码问题，不自愈`);
    return null;
  }
  newResult._renameInfo = { oldXname: xname, newXname: rename.newXname, newFile: rename.newFile };
  return { result: newResult };
}

// —— MOCK 平台辅助（测试用，QUANT_MCP_MOCK_PLATFORM=1 时启用）——
function _mockCheckResult(xname, checkOutput, { done = true } = {}) {
  if (done) {
    return {
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
  }
  return {
    ok: false,
    failureLayer: "check_output_missing",
    checkOutput,
    dailyIcSize: 0,
    summary: `[MOCK] ${xname} daily_ic 缺失`,
    evidence: { reason: "check_output_missing", daily_ic_size: 0 },
  };
}

function _writeMockZeroScreening(checkOutput, featureKey) {
  const dir = path.join(checkOutput, featureKey, "dailyX", `${featureKey}_feval`);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "screening.csv"), "zero_ratio\n1.0\n");
}

export const ALL_PLATFORM_SCHEMAS = [submitFactorSchema, checkFactorSchema];
export const ALL_PLATFORM_HANDLERS = {
  platform_submit_factor: submitFactorHandler,
  platform_check_factor: checkFactorHandler,
};
