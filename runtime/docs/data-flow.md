# Quant Pipeline 数据流图

完整数据流：触发 → state 演进 → MCP 工具 I/O → evidence → DB 落库。

- **state**：`~/.quant-runs/<run_id>/state.json`
- **DB**：`~/work/quant/factors.db`
- **MCP server**：`pipeline-mcp/mcp/server.mjs`
- **触发**：`/research-loop <run_id?>`

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          QUANT PIPELINE · 完整数据流图                                    │
│   触发: /research-loop <run_id?>    state: ~/.quant-runs/<run_id>/state.json             │
│   DB:   ~/work/quant/factors.db     MCP: pipeline-mcp/mcp/server.mjs                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘

【Step 0】run_init {idea?, factors?} ──► {run_id}
         state := { version, run_id, run_dir, status:"running", idea, idea_id:null,
                    parent_session, started_at, factors:[], finished_at:null }

         ┌─────────────────────────── state.factors[i] 演进(贯穿全程) ───────────────────────────┐
         │ name formula hypothesis categories coordinates │ factor_file │ status            │
         │   (brainstorm 写入)                          │ (write)    │ pending→submitting│
         │                                              │            │ →done/failed      │
         │ failure_layer │ retry_trace │ last_rewrite │ evidence ★ │ verdict │ persisted │
         │  (check)      │  (重试)     │ (质量重试)   │ (check内部) │(evaluate)│(evaluate)│
         └───────────────────────────────────────────────────────────────────────────────────┘

【Step 1】brainstorm skill
   摸底 │ factor_counts{}          → {factors, lessons, evaluated}
        │ factor_list{k:20}        → [{xname, status, latest_icir, formula_text}]
        │ factor_recent_lessons{k} → [{id, type, text, factor_xname}]
   检索 │ factor_semantic_search{query_text, k} → [{xname, distance, status, latest_icir}]  ★向量首选
        │ factor_search{query, k}             → [{id, type, text, bm25}]                  ★FTS5补充
        │ factor_detail{xname}                → {factor, evals, tags, ancestors, descendants}
        │ factor_similar{xname, k}            → [{xname, distance}]   (查重,需已入库xname)
   产出 │ persist_idea{text} ──────────────────────► [ideas 表: id, text]
        │ run_save{idea, idea_id, factors:[N候选]}   每候选含 name/formula/hypothesis/categories
              │
              ▼
【Step 2】run-factor-agent × N (并发3, 每因子独立context)
   ┌─[write]─ Skill write-factor{formula,intuition,categories} → /factors/<name>.h
   │          run_save{ factors.i.status:"submitting", factors.i.factor_file }
   │
   ├─[submit] submit_factor{ xname, factorFile, categories:[CU,AL,NI], params }
   │            → { ok, features, error?, raw?, attempts }                    ──► 量化平台(--feeds)
   │            ok=false → error分类: 编译错→useLLM重write | 超时→重submit | 鉴权→give_up
   │
   ├─[check] check_factor{ xname, submitRef:{ok,features}, checkOutput, run_id, factor_index }
   │            → 返回 { failureLayer, summary }   ★返回值不含 evidence
   │            ★ 内部 run_save{ factors.i.failure_layer, factors.i.evidence } (不经agent手,保真)
   │            │
   │            │  evidence 按 failureLayer:
   │            │   check_done          → { reason, daily_ic_preview, eval_metrics, stdout_tail }
   │            │   check_output_too_small→ { reason, daily_ic_size, stdout_tail, stderr_tail, dir_listing,
   │            │                          airflow_*, diagnosis:{ nature, root_cause_candidates[], fix_hint } }
   │            │   check_failed         → { reason, exit_code, stdout_tail, stderr_tail,
   │            │                          airflow_*, diagnosis:{ nature, root_cause_candidates[], fix_hint } }
   │            │   platform_timeout/failed → { reason, stdout_tail, stderr_tail, airflow_* }   (transient)
   │            │
   │            ├─ check_done           → 跳最终态
   │            ├─ platform_timeout     → 重 check   (budget-=1)
   │            ├─ check_output_missing → 重 submit  (transient)
   │            └─ too_small / check_failed → 质量重试 (quality_budget=3 独立):
   │                  run_load 读 factors.i.evidence.diagnosis
   │                  ├─ fix_hint 含"不可救" / quality_budget≤0 → give_up
   │                  └─ else → Skill write-factor{ 现有.h路径, diagnosis.nature/candidates/fix_hint }
   │                              → 改 .h → 回 [submit] 重跑   (记 last_rewrite)
   │
   └─[最终态] run_save{ factors.i.status:"done|failed", failure_layer, retry_trace, last_rewrite }
              (evidence 不写—已落盘)        return 主会话: { xname, failure_layer }
              │
              ▼
