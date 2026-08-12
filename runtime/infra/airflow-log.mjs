// 通用失败分诊：从 Airflow（同账号）定位因子 dag 失败的【根因 task + 真实信号】。
//
// 设计目标（不是"碰到一个信号打一个补丁"，而是通用检测+分诊）：
//   1. 枚举该 dag_run 的【全部】task instance，区分 failed(真失败) / upstream_failed(连坐) / success，
//      不再只抓一个 task —— 根因任务才该被诊断。
//   2. mapped task（generate_xy 动辄几十~上百实例）按 map_index 取日志，修掉无 map_index 时的 404。
//   3. 通用信号抽取：exit code 解码(134/139/137/136) + 编译错 + C++ abort/assert/terminate/what()
//      + python traceback，外加【兜底 rawTail】(过滤 airflow INFO 模板后的尾部日志)，
//      保证任何失败模式都不再是空 stderr。
//   4. 输出结构化 {dagState, rootTask, locus, mapped, exitCode, signals, causeText, rawTail}，
//      由 check.mjs 按 (locus, 信号) 分层，不再凭 dag_state 猜。
//
// 平台 featuretool API 不暴露 stderr，但底层 Airflow（同账号 ~/featuretool_creds.json）暴露 task log。
// dag_run_id 命名：{username}-{FactorName}-{ISO timestamp}-{TZ}
// 任何 Airflow 异常都吞掉返回 ok=false（调用方继续用平台 state=failed 判断，不依赖这个）。

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const DEFAULT_HOST = "airflow.dev.xyz.abc";
const CREDS_FILE = path.join(process.env.HOME, "featuretool_creds.json");
const DAG_ID = "GenerateXYs";

// 根因 task 的 locus 分类（决定是编译问题还是运行期问题）
const COMPILE_LOCUS = ["build_model", "generate_modelcpp", "generate_abstract_model", "generate_build_model_command"];
const RUNTIME_LOCUS = ["generate_xy"];
// 其余（start/end/zip_xy_files/generate_xy_commands/generate_configs/check_if_run_xy）= setup/infra

const COMPILE_ERROR_RE =
  /(?:INFO - )?([^:\s]+\.(?:h|hpp|cc|c|cpp)):(\d+):(?:\d+:)?\s*(error|fatal error|no matching function for call to|undefined reference|cannot find|no member):?([^\n]+)/g;

const EXIT_CODE_RE = /(?:Command exited with|returned a non-zero exit code|return code)\s*(\d{2,3})/g;

const CRASH_PATTERNS = [
  /Aborted\s*\(core dumped\)/,
  /Segmentation fault/i,
  /SIGABRT/, /SIGSEGV/, /SIGFPE/, /SIGKILL/,
  /terminate called after throwing an instance of/i,
  /terminate called after throwing/,
  /Assertion .* failed/i,
  /Assertion failed:/i,
  /double free or corruption/i,
  /malloc\s*\)/i,
  /stack smashing detected/i,
];

const EXIT_CODE_MEANING = {
  134: "SIGABRT (abort/assert/throw)",
  139: "SIGSEGV (segfault)",
  137: "SIGKILL (常为 OOM-killer)",
  136: "SIGFPE (整数除零)",
  138: "SIGBUS",
};

function readCreds(credsFile = CREDS_FILE) {
  if (!fs.existsSync(credsFile)) return null;
  try {
    const d = JSON.parse(fs.readFileSync(credsFile, "utf8"));
    if (d.username && d.password) return d;
  } catch {}
  return null;
}

function curlGet(host, basicAuth, ep) {
  return execFileSync(
    "curl",
    ["-s", "-k", "--max-time", "30", "-H", `Authorization: Basic ${basicAuth}`, `https://${host}${ep}`],
    { encoding: "utf8", timeout: 35000 }
  );
}

function locusOf(taskId) {
  if (COMPILE_LOCUS.some((t) => taskId.includes(t))) return "compile";
  if (RUNTIME_LOCUS.some((t) => taskId.includes(t))) return "runtime";
  return "setup";
}

function extractCompileErrors(logText) {
  const hits = [];
  let m;
  COMPILE_ERROR_RE.lastIndex = 0;
  while ((m = COMPILE_ERROR_RE.exec(logText)) !== null) {
    const basename = m[1].split("/").pop();
    hits.push(`${basename}:${m[2]}: ${m[3]}: ${(m[4] || "").trim()}`);
  }
  return [...new Set(hits)];
}

