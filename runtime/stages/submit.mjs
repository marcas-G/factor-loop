// Step: submit（推送到量化平台）。
// 纯代码 runPy 一次性调用。失败处理（重试/改代码）由 run-factor.mjs 状态机决定。

import { DRY_RUN, FEATURETOOL_PY } from "../lib/config.mjs";
import { runPy, parseJsonOutput } from "../infra/run-py.mjs";
import { extractClassNameFromH, isTemplateClass } from "./write-factor.mjs";

const SUBMIT_TIMEOUT_SEC = 120;

// 合法品种代码白名单(沪金银铜铝镍, 5 品种)。
// categories 必须是这些代码之一, 不是 angle 标签(oi_anomaly/regime_gate 等)。
// 防 P0: categories 填错(填成 angle 标签)→ 拼出 SHFE-oi_anomaly 畸形 feeds → DAG failed。
export const VALID_CATEGORIES = ["AG", "AU", "CU", "AL", "NI"];

/** 校验 categories 是合法品种代码。返回 {valid, invalid, error}。 */
export function validateCategories(categories) {
  if (!Array.isArray(categories)) {
    return { valid: false, invalid: [], error: `categories 必须是数组, 得到 ${typeof categories}` };
  }
  const invalid = categories.filter((c) => !VALID_CATEGORIES.includes(c));
  if (invalid.length > 0) {
    return {
      valid: false,
      invalid,
      error: `categories 必须是品种代码 ${VALID_CATEGORIES.join("/")} 之一(如 ["AG"]), 不是 angle 标签或 tags。非法值: ${invalid.join(", ")}`,
    };
  }
  return { valid: true, invalid: [] };
}

// categories: ["CU","AL","NI"] → "SHFE-CU,SHFE-CU@1,SHFE-AL,SHFE-AL@1,..."
// 不传或为空 → 返回 null（让 featuretool 用默认 SHFE-AG,SHFE-AG@1,SHFE-CU,SHFE-CU@1）
// 调用前必须先 validateCategories(防畸形 feeds)。
function categoriesToFeeds(categories) {
  if (!Array.isArray(categories) || categories.length === 0) return null;
  return categories.flatMap((c) => [`SHFE-${c}`, `SHFE-${c}@1`]).join(",");
}

export async function submitFactorProgrammatic(factor, factorFile) {
  if (DRY_RUN) {
    return { ok: true, features: factor.name, raw: "[DRY-RUN] submit skipped", dry: true, attempts: 1 };
  }

  // P0 防御: categories 必须是合法品种代码(AG/AU/CU/AL/NI), 不是 angle 标签。
  // 拦在这里, 避免拼出 SHFE-oi_anomaly 畸形 feeds 发到平台导致 DAG failed。
  const catCheck = validateCategories(factor.categories || []);
  if (!catCheck.valid) {
    return {
      ok: false,
      features: factor.name,
      error: `[categories 语义错误] ${catCheck.error}`,
      raw: `非法 categories: ${JSON.stringify(factor.categories)}`,
      attempts: 1,
      failure_layer: "config_error",
    };
  }

  const className = extractClassNameFromH(factorFile) || factor.name;
  const features = isTemplateClass(factorFile) ? `${className}<>` : className;
  const feeds = categoriesToFeeds(factor.categories);

  console.log(`  [submit] ${factor.name} features=${features}${feeds ? ` feeds=${feeds}` : ""}`);

  // adapt/default-test: 新平台删 GenerateXs(ComputeCsvIc 在 featuretool.py 内默认 on)
  const args = ["submit", "--file", factorFile, "--features", features, "--json"];
  if (feeds) args.push("--feeds", feeds);

  const result = await runPy(FEATURETOOL_PY, args, { timeoutSec: SUBMIT_TIMEOUT_SEC });

  if (result.timedOut) {
    return { ok: false, features, error: `submit 超时 (${result.durationMs}ms)`, raw: result.stdout, attempts: 1 };
  }
  const parsed = parseJsonOutput(result.stdout);
  if (!parsed) {
    return { ok: false, features, error: `submit 输出非 JSON: ${(result.stdout || result.stderr).slice(0, 200)}`, raw: result.stdout, attempts: 1 };
  }
  if (parsed.ok === true && result.exitCode === 0) {
    return { ok: true, features: parsed.features || features, raw: JSON.stringify(parsed), attempts: 1 };
  }
  return { ok: false, features: parsed.features || features, error: parsed.error || `exit=${result.exitCode}`, raw: JSON.stringify(parsed), attempts: 1 };
}
