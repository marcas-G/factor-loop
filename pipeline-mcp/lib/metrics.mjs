// 7 维评估数据抓取：从 checkOutput 读 feval/deep/pearson 产物，组装成结构化 JSON。
// 平台 decision_summary.csv 已经做了 X-Y 对级的 KEEP/WATCH/REJECT 判定 +
// score + reason，本模块做因子级聚合：把 N 个 X-Y 对压成单因子的 7 维摘要。
//
// 输出结构（喂给 LLM 做因子级评估）：
// {
//   factor_level: { n_pairs, keep, watch, reject, best_score, best_pair },
//   seven_dim_best: {
//     screening:   { ic_mean, icir, spearman, sign_match_rate, decay_robust, decay_severe, pair },
//     session_ic:  { morning, midday, afternoon, night, std, pair },
//     vol_regime:  { q1..q5, sign_consistent, pair },
//     zero:        { t_stat, p_value, pair },
//     train_test:  { train_ic, test_ic, decay, pair },
//   },
//   deep_best: { rank_ic, conditional_sharpe, cum_ret_pct, monthly_icir, daily_ic_tstat, signal_instability },
//   top_pairs: [{ pair, decision, score, ic_mean, icir, reason }],
//   failure_reasons: { low_icir: N, vol_regime_unstable: N, ... },
// }

import fs from "node:fs";
import path from "node:path";

const FACTOR_NAMES = ["ic_mean", "ic_ir", "icir", "spearman_r", "sign_match_rate", "score"];

// 简单 CSV 行解析：支持引号字段（含逗号）和转义双引号 ("")
export function parseCsvLine(line) {
  const cells = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQuotes) {
      if (c === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; }
        else inQuotes = false;
      } else cur += c;
    } else {
      if (c === '"') inQuotes = true;
      else if (c === ",") { cells.push(cur); cur = ""; }
      else cur += c;
    }
  }
  cells.push(cur);
  return cells;
}

export function readCsv(filePath) {
  if (!fs.existsSync(filePath)) return null;
  const text = fs.readFileSync(filePath, "utf8").trim();
  if (!text) return null;
  const lines = text.split(/\r?\n/);
  const header = parseCsvLine(lines[0].replace(/^﻿/, ""));
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    const cells = parseCsvLine(lines[i]);
    const row = {};
    for (let j = 0; j < header.length; j++) {
      row[header[j]] = cells[j] != null ? cells[j] : "";
    }
    rows.push(row);
  }
  return { header, rows };
}

