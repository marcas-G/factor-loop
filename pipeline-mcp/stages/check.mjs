// Step 2C: check（程序化路径：调 pipeline-py/factor_check.py run）。
// 评估分层（failureLayer）+ Airflow 通用失败分诊 + daily_ic 抓取。
//
// 分层原则：按【根因 task 的 locus + 信号】分层，不再凭 dag_state 猜。
//   - compile locus  (build_model/generate_modelcpp) + 编译错 → compile_failed        (因子代码, 重写)
//   - runtime locus  (generate_xy) + 崩溃信号(134/139/abort/assert) → factor_runtime_crash (因子代码, 重写)
//   - runtime locus  + exit≠0 无崩溃 → factor_runtime_error                              (因子代码, 重写)
//   - setup locus    (start/configs/zip 等基础设施任务) failed → platform_transient     (infra, 重 check 不重写)
//   - dag success + daily_ic 空/过小 → check_output_missing / check_output_too_small    (因子质量, 重写)
//   - dag running / 无分诊信息 / factor_check 超时 → platform_transient                  (真 transient, 有界重 check)
// evidence 永远带 rootTask/locus/exitCode/signals/causeText/rawTail，不再出现空 stderr。

import fs from "node:fs";
import path from "node:path";

import { DRY_RUN, FACTOR_CHECK_PY, RUN_DIR, FACTORS_DB } from "../lib/config.mjs";
import { runPy } from "../run-py.mjs";
import { triageFailure } from "../airflow-log.mjs";
import { extractMetricsFromCheckOutput } from "../lib/metrics.mjs";
import { DatabaseSync } from "node:sqlite";

// 平台 feature 名 = .h 文件 stem（parse_index 实测：book_HHI.h → "book_HHI"）。
// 文件名≠class 名时，class 名(如 BHHI)对不上平台 stem(book_HHI)→ factor_check wait 永久 pending。
// 故 featureKey 必须用 stem：factor_file 优先 → factors 表 file_path 兜底 → class 名最后(带 warning)。
// 只读连接(模块级缓存,避免每次 new/close)。WAL 模式下读不阻塞 factor-db 写连接;
// query_only 防误写,busy_timeout 兜底等锁而非立刻 SQLITE_BUSY。
let _readDb = null;
function readDb() {
  if (_readDb) return _readDb;
  _readDb = new DatabaseSync(FACTORS_DB);
  _readDb.exec("PRAGMA query_only = ON");
  _readDb.exec("PRAGMA busy_timeout = 5000");
  return _readDb;
}

// 平台 feature 名 = .h 文件 stem（parse_index 实测：book_HHI.h → "book_HHI"）。
// 文件名≠class 名时，class 名(如 BHHI)对不上平台 stem(book_HHI)→ factor_check wait 永久 pending。
// 故 featureKey 必须用 stem：factor_file 优先 → factors 表 file_path 兜底 → class 名最后(带 warning)。
function featureStemFromDb(xname) {
  try {
    const row = readDb().prepare("SELECT file_path FROM factors WHERE xname = ?").get(xname);
    if (row && row.file_path) return path.basename(row.file_path, ".h");
  } catch (e) { /* db 不可用返回 null */ }
  return null;
}