【Step 3】evaluate skill  (仅筛选 failure_layer==check_done 的, 串行)
   run_load 读 factors.i.evidence.eval_metrics
   LLM 推理 → verdict { xname, verdict:"pass|fail", key_strengths[], key_weaknesses[], suggested_iteration }
   persist_factor{ run_id, factor_index, verdict }            ★3参数,内部组装
       │  内部 runLoad → { factor, factorFile, checkResult:evidence, retryInfo:last_rewrite, ideaId }
       ▼
       persistVerdict:
        ├─ verdict=pass → addFactorFromHFile(status=evaluated)
        │                 addEval{ ic_mean, icir, sharpe, rank_ic, eval_metrics, conditional_returns, significant:1 }
        │                 addLesson(type=success_pattern, evidence)
        │                 (retry改码成功 → addIteration from→to)
        │   return { xname, status:"evaluated", metrics:{ic_mean,icir,sharpe,rank_ic}, lessonId }
        └─ verdict=fail  → addFactorFromHFile(status=dead_end)
                           addEval{ ..., significant:0 }
                           addLesson(type=dead_end, evidence, suggested_iteration)
              return { xname, status:"dead_end", metrics, lessonId }
              (失败: return { ok:false, error } )
   run_save{ factors.i.verdict, factors.i.persisted }
              │
              ▼
【Step 4】run_save{ status:"done", finished_at:ISO }  +  报告{run_id, N因子failure_layer分布, verdict分布}

═══════════════════════════════════════════════════════════════════════════════
【数据库 factors.db 落库结构】

  ideas ──┐
 (id,text)│ idea_factor_links
          │  (idea_id, factor_xname)
          ▼
  factors ─────────┬─ factor_evals (factor_xname FK, idea_id, ts, ic_mean, icir, sharpe,
 (xname,           │                 rank_ic, eval_metrics JSON, conditional_returns JSON,
  class_name,      │                 eval_mode, significant, raw_path)
  file_path,       ├─ lessons (id, type:dead_end|success_pattern, scope:factor, text,
  formula_text,    │          evidence JSON, idea_id, factor_xname FK, created_ts)
  params,          ├─ factors_vec (xname, embedding: 512维 blob)   ← bge-small-zh-v1.5
  status,          ├─ iterations (from_xname, to_xname, idea_id, changes, status, icir)
  latest_ic,       └─ tags / factor_tags (name, factor_xname, tag_id)
  latest_icir,
  sharpe,
  created_ts)

═══════════════════════════════════════════════════════════════════════════════
【关键架构约束】
  ① check_factor 内部 run_save 完整 evidence → 返回只 {failureLayer,summary}
     (根治 agent LLM 二次加工丢字段: stdout_tail被清空/字段被重命名)
  ② persist_factor {run_id,factor_index,verdict} → 内部 runLoad 组装 (避免agent传复杂对象)
  ③ 质量失败带 diagnosis → agent quality_budget=3 跑 write-factor 改.h 重submit (非裸give_up)
  ④ semantic_search(CPU torch) 首选, factor_search(FTS5) 补充
```