function num(v) {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function bool(v) {
  if (v == null || v === "") return null;
  return v === "True" || v === "true" || v === "1";
}

// 按 abs(value) 最大选 best row，返回 { value, pair, row }
function pickBestAbs(rows, valueKey, pairKey) {
  let best = null;
  for (const r of rows) {
    const v = num(r[valueKey]);
    if (v == null) continue;
    if (!best || Math.abs(v) > Math.abs(best.value)) {
      best = { value: v, pair: r[pairKey] || `${r.x_col} vs ${r.y_col}`, row: r };
    }
  }
  return best;
}

// X-Y 对的 pair label，去重 instrument/horizon 信息
function pairLabel(r) {
  return `${r.x_col} vs ${r.y_col}`;
}

// 去掉 CSV 字段两侧的引号（decision_summary.csv 的 reason 字段会带引号）
function stripQuotes(v) {
  if (v == null) return v;
  let s = String(v);
  if (s.startsWith('"') && s.endsWith('"')) s = s.slice(1, -1);
  return s.replace(/""/g, '"');
}

export function extractMetricsFromCheckOutput(checkOutput, xname) {
  const result = {
    factor_level: { n_pairs: 0, keep: 0, watch: 0, reject: 0, best_score: null, best_pair: null },
    seven_dim_best: {},
    deep_best: {},
    top_pairs: [],
    failure_reasons: {},
    // 新增指标（来自 factor_check 深度分析 [6/7][7/7]）
    stationarity: {},
    transform_family: {},
  };

  // ---- 1. decision_summary.csv：聚合因子级 decision 分布 + best score ----
  const decisionCsv = findFirst(checkOutput, [
    `all_factors_decision_summary.csv`,
    `${xname}/dailyX/${xname}_feval/decision_summary.csv`,
  ]);
  const decisionRows = decisionCsv ? readCsv(decisionCsv)?.rows : null;
  if (decisionRows && decisionRows.length) {
    result.factor_level.n_pairs = decisionRows.length;
    for (const r of decisionRows) {
      const d = (r.decision || "").toUpperCase();
      if (d === "KEEP") result.factor_level.keep++;
      else if (d === "WATCH") result.factor_level.watch++;
      else if (d === "REJECT") result.factor_level.reject++;

      // reason 聚合（逗号分隔）
      const reasons = (r.reason || "").split(",").map(s => s.trim()).filter(Boolean);
      for (const reason of reasons) {
        result.failure_reasons[reason] = (result.failure_reasons[reason] || 0) + 1;
      }
    }
    // best score
    const best = decisionRows
      .map(r => ({ score: num(r.score), pair: pairLabel(r), decision: r.decision, reason: r.reason || "" }))
      .filter(x => x.score != null)
      .sort((a, b) => b.score - a.score);
    if (best.length) {
      result.factor_level.best_score = best[0].score;
      result.factor_level.best_pair = best[0].pair;
      result.top_pairs = best.slice(0, 3);
    }
  }

  // ---- 2. feval 子目录里的 7 维 CSV ----
  const fevalDir = findFirst(checkOutput, [
    `${xname}/dailyX/${xname}_feval`,
  ]);
  if (fevalDir) {
    // Screening: screening.csv — 取 |ic_mean| 最大的 pair
    const screening = readCsv(path.join(fevalDir, "screening.csv"))?.rows;
    if (screening && screening.length) {
      const best = pickBestAbs(screening, "ic_mean", null);
      if (best) {
        result.seven_dim_best.screening = {
          ic_mean: best.value,
          icir: num(best.row.ic_ir),
          spearman: num(best.row.spearman_r),
          sign_match_rate: num(best.row.sign_match_rate),
          zero_ratio: num(best.row.zero_ratio),
          pair: pairLabel(best.row),
        };
      }
    }
    // Session IC: session_ic.csv — std 最小的 pair（最稳定）
    const session = readCsv(path.join(fevalDir, "session_ic.csv"))?.rows;
    if (session && session.length) {
      const sorted = session
        .map(r => ({ std: num(r.ic_std_across_sessions), row: r }))
        .filter(x => x.std != null)
        .sort((a, b) => a.std - b.std);
      if (sorted.length) {
        const b = sorted[0].row;
        result.seven_dim_best.session_ic = {
          morning: num(b.morning_ic),
          midday: num(b.midday_ic),
          afternoon: num(b.afternoon_ic),
          night: num(b.night_ic),
          std: num(b.ic_std_across_sessions),
          pair: pairLabel(b),
        };
      }
    }
    // Vol regime: vol_regime_ic.csv — sign 最一致的 pair（所有 q 同号）
    const vol = readCsv(path.join(fevalDir, "vol_regime_ic.csv"))?.rows;
    if (vol && vol.length) {
      const annotated = vol.map(r => {
        const qs = [num(r.q1_ic), num(r.q2_ic), num(r.q3_ic), num(r.q4_ic), num(r.q5_ic)].filter(x => x != null);
        const allSameSign = qs.length === 5 && qs.every(x => Math.sign(x) === Math.sign(qs[0]));
        return { row: r, allSameSign, minAbs: Math.min(...qs.map(Math.abs)) };
      });
      // 优先选 allSameSign 的，其次 minAbs 最大的
      const sorted = annotated.sort((a, b) => {
        if (a.allSameSign !== b.allSameSign) return a.allSameSign ? -1 : 1;
        return b.minAbs - a.minAbs;
      });
      if (sorted.length) {
        const b = sorted[0].row;
        result.seven_dim_best.vol_regime = {
          q1: num(b.q1_ic), q2: num(b.q2_ic), q3: num(b.q3_ic), q4: num(b.q4_ic), q5: num(b.q5_ic),
          sign_consistent: sorted[0].allSameSign,
          pair: pairLabel(b),
        };
      }
    }
    // Zero analysis: zero_analysis.csv — |t_stat| 最大的 pair（X=0 vs X!=0 差异最显著）
    const zero = readCsv(path.join(fevalDir, "zero_analysis.csv"))?.rows;
    if (zero && zero.length) {
      const best = pickBestAbs(zero, "t_stat", null);
      if (best) {
        result.seven_dim_best.zero = {
          t_stat: best.value,
          p_value: num(best.row.p_value),
          y_mean_x0: num(best.row.y_mean_x0),
          y_mean_xnz: num(best.row.y_mean_xnz),
          pair: pairLabel(best.row),
        };
      }
    }
    // Train/Test Decay: train_test.csv — same_sign=true 且 |test_ic| 最大的 pair
    const tt = readCsv(path.join(fevalDir, "train_test.csv"))?.rows;
    if (tt && tt.length) {
      const sameSignRows = tt.filter(r => bool(r.same_sign) === true);
      const candidates = (sameSignRows.length ? sameSignRows : tt);
      const best = pickBestAbs(candidates, "test_ic", null);
      if (best) {
        result.seven_dim_best.train_test = {
          train_ic: num(best.row.train_ic),
          test_ic: num(best.row.test_ic),
          decay: num(best.row.ic_decay),
          same_sign: bool(best.row.same_sign),
          pair: pairLabel(best.row),
        };
      }
    }
  }

  // ---- 2b. bucket_analysis_summary.csv：可交易性(换手/成本后/容量,factor_check 算)----
  const bucketCsv = findFirst(checkOutput, [`bucket_analysis_summary.csv`, `${xname}/dailyX/bucket_analysis_summary.csv`]);
  const bucketRows = bucketCsv ? readCsv(bucketCsv)?.rows : null;
  if (bucketRows && bucketRows.length) {
    const best = bucketRows
      .map(r => ({ s: num(r.sharpe_net_8bps), row: r }))
      .filter(x => x.s != null)
      .sort((a, b) => Math.abs(b.s) - Math.abs(a.s));
    if (best.length) {
      const b = best[0].row;
      result.seven_dim_best.tradability = {
        avg_turnover_per_day: num(b.avg_turnover_per_day),
        sharpe_net_8bps: num(b.sharpe_net_8bps),
        sharpe_net_16bps: num(b.sharpe_net_16bps),
        veto3_cost_double: bool(b.veto3_cost_double),
        capacity_risk: bool(b.capacity_risk),
        pair: pairLabel(b),
      };
    }
  }

  // ---- 3. deep_summary.csv：因子级 8 行摘要 ----
  const deepSummaryCsv = findFirst(checkOutput, [
    `all_factors_deep_summary.csv`,
  ]);
  const deepRows = deepSummaryCsv ? readCsv(deepSummaryCsv)?.rows : null;
  if (deepRows && deepRows.length) {
    for (const r of deepRows) {
      const analysis = r.analysis;
      const metric = r.metric;
      const value = num(r.value);
      if (value == null) continue;
      if (analysis === "Daily IC") result.deep_best.daily_ic_tstat = value;
      else if (analysis === "Rank IC") result.deep_best.rank_ic_max = value;
      else if (analysis === "Conditional Return" && metric === "best_annualized_sharpe") result.deep_best.conditional_sharpe = value;
      else if (analysis === "Conditional Return" && metric === "best_cum_ret_%") result.deep_best.cum_ret_pct = value;
      else if (analysis === "Signal Stability") result.deep_best.signal_instability_pct = value;
      else if (analysis === "Monthly IC" && metric === "best_icir") result.deep_best.monthly_icir = value;
      else if (analysis === "Monthly IC" && metric === "best_ic_mean") result.deep_best.monthly_ic_mean = value;
      // 新增指标（[6/7][7/7]）
      else if (analysis === "Stationarity") result.stationarity[metric] = value;
      else if (analysis === "Transform Family") result.transform_family[metric] = value;
    }
  }

  return result;
}

// 在 checkOutput 下找第一个存在的路径
function findFirst(base, candidates) {
  for (const c of candidates) {
    const p = path.join(base, c);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

// 从 daily_ic_results.txt 抓 4 个数值（保留向后兼容，给 persist 用）
export function extractMetricsFromDailyIc(dailyIcPreview) {
  if (!dailyIcPreview) return {};
  const find = (re) => {
    const m = String(dailyIcPreview).match(re);
    return m ? Number(m[1]) : null;
  };
  const icMean = find(/IC[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)/i);
  const icir = find(/ICIR[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)/i);
  const sharpe = find(/Sharpe[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)/i);
  const rankIc = find(/Rank\s*IC[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)/i);
  return { ic_mean: icMean, icir, sharpe, rank_ic: rankIc };
}

// check_output_missing 时检测因子值是否全零：读 feval/screening.csv 的 zero_ratio 列 max。
// 全零(zero_ratio>=0.999) + daily_ic 缺失 = DAG 缓存陷阱特征（代码对但缓存旧全零结果）。
// 文件缺失/无数据 → false（无法判全零，不触发换名）。
export function isAllZeroFromScreening(checkOutput, featureKey) {
  const screeningPath = path.join(checkOutput, featureKey, "dailyX", `${featureKey}_feval`, "screening.csv");
  const csv = readCsv(screeningPath);
  if (!csv || !csv.rows || !csv.rows.length) return false;
  let maxZero = 0;
  for (const r of csv.rows) {
    const z = num(r.zero_ratio);
    if (z != null && z > maxZero) maxZero = z;
  }
  return maxZero >= 0.999;
}