// 程序化路径：调 factor_check.py run --skip-submit 一次完成 wait/download/analyze
// 前置条件：submitResult.ok === true（submit 失败由 run-factor.mjs 状态机处理，不会到这里）
export async function checkFactorProgrammatic(factor, submitResult, checkOutput) {
  // 平台用 .h stem 注册 feature 名；factor_file 缺时从 factors 表 file_path 兜底，
  // 避免 class 名(文件名≠class 时)与平台 stem mismatch → factor_check wait 永久 pending。
  const classFallback = (submitResult.features || factor.name).replace(/<.*>$/, "").trim();
  const stemFromDb = factor.factor_file ? null : featureStemFromDb(factor.name);
  const featureKey = factor.factor_file
    ? path.basename(factor.factor_file, ".h")
    : (stemFromDb ?? classFallback);
  if (!factor.factor_file && !stemFromDb) {
    console.error(`  [check] ⚠️ ${factor.name}: 无 factor_file 且 factors 表无 file_path，回退 class 名 "${featureKey}"——平台若用 .h stem 注册将永久 pending`);
  }

  if (DRY_RUN) {
    const mockPath = findDailyIc(checkOutput, featureKey);
    return {
      ok: true,
      failureLayer: "check_done",
      checkOutput,
      dailyIcPath: mockPath,
      dailyIcSize: 4096,
      summary: `[DRY-RUN mock] ${factor.name} 检查跳过，假设成功`,
      evidence: { reason: "dry_run", daily_ic_preview: "IC=0.038, ICIR=2.8, t-stat=4.2 (mock 数据)" },
    };
  }

  console.log(`  [check-prog] ${factor.name} → ${checkOutput}`);

  const result = await runPy(
    FACTOR_CHECK_PY,
    ["run", "--skip-submit", "--names", featureKey, "--dir", checkOutput, "--mode", "full"],
    { timeoutSec: 86400 }
  );

  const dailyIcPath = findDailyIc(checkOutput, featureKey);
  const dailyIcExists = fs.existsSync(dailyIcPath);
  const dailyIcSize = dailyIcExists ? fs.statSync(dailyIcPath).size : 0;

  // 通用失败分诊：定位根因 task + 真实信号（失败容忍，不影响主流程）。
  const tg = await triageFailure({ factorName: featureKey }).catch(() => null);
  const triageEvidence = tg && tg.ok && tg.triaged
    ? {
        airflow_dag_run_id: tg.dagRunId,
        airflow_root_task: tg.rootTask,
        airflow_locus: tg.locus,
        airflow_mapped: tg.mapped,
        airflow_n_root_instances: tg.nRootInstances,
        airflow_exit_code: tg.exitCode,
        airflow_signals: tg.signals,
        cause_text: tg.causeText || undefined,
        stderr_tail: (tg.causeText || tg.rawTail || "").slice(-500) || undefined,
        airflow_task_state_summary: tg.taskStateSummary,
        raw_tail: tg.rawTail ? tg.rawTail.slice(-800) : undefined,
      }
    : null; // success/running/无 dag_run → 无分诊证据，靠下面 dailyIc / 超时分支

  // —— 1. factor_check.py 超时（自身没跑完 wait/download） ——
  if (result.timedOut) {
    // 但若分诊已确认 dag=failed 的真因，优先报真因，不要笼统说超时
    if (triageEvidence) {
      return _classifyFailed({ checkOutput, dailyIcPath, dailyIcExists, dailyIcSize, result, triageEvidence, tg });
    }
    return {
      ok: false,
      failureLayer: "platform_transient",
      checkOutput,
      dailyIcPath: dailyIcExists ? dailyIcPath : null,
      dailyIcSize,
      summary: `[检查失败] factor_check 超时 (${result.durationMs}ms)，dag 未确认 failed`,
      evidence: {
        reason: "platform_transient",
        stdout_tail: result.stdout.slice(-500),
        stderr_tail: (result.stderr || "").slice(-500),
        note: "factor_check.py 超时且未能确认 dag 失败；多为平台管道慢/资源紧，有界重 check，不重写因子",
      },
    };
  }

  // —— 2. factor_check.py 非 0 退出（通常因平台 state=failed 而中止） ——
  if (result.exitCode !== 0) {
    if (triageEvidence) {
      // dag=failed 且已分诊到根因 → 按 (locus, 信号) 精确分层
      return _classifyFailed({ checkOutput, dailyIcPath, dailyIcExists, dailyIcSize, result, triageEvidence, tg });
    }
    // 无分诊信息：dag 可能 success（下载/分析阶段失败）或仍 running
    const dagState = tg && tg.ok ? tg.dagState : null;
    if (dagState === "running") {
      return _transient(checkOutput, dailyIcPath, dailyIcExists, dailyIcSize, result, "dag 仍 running，因子未跑完");
    }
    if (dailyIcExists && dailyIcSize >= 1024) {
      // dag 成功、有 IC，但 factor_check 非0退出（分析阶段小问题）—— 仍当可评估
      return _success(checkOutput, dailyIcPath, dailyIcSize, result, featureKey);
    }
    // 兜底：真因不明，但带上 stdout/stderr 尾部，不再空 stderr
    return {
      ok: false,
      failureLayer: "check_failed",
      checkOutput,
      dailyIcPath: dailyIcExists ? dailyIcPath : null,
      dailyIcSize,
      summary: `[检查失败] factor_check exit=${result.exitCode}，dag=${dagState || "n/a"}，真因未明（见 stdout/stderr 尾）`,
      evidence: {
        reason: "check_failed",
        exit_code: result.exitCode,
        dag_state: dagState,
        stdout_tail: result.stdout.slice(-500),
        stderr_tail: (result.stderr || "").slice(-500),
        ...(await _maybeDiagnosis(result)),
      },
    };
  }

  // —— 3. factor_check.py 正常退出：看 daily_ic 产物 ——
  if (!dailyIcExists || dailyIcSize < 1024) {
    const reason = !dailyIcExists ? "check_output_missing" : "check_output_too_small";
    // dag 若 failed 仍优先报真因
    if (triageEvidence) {
      return _classifyFailed({ checkOutput, dailyIcPath, dailyIcExists, dailyIcSize, result, triageEvidence, tg });
    }
    const diagnosis = reason === "check_output_too_small" ? buildTooSmallDiagnosis() : null;
    return {
      ok: false,
      failureLayer: reason,
      checkOutput,
      dailyIcPath: dailyIcExists ? dailyIcPath : null,
      dailyIcSize,
      summary: `[检查失败] daily_ic_results.txt ${!dailyIcExists ? "缺失" : `过小 (${dailyIcSize}B)`}`,
      evidence: {
        reason,
        daily_ic_size: dailyIcSize,
        stdout_tail: result.stdout.slice(-500),
        dir_listing: listDir(checkOutput, 3, 30),
        ...(diagnosis || {}),
      },
    };
  }

  return _success(checkOutput, dailyIcPath, dailyIcSize, result, featureKey);
}

