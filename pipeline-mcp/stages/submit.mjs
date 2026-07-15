// Step: submit（推送到量化平台）。
// 纯代码 runPy 一次性调用。失败处理（重试/改代码）由 run-factor.mjs 状态机决定。

import { DRY_RUN, FEATURETOOL_PY } from "../lib/config.mjs";
import { runPy, parseJsonOutput } from "../infra/run-py.mjs";
import { extractClassNameFromH, isTemplateClass } from "./write-factor.mjs";

const SUBMIT_TIMEOUT_SEC = 120;

// categories: ["CU","AL","NI"] → "SHFE-CU,SHFE-CU@1,SHFE-AL,SHFE-AL@1,..."
// 不传或为空 → 返回 null（让 featuretool 用默认 SHFE-AG,SHFE-AG@1,SHFE-CU,SHFE-CU@1）
function categoriesToFeeds(categories) {
  if (!Array.isArray(categories) || categories.length === 0) return null;
  return categories.flatMap((c) => [`SHFE-${c}`, `SHFE-${c}@1`]).join(",");
}

export async function submitFactorProgrammatic(factor, factorFile) {
  if (DRY_RUN) {
    return { ok: true, features: factor.name, raw: "[DRY-RUN] submit skipped", dry: true, attempts: 1 };
  }

  const className = extractClassNameFromH(factorFile) || factor.name;
  const features = isTemplateClass(factorFile) ? `${className}<>` : className;
  const feeds = categoriesToFeeds(factor.categories);

  console.log(`  [submit] ${factor.name} features=${features}${feeds ? ` feeds=${feeds}` : ""}`);

  const args = ["submit", "--file", factorFile, "--features", features, "--generate-xs", "--json"];
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