function extractExitCodes(logText) {
  const codes = [];
  let m;
  EXIT_CODE_RE.lastIndex = 0;
  while ((m = EXIT_CODE_RE.exec(logText)) !== null) codes.push(Number(m[1]));
  return [...new Set(codes)];
}

function extractCrashSignals(logText) {
  const hits = [];
  for (const re of CRASH_PATTERNS) {
    const m = logText.match(re);
    if (m) hits.push(m[0].trim());
  }
  // C++ exception what(): 提取消息
  const what = logText.match(/what\(\):\s*([^\n]+)/);
  if (what) hits.push(`C++ exception: ${what[1].trim()}`);
  // terminate thrown 的类型
  const thrown = logText.match(/terminate called after throwing an instance of\s*['"]?(\S+)/);
  if (thrown) hits.push(`uncaught exception: ${thrown[1].replace(/['"]/g, "")}`);
  return [...new Set(hits)];
}

function extractPyTraceback(logText) {
  const m = logText.match(/Traceback \(most recent call last\):[\s\S]{0,1200}?\n([A-Za-z_.]*Error|Exception):[^\n]*/);
  return m ? [m[0].split("\n").slice(-3).join(" | ")] : [];
}

// 兜底：过滤掉 airflow INFO 模板行，保留有信息量的尾部日志，任何未知失败都不留空。
function extractRawTail(logText, maxLines = 30) {
  const keep = [];
  for (const raw of logText.split("\n")) {
    // 去 airflow 样板：纯调度/INFO 行
    const line = raw.replace(/^\[?\d{4}-\d\d-\d\dT[\d:+-]+\]?\s*\{[^}]+\}\s*(INFO|DEBUG)\s*-\s*/, "");
    if (!line.trim()) continue;
    if (/^Dependencies all met|^Starting attempt|^Executing <|^Started process|^Running:|^Running command|^\['airflow'|^Exporting env vars|^Tmp dir|^Marking task as|^Task exited|^0 downstream/.test(line)) continue;
    keep.push(line);
    if (keep.length > maxLines * 3) break;
  }
  return keep.slice(-maxLines).join("\n");
}

/**
 * 通用失败分诊。
 * @param {object} opts {factorName, username?, host?, maxMapProbe?=3}
 * @returns {Promise<object>} 见文件头注释。失败/无 dag_run 时 ok=false。
 */
export async function triageFailure({ factorName, username, host = DEFAULT_HOST, maxMapProbe = 3 }) {
  const creds = readCreds();
  const user = username || creds?.username;
  if (!user || !creds) return _fail("missing_credentials");
  const basic = Buffer.from(`${creds.username}:${creds.password}`).toString("base64");

  // 1. 最新 dag run
  let runs;
  try {
    const body = curlGet(host, basic, `/api/v1/dags/${DAG_ID}/dagRuns?limit=100&order_by=-start_date`);
    runs = (JSON.parse(body).dag_runs || []).filter((r) => r.dag_run_id.startsWith(`${user}-${factorName}-`));
  } catch (e) {
    return _fail("dagruns_fetch_failed", e.message);
  }
  if (!runs.length) return _fail("no_dag_run");
  const latest = runs[0];

  // success / running：无失败可分诊（调用方按 dailyIc / 超时自行处理）
  if (latest.state !== "failed") {
    return { ok: true, triaged: false, dagRunId: latest.dag_run_id, dagState: latest.state, rootTask: null };
  }

  // 2. 全部 task instance
  let tis;
  try {
    const body = curlGet(
      host,
      basic,
      `/api/v1/dags/${DAG_ID}/dagRuns/${encodeURIComponent(latest.dag_run_id)}/taskInstances`
    );
    tis = JSON.parse(body).task_instances || [];
  } catch (e) {
    return _fail("taskinstances_fetch_failed", e.message, latest.dag_run_id);
  }

  // 3. 根因 task = 有 failed 实例的 task（排除只有 upstream_failed 的连坐任务）
  const failedById = new Map(); // taskId -> failed instances
  const taskStateSummary = {}; // taskId -> {state:count}
  for (const t of tis) {
    const s = (taskStateSummary[t.task_id] ||= {});
    s[t.state] = (s[t.state] || 0) + 1;
    if (t.state === "failed") (failedById.get(t.task_id) || failedById.set(t.task_id, []).get(t.task_id)).push(t);
  }
  const failedTaskIds = [...failedById.keys()];

  // 4. 选根因 task：compile-locus 优先（编译错会连坐导致 generate_xy upstream_failed），其次 runtime-locus，其次其它
  const pick = (locus) => failedTaskIds.find((id) => locusOf(id) === locus);
  const rootTaskId = pick("compile") || pick("runtime") || failedTaskIds[0];
  const rootInstances = failedById.get(rootTaskId) || [];
  const mapped = rootInstances.length > 1 || rootInstances.some((t) => t.map_index >= 0);

  // 5. 取根因 task 日志（mapped 按 map_index 探测；map_index 缺失则探测 0..N 防 404 空 log）
  const probes = mapped ? rootInstances.slice(0, maxMapProbe) : rootInstances.slice(0, 1);
  let logBlob = "";
  for (const inst of probes) {
    const maxTry = Math.max(inst.try_number || 1, 2);
    // map_index 候选: inst 有效值优先; 否则 mapped 时探测 0..maxMapProbe(airflow mapped task 缺 map_index 会 404, 历史 bug 致 signals 空/误判 platform)
    const miVals = (inst.map_index != null && inst.map_index >= 0)
      ? [inst.map_index]
      : (mapped ? Array.from({ length: maxMapProbe }, (_, i) => i) : [null]);
    let got = false;
    for (const miVal of miVals) {
      for (let ty = 1; ty <= maxTry && !got; ty++) {
        const mi = miVal != null ? `?map_index=${miVal}` : "";
        try {
          const log = curlGet(
            host,
            basic,
            `/api/v1/dags/${DAG_ID}/dagRuns/${encodeURIComponent(latest.dag_run_id)}/taskInstances/${encodeURIComponent(rootTaskId)}/logs/${ty}${mi}`
          );
          if (log && log.length > 10 && !log.includes('"status": 404')) { logBlob += "\n" + log; got = true; }
        } catch {}
      }
      if (got) break;
    }
  }

  // 6. 通用信号抽取
  const compileErrs = extractCompileErrors(logBlob);
  const exitCodes = extractExitCodes(logBlob);
  const crashes = extractCrashSignals(logBlob);
  const tracebacks = extractPyTraceback(logBlob);
  const rawTail = extractRawTail(logBlob);

  const exitCode = exitCodes[0] ?? null;
  const signals = {
    compile: compileErrs,
    crash: crashes,
    traceback: tracebacks,
    exit_codes: exitCodes.map((c) => `${c}=${EXIT_CODE_MEANING[c] || "non-zero"}`),
  };
  const causeParts = [...compileErrs, ...crashes, ...tracebacks, ...exitCodes.map((c) => `exit ${c} (${EXIT_CODE_MEANING[c] || "non-zero"})`)];
  const causeText = [...new Set(causeParts)].slice(0, 12).join("\n");

  return {
    ok: true,
    triaged: true,
    dagRunId: latest.dag_run_id,
    dagState: "failed",
    rootTask: rootTaskId,
    locus: locusOf(rootTaskId),
    mapped,
    nRootInstances: rootInstances.length,
    taskStateSummary,
    exitCode,
    signals,
    causeText,
    rawTail,
  };
}

function _fail(reason, detail, dagRunId = null) {
  return { ok: false, triaged: false, _reason: reason, _detail: detail || undefined, dagRunId };
}

// —— 向后兼容：旧 fetchFailureLog({factorName}) 形状 —— 供尚未迁移的调用方用。
// 新代码应直接用 triageFailure。
export async function fetchFailureLog({ factorName, username, host, tailBytes = 500 }) {
  const t = await triageFailure({ factorName, username, host }).catch(() => null);
  if (!t || !t.ok) {
    return { ok: false, dagRunId: t?.dagRunId ?? null, taskId: null, dagState: null, stderrTail: "", errorCount: 0, raw: "", _reason: t?._reason };
  }
  if (!t.triaged) {
    // success / running
    return { ok: true, dagRunId: t.dagRunId, taskId: null, dagState: t.dagState, stderrTail: "", errorCount: 0, raw: "" };
  }
  const stderrTail = (t.causeText || t.rawTail || "").slice(-tailBytes);
  return {
    ok: true,
    dagRunId: t.dagRunId,
    taskId: t.rootTask,
    dagState: "failed",
    stderrTail,
    errorCount: (t.signals.compile.length + t.signals.crash.length + t.signals.traceback.length) || (t.exitCode ? 1 : 0),
    raw: t.rawTail,
  };
}