// 纯函数：triage 结果 → {layer, diagnosis, summary}。独立于平台调用，可单测。
// locus + 信号 决定分层（不凭 dag_state）：
//   compile → compile_failed；runtime+崩溃 → factor_runtime_crash；runtime+非崩溃 → factor_runtime_error；
//   setup/infra → platform_transient（有界重 check，不重写因子）。
export function decideFailureLayer(tg) {
  const hasCrash = (tg.signals?.crash?.length > 0) || [134, 139, 136, 138].includes(tg.exitCode);
  const hasAnySignal = !!(tg.signals?.crash?.length || tg.signals?.compile?.length || tg.signals?.traceback?.length || tg.exitCode);
  if (tg.locus === "compile") {
    return { layer: "compile_failed", diagnosis: buildCompileDiagnosis(tg.causeText).diagnosis, summary: `compile_failed (root=${tg.rootTask})` };
  }
  if (tg.locus === "runtime" && hasCrash) {
    return { layer: "factor_runtime_crash", diagnosis: buildRuntimeCrashDiagnosis(tg.causeText, tg.exitCode).diagnosis, summary: `factor_runtime_crash (root=${tg.rootTask}, exit=${tg.exitCode ?? "?"})` };
  }
  if (tg.locus === "runtime") {
    return { layer: "factor_runtime_error", diagnosis: buildRuntimeErrorDiagnosis(tg.causeText, tg.exitCode).diagnosis, summary: `factor_runtime_error (root=${tg.rootTask})` };
  }
  // setup/infra locus: 有确凿信号才 platform_transient; signals 全空(log 缺失/分诊失败)→ check_failed 不甩锅平台
  if (!hasAnySignal) {
    return { layer: "check_failed", diagnosis: null, summary: `check_failed (root=${tg.rootTask}, locus=${tg.locus}, 分诊信号缺失, 真因未明)` };
  }
  return { layer: "platform_transient", diagnosis: null, summary: `platform_transient (root=${tg.rootTask}, locus=${tg.locus})` };
}

