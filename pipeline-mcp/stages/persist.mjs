// DB 写入：根据 evaluate 阶段 LLM 输出的 verdict 决定写哪些表。
// 调度由 evaluate.mjs 负责（evaluate 完成后调 persistVerdict）。
//
// 策略：
//   verdict=pass:
//     - factors 表（status=evaluated）
//     - factor_evals 表（含 eval_metrics / conditional_returns / significant=1）
//     - lessons 表（type=success_pattern）
//   verdict=fail:
//     - factors 表（status=dead_end）
//     - factor_evals 表（含 eval_metrics / significant=0，更新 latest_ic/icir）
//     - lessons 表（type=dead_end，含 LLM 给的 suggested_iteration）
//
// 失败因子（submit_failed / platform_* / check_failed）→ 不调本函数，靠 state.json 留痕
//
// 注意：lessons.factor_xname 有 FK 约束 → factors.xname。
// verdict=fail 时不写 factors，所以 lesson 的 factor_xname 用 factor.name 会导致 FK 失败。
// 需要先把 factor 写进 factors 表（status=failed 或 draft），再写 lesson，但 evaluation=fail。
// 当前实现：verdict=fail 时也写 factors（status=dead_end）+ evals（status=dead_end，更新 latest_ic/icir）。

import * as factorDb from "../lib/factor-db.mjs";

// 从 eval_metrics 提取 metrics，适配三种历史结构：
//   1. 嵌套（期望）：{core_metrics: {screening: {ic_mean, icir}}, deep_best: {conditional_sharpe, rank_ic_max}}
//   2. factor 1 扁平：{1_ic, 2_icir, 3_hit_rate, 4_train_test_consistency, ...}
//   3. factor 2 扁平：{ic_mean, icir, hit_rate, t_stat, ..., bucket_annualized_sharpe, ic_decay}
function extractMetrics(evalMetrics) {
  if (!evalMetrics) return { ic_mean: null, icir: null, sharpe: null, rank_ic: null };
  const fromScreening = evalMetrics.core_metrics?.screening || {};
  const fromDeep = evalMetrics.deep_best || {};
  return {
    ic_mean: fromScreening.ic_mean ?? evalMetrics.ic_mean ?? evalMetrics["1_ic"] ?? null,
    icir: fromScreening.icir ?? evalMetrics.icir ?? evalMetrics["2_icir"] ?? null,
    sharpe: fromDeep.conditional_sharpe ?? evalMetrics.bucket_annualized_sharpe?.["@1s"] ?? null,
    rank_ic: fromDeep.rank_ic_max ?? null,
  };
}

