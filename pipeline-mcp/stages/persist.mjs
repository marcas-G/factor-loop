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
    rank_ic: fromScreening.spearman ?? fromDeep.rank_ic_max ?? null,
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

    // === 早期否决(不依赖入库数据,写库前判,省一次写) ===
    // 第4红线:|screening.icir|<0.5 且无变换族救场 → fail(防 LLM 失稳放弱信号)
    if (isPass && Math.abs(metrics.icir ?? 0) < 0.5) {
      const tf = evalMetrics?.transform_family || {};
      const hasRescue = Object.values(tf).some((v) => Math.abs(Number(v)) >= 0.05);
      if (!hasRescue) {
        verdict.verdict = "fail";
        (verdict.key_weaknesses ||= []).push("代码兜底:|screening.icir|<0.5 且无变换族救场(某变换|IC|≥0.05),第4红线否决");
        console.log(`  [db] 第4红线代码兜底: |ICIR|=${Math.abs(metrics.icir).toFixed(2)}<0.5,pass→fail`);
      }
    }
    // deepbest 全 None → 评估不全(第二/三维缺),ICIR<3 则 fail
    if (verdict.verdict === "pass") {
      const dbm = evalMetrics?.deep_best || {};
      const deepOk = Object.values(dbm).some((v) => v != null);
      if (!deepOk && Math.abs(metrics.icir ?? 0) < 3) {
        verdict.verdict = "fail";
        (verdict.key_weaknesses ||= []).push("代码兜底:deepbest 全 None(第二/三维数据缺)+ ICIR<3,评估不全硬否决");
        console.log(`  [db] 评估不全硬否决: deepbest None + ICIR=${metrics.icir}<3`);
      }
    }

    // === pass:先写 factor 拿 written,再做入库后冗余/残差检查 ===
    // 根因:冗余/残差检查依赖因子已入库的 IC 向量(icRefreshFactor 下载 dailyX 算 IC 序列),
    // 必须在 addFactorFromHFile 之后跑。原实现把检查放在写库前且引用未声明的 written,
    // ReferenceError 被 try-catch 吞 → 检查静默失效。现改为:写库→检查→必要时降级 status。
    let written = null;
    if (verdict.verdict === "pass") {
      written = factorDb.addFactorFromHFile(factorFile, ideaId, { status: "evaluated", intuition: factor.intuition || null });
      if (!written) {
        return { ok: false, error: `addFactorFromHFile 返回 null（frontmatter 解析失败或无 xname/class_name），factorFile=${factorFile}` };
      }
      factorDb.ensureFormulaTags(written, factor.formula, factor.tags);
      try { await factorDb.generateAnchorText(written); }
      catch (e) { console.error(`  [db] anchor 生成失败(降级不阻塞): ${e.message}`); }
      let embOk = false;
      try { embOk = (await factorDb.generateEmbedding(written)).ok; }
      catch (e) { console.error(`  [db] emb 生成失败(降级不阻塞): ${e.message}`); }
      console.log(`  [db] formula/tags 兜底完成; emb=${embOk ? "OK" : "SKIP/FAIL"}`);

      // 入库后冗余/残差检查(依赖 IC 数据,因子已入库,icRefresh 先算 IC 向量使新因子可被检索)
      try { await factorDb.icRefreshFactor(written); }
      catch (e) { console.error(`  [db] ic_refresh 失败(降级跳冗余检查): ${e.message}`); }
      // 冗余:max |pearson|>=0.7 → fail
      try {
        const corr = await factorDb.icCorrelateFactors(written, { k: 10, minAbsPearson: 0.7 });
        const topP = corr?.results?.[0];
        if (topP && Math.abs(topP.pearson_approx ?? 0) >= 0.7) {
          verdict.verdict = "fail";
          (verdict.key_weaknesses ||= []).push(`代码兜底:冗余 vs ${topP.factor} pearson=${topP.pearson_approx.toFixed(3)}>=0.7,硬否决`);
          console.log(`  [db] 冗余硬否决: vs ${topP.factor} p=${topP.pearson_approx.toFixed(3)}`);
        }
      } catch (e) { console.error(`  [db] ic_correlate 失败(降级): ${e.message}`); }
      // 残差:<0.4 → fail(零新息)
      try {
        const resid = await factorDb.residualIcStrength(written);
        const strengths = (resid?.scenes || []).map((s) => s.residual_ic_strength).filter((x) => x != null);
        if (strengths.length) {
          const minR = Math.min(...strengths);
          if (minR < 0.4) {
            verdict.verdict = "fail";
            (verdict.key_weaknesses ||= []).push(`代码兜底:残差 IC 强度=${minR.toFixed(3)}<0.4,零新息,硬否决`);
            console.log(`  [db] 残差硬否决: strength=${minR.toFixed(3)}`);
          }
        }
      } catch (e) { console.error(`  [db] residual 失败(降级): ${e.message}`); }

      // 入库后否决:已写的 evaluated factor 降级为 dead_end,后续走 dead_end eval/lesson
      if (verdict.verdict === "fail") {
        factorDb.updateFactorStatus(written, "dead_end");
        console.log(`  [db] 入库后否决: ${written} evaluated→dead_end`);
      }
    }

    if (verdict.verdict === "pass") {
      // pass:写 evaluated eval + success_pattern lesson + 假设支持度 + retry 迭代
      factorDb.addEval(written, ts, metrics, ideaId, checkResult.checkOutput, {
        evalMetrics: evalMetrics,
        conditionalReturns: evalMetrics?.deep_best || null,
        significant: 1,
        mode: "full",
        status: "evaluated",
      });
      console.log(`  [db] 因子 ${written} 入库 status=evaluated IC=${metrics.ic_mean ?? "null"} ICIR=${metrics.icir ?? "null"}`);

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
          // retry 路径 icir_delta 留空(原误传绝对 metrics.icir 当 delta 污染 iterations);
          // 真演进 delta 由主路径 realizeIteration(B.icir - A.icir)算
          factorDb.addIteration(
            fromXname, toXname, ideaId,
            retryInfo.changes,
            "improved",
            null
          );
          console.log(`  [db] 迭代关系 ${fromXname} → ${toXname} (${retryInfo.changes?.slice(0, 60)})`);
        }
      }
      return { xname: written, status: "evaluated", metrics, lessonId };
    } else {
      // fail/dead_end:lesson.factor_xname 有 FK → 必须先写 factors(status=dead_end)。
      // 早期否决时 written 还没写,这里补;入库后否决时 written 已是 dead_end(上面降级改过),跳过重写。
      if (!written) {
        written = factorDb.addFactorFromHFile(factorFile, ideaId, { status: "dead_end", intuition: factor.intuition || null });
        if (!written) {
          return { ok: false, error: `addFactorFromHFile 返回 null（frontmatter 解析失败或无 xname/class_name），factorFile=${factorFile}` };
        }
        factorDb.ensureFormulaTags(written, factor.formula, factor.tags);
        try { await factorDb.generateAnchorText(written); }
        catch (e) { console.error(`  [db] anchor 生成失败(降级不阻塞): ${e.message}`); }
        let embOk = false;
        try { embOk = (await factorDb.generateEmbedding(written)).ok; }
        catch (e) { console.error(`  [db] emb 生成失败(降级不阻塞): ${e.message}`); }
        console.log(`  [db] formula/tags 兜底完成; emb=${embOk ? "OK" : "SKIP/FAIL"}`);
      }
      // 写 factor_evals（带 status="dead_end" 触发 latest_ic/icir 更新）+ dead_end lesson
      factorDb.addEval(written, ts, metrics, ideaId, checkResult.checkOutput, {
        evalMetrics: evalMetrics,
        conditionalReturns: evalMetrics?.deep_best || null,
        significant: 0,
        mode: "full",
        status: "dead_end",
      });
      console.log(`  [db] dead_end eval 入库 IC=${metrics.ic_mean ?? "null"} ICIR=${metrics.icir ?? "null"}`);

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