// dag=failed 且分诊到根因 task：按 (locus, 信号) 分层
function _classifyFailed({ checkOutput, dailyIcPath, dailyIcExists, dailyIcSize, result, triageEvidence, tg }) {
  const { layer, diagnosis, summary } = decideFailureLayer(tg);
  if (layer === "platform_transient") {
    // setup/infra 任务 failed —— 多为平台/配置侧，有界重 check，不重写因子；但带 rawTail 不留黑盒
    return _transient(checkOutput, dailyIcPath, dailyIcExists, dailyIcSize, result, `根因任务 ${tg.rootTask} (locus=${tg.locus}) failed`, triageEvidence);
  }
  return {
    ok: false,
    failureLayer: layer,
    checkOutput,
    dailyIcPath: dailyIcExists ? dailyIcPath : null,
    dailyIcSize,
    summary: `[检查失败] ${summary}`,
    evidence: {
      reason: layer,
      dag_state: "failed",
      stdout_tail: result.stdout.slice(-500),
      ...triageEvidence,
      ...(diagnosis ? { diagnosis } : {}),
    },
  };
}

function _transient(checkOutput, dailyIcPath, dailyIcExists, dailyIcSize, result, note, triageEvidence = null) {
  return {
    ok: false,
    failureLayer: "platform_transient",
    checkOutput,
    dailyIcPath: dailyIcExists ? dailyIcPath : null,
    dailyIcSize,
    summary: `[检查失败] platform_transient — ${note}`,
    evidence: {
      reason: "platform_transient",
      stdout_tail: result.stdout.slice(-500),
      stderr_tail: (result.stderr || "").slice(-500),
      note,
      ...(triageEvidence || {}),
    },
  };
}

function _success(checkOutput, dailyIcPath, dailyIcSize, result, featureKey) {
  const icContent = fs.readFileSync(dailyIcPath, "utf8");
  const icPreview = icContent.split("\n").slice(0, 30).join("\n");
  const sevenDimSummary = extractMetricsFromCheckOutput(checkOutput, featureKey);
  return {
    ok: true,
    failureLayer: "check_done",
    checkOutput,
    dailyIcPath,
    dailyIcSize,
    summary: `[检查完成] IC 文件 ${dailyIcSize}B（详见 evidence.daily_ic_preview）`,
    evidence: {
      reason: "check_done",
      daily_ic_preview: icPreview,
      seven_dim_summary: sevenDimSummary,
      stdout_tail: result.stdout.slice(-500),
    },
  };
}

// factor_check.py 产物结构：<checkOutput>/<featureKey>/dailyX/<featureKey>_deep/daily_ic_results.txt
export function findDailyIc(checkOutput, featureKey) {
  return path.join(checkOutput, featureKey, "dailyX", `${featureKey}_deep`, "daily_ic_results.txt");
}

export function listDir(dir, maxDepth = 3, maxEntries = 30) {
  const lines = [];
  let count = 0;
  function walk(d, depth = 0) {
    if (depth > maxDepth || count >= maxEntries) return;
    let entries;
    try { entries = fs.readdirSync(d, { withFileTypes: true }); }
    catch { return; }
    for (const e of entries) {
      if (count >= maxEntries) { lines.push("... (more)"); return; }
      const prefix = "  ".repeat(depth);
      lines.push(`${prefix}${e.isDirectory() ? "/" : ""}${e.name}`);
      count++;
      if (e.isDirectory()) walk(path.join(d, e.name), depth + 1);
    }
  }
  walk(dir);
  return lines.join("\n");
}

async function _maybeDiagnosis(result) {
  const tail = (result.stderr || "") + "\n" + (result.stdout || "");
  if (/Traceback|Error|Exception/i.test(tail)) return buildCheckFailedDiagnosis();
  return {};
}