export async function persistVerdict(factor, factorFile, checkResult, retryInfo, verdict, ideaId) {
  try {
    if (checkResult.failureLayer !== "check_done") {
      return { ok: false, error: `failureLayer=${checkResult.failureLayer} 非 check_done，不入库` };
    }
    if (!verdict) {
      return { ok: false, error: "verdict 为空" };
    }

    const featureKey = (checkResult.features || factor.name || "").replace(/<.*>$/, "").trim();
    if (!featureKey) {
      return { ok: false, error: "无法确定 xname（checkResult.features 和 factor.name 都为空）" };
    }
    const xname = featureKey;
    const ts = new Date().toISOString();
    const evalMetrics = checkResult.evidence?.eval_metrics || null;
    const metrics = extractMetrics(evalMetrics);
    const isPass = verdict.verdict === "pass";

    if (isPass) {
      // 写 factors + factor_evals + success_pattern lesson
      const written = factorDb.addFactorFromHFile(factorFile, ideaId, { status: "evaluated", intuition: factor.intuition || null });
      if (!written) {
        return { ok: false, error: `addFactorFromHFile 返回 null（frontmatter 解析失败或无 xname/class_name），factorFile=${factorFile}` };
      }
      factorDb.addEval(written, ts, metrics, ideaId, checkResult.checkOutput, {
        evalMetrics: evalMetrics,
        conditionalReturns: evalMetrics?.deep_best || null,
        significant: 1,
        mode: "full",
        status: "evaluated",
      });
      console.log(`  [db] 因子 ${written} 入库 status=evaluated IC=${metrics.ic_mean ?? "null"} ICIR=${metrics.icir ?? "null"}`);

      // 三件套兜底：.h 无 frontmatter 时从 state 补 formula_text/tags；再补 emb（新因子入库补全）
      factorDb.ensureFormulaTags(written, factor.formula, factor.tags);
      let anchorOk = false;
      try { anchorOk = (await factorDb.generateAnchorText(written)).ok; }
      catch (e) { console.error(`  [db] anchor 生成失败(降级不阻塞): ${e.message}`); }
      let embOk = false;
      try { embOk = (await factorDb.generateEmbedding(written)).ok; }
      catch (e) { console.error(`  [db] emb 生成失败(降级不阻塞): ${e.message}`); }
      console.log(`  [db] formula/tags 兜底完成; emb=${embOk ? "OK" : "SKIP/FAIL"}`);

      // success_pattern lesson
      const lessonText = buildSuccessLessonText(factor, verdict, evalMetrics);
      const lessonId = factorDb.addLesson("success_pattern", lessonText, {
        xname: written,
        ideaId,
        evidence: {
          xname: written,
          icir: metrics.icir,
          ic_mean: metrics.ic_mean,
          sharpe: metrics.sharpe,
          decision_breakdown: evalMetrics?.factor_level,
          deep_best: evalMetrics?.deep_best,
          strengths: verdict.key_strengths || [],
        },
      });
      console.log(`  [db] success_pattern lesson 入库 id=${lessonId}`);

      // 假设级支持度聚合（贝叶斯平滑，因子二元 verdict → 假设连续分数）
      if (ideaId != null) {
        const agg = factorDb.updateIdeaSupportScore(ideaId);
        console.log(`  [db] 假设 ${ideaId} 支持度: pass=${agg.pass}/${agg.total} score=${agg.score?.toFixed(3) ?? "null"}`);
      }

      // retry 改了代码且最终成功 → 记迭代关系
      if (retryInfo?.fixed && retryInfo?.changed_code) {
        const fromXname = factor.name;
        const toXname = written;
        if (fromXname !== toXname) {
          factorDb.addIteration(
            fromXname, toXname, ideaId,
            retryInfo.changes,
            "improved",
            metrics.icir ?? null
          );
          console.log(`  [db] 迭代关系 ${fromXname} → ${toXname} (${retryInfo.changes?.slice(0, 60)})`);
        }
      }
      return { xname: written, status: "evaluated", metrics, lessonId };
    } else {
      // verdict=fail：lesson.factor_xname 有 FK → 必须先写 factors（status=dead_end）
      // 同时写 factor_evals（带 status="dead_end" 触发 latest_ic/icir 更新）+ dead_end lesson
      const written = factorDb.addFactorFromHFile(factorFile, ideaId, { status: "dead_end", intuition: factor.intuition || null });
      if (!written) {
        return { ok: false, error: `addFactorFromHFile 返回 null（frontmatter 解析失败或无 xname/class_name），factorFile=${factorFile}` };
      }
      factorDb.addEval(written, ts, metrics, ideaId, checkResult.checkOutput, {
        evalMetrics: evalMetrics,
        conditionalReturns: evalMetrics?.deep_best || null,
        significant: 0,
        mode: "full",
        status: "dead_end",
      });
      console.log(`  [db] dead_end eval 入库 IC=${metrics.ic_mean ?? "null"} ICIR=${metrics.icir ?? "null"}`);

      // 三件套兜底 + emb（dead_end 因子也入库，补全以便检索/避雷）
      factorDb.ensureFormulaTags(written, factor.formula, factor.tags);
      let anchorOk = false;
      try { anchorOk = (await factorDb.generateAnchorText(written)).ok; }
      catch (e) { console.error(`  [db] anchor 生成失败(降级不阻塞): ${e.message}`); }
      let embOk = false;
      try { embOk = (await factorDb.generateEmbedding(written)).ok; }
      catch (e) { console.error(`  [db] emb 生成失败(降级不阻塞): ${e.message}`); }
      console.log(`  [db] formula/tags 兜底完成; emb=${embOk ? "OK" : "SKIP/FAIL"}`);

      const lessonText = buildDeadEndLessonText(factor, verdict, evalMetrics);
      const lessonId = factorDb.addLesson("dead_end", lessonText, {
        xname: written,
        ideaId,
        evidence: {
          xname: written,
          icir: metrics.icir,
          ic_mean: metrics.ic_mean,
          decision_breakdown: evalMetrics?.factor_level,
          weaknesses: verdict.key_weaknesses || [],
          suggested_iteration: verdict.suggested_iteration || null,
        },
      });
      console.log(`  [db] dead_end lesson 入库 id=${lessonId} (xname=${written}, status=dead_end)`);

      // 假设级支持度聚合（贝叶斯平滑，因子二元 verdict → 假设连续分数）
      if (ideaId != null) {
        const agg = factorDb.updateIdeaSupportScore(ideaId);
        console.log(`  [db] 假设 ${ideaId} 支持度: pass=${agg.pass}/${agg.total} score=${agg.score?.toFixed(3) ?? "null"}`);
      }

      return { xname: written, status: "dead_end", metrics, lessonId };
    }
  } catch (e) {
    console.error(`  [db] persistVerdict 失败 (不阻塞主流程): ${e.message}`);
    return { ok: false, error: `persistVerdict 异常: ${e.message}` };
  }
}

function buildSuccessLessonText(factor, verdict, evalMetrics) {
  const f = evalMetrics?.factor_level || {};
  const deep = evalMetrics?.deep_best || {};
  const strengths = (verdict.key_strengths || []).join("; ");
  return [
    `[success_pattern] ${factor.name}`,
    `假设: ${factor.hypothesis?.slice(0, 200) || "(无)"}`,
    `X-Y 对: ${f.n_pairs || "?"} 个 (keep=${f.keep || 0}, watch=${f.watch || 0}, reject=${f.reject || 0})`,
    `最佳 score=${f.best_score || "?"} pair=${f.best_pair || "?"}`,
    `deep: conditional_sharpe=${deep.conditional_sharpe ?? "?"} cum_ret=${deep.cum_ret_pct ?? "?"}% monthly_icir=${deep.monthly_icir ?? "?"}`,
    `强项: ${strengths}`,
  ].join("\n");
}

function buildDeadEndLessonText(factor, verdict, evalMetrics) {
  const f = evalMetrics?.factor_level || {};
  const deep = evalMetrics?.deep_best || {};
  const reasons = evalMetrics?.failure_reasons || {};
  const topReasons = Object.entries(reasons).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${k}(${v})`).join(", ");
  const weaknesses = (verdict.key_weaknesses || []).join("; ");
  return [
    `[dead_end] ${factor.name}`,
    `假设: ${factor.hypothesis?.slice(0, 200) || "(无)"}`,
    `X-Y 对: ${f.n_pairs || "?"} 个 (keep=${f.keep || 0}, watch=${f.watch || 0}, reject=${f.reject || 0})`,
    `deep: conditional_sharpe=${deep.conditional_sharpe ?? "?"} monthly_icir=${deep.monthly_icir ?? "?"}`,
    `主要失败原因: ${topReasons || "(无)"}`,
    `弱项: ${weaknesses}`,
    `建议迭代: ${verdict.suggested_iteration || "(无)"}`,
  ].join("\n");
}