// 结构性失败的可执行诊断（喂给 write-factor 照做，不是自然语言描述）。

function buildCompileDiagnosis(causeText) {
  return {
    diagnosis: {
      nature: "编译失败（因子代码）：build_model 阶段 g++ 编译因子 .h 失败",
      root_cause: causeText || "见 stderr_tail / cause_text 的 file:line: error",
      fix_hint: "按 cause_text 每条 file:line: error 精确改对应行；常见：std::pair 无 clear()、std::vector 无 pop_front()(用 erase(begin()))、缺 #include",
    },
  };
}

function buildRuntimeCrashDiagnosis(causeText, exitCode) {
  return {
    diagnosis: {
      nature: `运行期崩溃（因子代码）：generate_xy 执行因子时 ${exitCode ? `exit ${exitCode}(SIGABRT/SIGSEGV)` : "崩溃"} core dump。编译通过但跑数据时崩 → 未定义行为`,
      root_cause_candidates: [
        "容器（vector/deque/array）未按 _numFeeds / 档位数 resize 即用 operator[] 访问 → 越界 (最常见！所有 per-feed 容器必须在 initialize/onStarted 里 resize 到 _numFeeds)",
        "未初始化的成员（指针/迭代器/计数器）首帧使用",
        "整数除零 / NaN 传播到后续计算 (加 std::isfinite 守卫 + eps 保底)",
        "模板参数越界（MaxLevels/窗口为0或超范围）→ 检查 static_assert",
        "feed().bidSize/askSize 在档位不足时越界 → 用 availableLevels=min(MaxLevels, bidNumLevels, askNumLevels) 约束",
      ],
      signal: causeText || "Aborted (core dumped) / Segmentation fault",
      fix_hint: "逐个核查 per-feed 容器是否在 initialize/onStarted resize 到 _numFeeds；onEndBook 里所有 operator[] 下标先校验 <size()；冷启动未就绪时输出 0 不访问空容器",
    },
  };
}

function buildRuntimeErrorDiagnosis(causeText, exitCode) {
  return {
    diagnosis: {
      nature: `运行期错误（因子代码）：generate_xy exit=${exitCode ?? "?"} 非崩溃类失败`,
      root_cause: causeText || "见 raw_tail / cause_text",
      fix_hint: "读 raw_tail 定位具体错误行；常见数值/边界问题",
    },
  };
}

function buildTooSmallDiagnosis() {
  return {
    diagnosis: {
      nature: "结构性失败（因子质量）：DAG 成功但 IC 产物空 → 因子值近全0/NaN/非零率过低，平台跳过 IC 计算",
      root_cause_candidates: [
        "硬门控（如 volHigh ? x : 0）把因子压成近全0 → 降门控分位(如 0.80→0.50) 或软化成 sigmoid 权重 out=w*lr",
        "冷启动期全0（需积累 N 样本才输出，如 _volHistory.size()>=30）→ 缩短冷启动阈值或冷启动期输出 baseline",
        "底事件罕见导致信号稀疏（如撤单/大单触发率<5%）→ 放宽触发阈值/降分位/换更活跃品种",
        "log/除法产生 NaN/极值 → std::log(std::max(v,1e-20)) 保底 + 最终 isfinite+clamp",
      ],
      fix_hint: "定位 onEndBook 里把结果归0的门控/冷启动分支，放宽或软化；确认输出在正常行情下非零率>20%",
    },
  };
}

function buildCheckFailedDiagnosis() {
  return {
    diagnosis: {
      nature: "factor_check.py 执行异常（pipeline python 侧）",
      root_cause_candidates: [
        "查 stderr_tail/stdout_tail 的 traceback 定位",
        "若 traceback 指向因子值解析（如非有限值/类型不符）→ 因子输出格式问题",
        "若指向平台/下载/cookie → 平台侧，标 platform_transient 重试",
      ],
      fix_hint: "读 traceback；因子侧改代码，平台侧重 check",
    },
  };
}
