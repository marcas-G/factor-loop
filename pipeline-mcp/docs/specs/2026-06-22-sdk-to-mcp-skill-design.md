# 设计：把 sdk-demo 从 claude-agent-sdk 改造为 MCP + Skill + Task 子代理

**日期**：2026-06-22
**状态**：已评审，待转入实施计划

---

## 1. 背景与动机

现有 `sdk-demo` 量化因子研究 pipeline 通过 `@anthropic-ai/claude-agent-sdk` 的 `query()` 调用 Claude opus 跑三阶段循环（brainstorm → runFactor × N → evaluate）。痛点：

- **额度受限**：SDK 走 API 计费，opus 的 token 消耗在完整循环下极易触发 429/529，retry 也救不回来
- **订阅额度未用**：用户已订阅 Claude Code（Pro/Max），会话内调用走订阅额度，与 API 额度互不冲突
- **AI 与代码边界模糊**：SDK 模式下 Claude 通过 `allowedTools: ["Bash","Read","Write","Edit","Glob","Grep"]` 自由操作文件系统和平台脚本，缺少接口边界

**目标**：把 pipeline 的工作挪到 Claude Code 会话里跑（走订阅额度），同时把所有非 LLM 必须的搬砖操作封装成 MCP 工具，让 AI 严格通过接口操作，并为未来无人值守的自动化留好入口。

## 2. 关键约束（来自需求澄清）

1. **受限类型**：仅 opus 额度/计费受限，不是代理不支持 SDK 路径
2. **AI 不碰代码原则**：除了 write-factor skill 本身（写因子 `.h` 是 LLM 必须做的核心任务），其它所有操作（DB 查询、平台调用、状态管理、写库）都封装为 MCP 工具
3. **write-factor skill 复用**：现有 `/home/lgao/work/quant/.claude/skills/write-factor/SKILL.md` 保持原样，继续用 Claude Code 内置 `Write/Edit` 工具写因子文件
4. **自动化空间**：会话内一键跑 + 会话外调度触发（cron/systemd）都要支持
5. **并发**：Step 2 多个 factor 保持 `SUBMIT_CONCURRENCY=3` 并发
6. **错误处理**：MCP 工具连续失败时 skill 暂停 run 并报告给人（会话内场景人在环里）

## 3. 整体架构

```
┌────────────────────────────────────────────────────────────────┐
│                  Host（两种入口，同一套逻辑）                    │
│  ┌───────────────────┐        ┌──────────────────────┐         │
│  │ Claude Code 会话  │        │ claude --print -p    │         │
│  │ (/research-loop)  │        │ (cron/脚本触发)      │         │
│  └─────────┬─────────┘        └──────────┬───────────┘         │
└────────────┼─────────────────────────────┼────────────────────┘
             ▼                             ▼
   ┌──────────────────────────────────────────────────┐
   │  Skill: research-loop  (编排器)                  │
   │  - 加载 idea/state                                │
   │  - 顺序: brainstorm → run×N → evaluate            │
   └────┬─────────────┬───────────────────┬───────────┘
        ▼             ▼                   ▼
  ┌──────────┐  ┌──────────────────┐  ┌──────────┐
  │brainstorm│  │  Task 子代理      │  │ evaluate │
  │ skill    │  │  (per factor,    │  │ skill    │
  │ (主会话) │  │   替代 fork)      │  │ (主会话) │
  └────┬─────┘  │  ┌────────────┐  │  └────┬─────┘
       │        │  │write-factor│  │       │
       │        │  │skill(已存在)│  │       │
       │        │  └────────────┘  │       │
       │        └────────┬─────────┘       │
       │                 │                 │
       ▼                 ▼                 ▼
  ┌──────────────────────────────────────────────────┐
  │           quant-mcp MCP server                    │
  │  ┌────────┬─────────┬────────┬────────┬────────┐ │
  │  │factor- │ submit  │ check  │ state  │persist │ │
  │  │cli     │ factor  │ factor │ load/  │verdict │ │
  │  │(查询)  │(平台)   │(平台)  │ save   │(写库)  │ │
  │  └────────┴─────────┴────────┴────────┴────────┘ │
  └──────────────────────────────────────────────────┘
                        │
                        ▼
   factors.db / state.json / factors/*.h / 平台
```

**三套承载形式**：
- **MCP server**：封装所有搬砖原子能力（DB 查询、平台调用、状态、写库）
- **Skill**：承载 LLM 推理 + 编排逻辑（research-loop 编排器、复用已有 write-factor）
- **Task 子代理**：每个 factor 一个独立 context 跑 write→submit→check→rewrite 状态机，替代 SDK 的 `forkSession`

**Session 模型**：
- 主会话 = 父 session：brainstorm 和 evaluate 都在主会话跑，上下文自然延续
- Task 子代理 = fork：每个 factor 的 runFactor 在子代理跑，独立上下文

## 4. MCP server 工具清单

共 15 个工具，分 5 组。所有工具无状态（除 state 组，外部化到 state.json）。

### 组 1: factor-db 查询（替代 factor-cli.mjs）

| 工具 | 入参 | 出参 | 对应现有代码 |
|---|---|---|---|
| `factor_search` | `{query: string, k?: number=5}` | `Lesson[]` | `factor-cli search` |
| `factor_recent_lessons` | `{k?: number=10}` | `Lesson[]` | `factor-cli recent` |
| `factor_list` | `{k?: number=20}` | `Factor[]` | `factor-cli factors` |
| `factor_detail` | `{xname: string}` | `{factor, evals[], tags[], ancestors[], descendants[]}` | `factor-cli factor` |
| `factor_similar` | `{xname: string, k?: number=10}` | `Factor[]` | `factor-cli similar` |
| `factor_counts` | `{}` | `{factors, lessons, evaluated}` | `factor-cli count` |

### 组 2: 因子文件管理

**砍掉**。write-factor skill 继续用 Claude Code 内置 `Write/Edit` 直接操作 `.h` 文件。

### 组 3: 平台调用（替代 submit.mjs / check.mjs 的 programmatic 入口）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `submit_factor` | `{xname, categories, params}` | `{ok, features, error}` | 调 featuretool.py submit |
| `check_factor` | `{xname, submitRef}` | `{failureLayer, summary, evidence, dailyIcPath}` | 调 factor_check.py + 抓 evidence |

### 组 4: 状态机（替代 lib/state.mjs）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `run_init` | `{idea?, parentSession?}` | `{run_id}` | 建新 RUN_DIR + state.json |
| `run_load` | `{run_id}` | `state object` | 读 state |
| `run_save` | `{run_id, patch}` | `{ok}` | 原子写 state（merge patch） |
| `run_list` | `{}` | `[{run_id, idea, status, finished_at}]` | 列历史 run |

### 组 5: 写库（替代 persist.mjs）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `persist_idea` | `{text}` | `{id}` | 入 ideas 表 |
| `persist_factor` | `{factor, hypothesis, factor_file, checkResult, retryInfo, verdict, ideaId}` | `{xname, status}` | 聚合：pass → factors+evals+success_lesson；fail → dead_end lesson |

## 5. Skill / Task 子代理设计

### Skill: `research-loop`（编排器）

**位置**：`/home/lgao/work/quant/.claude/skills/research-loop/SKILL.md`

**触发**：`/research-loop <run_id?>` 或自然语言"跑一轮研究"

**工作流**：

```markdown
## Step 0 · 初始化
- 如未给 run_id：MCP run_init {} 建新 run
- 如给 run_id：MCP run_load {run_id} 恢复（断点续传）

## Step 1 · brainstorm（主会话直接跑）
- 读 .claude/PRINCIPLES.md + CONSTRAINTS.yaml
- MCP factor_counts 摸底
- 读 prompts/brainstorm.md（从原 stages/brainstorm.mjs 抽出的 prompt）
- 执行（含调 MCP factor_* 工具检索历史经验）
- 产出 {idea, factors[N]}
- MCP persist_idea {text: idea}
- MCP run_save {patch: {idea, factors, parent_session: <本会话id>}}

## Step 2 · 每个 factor 跑 runFactor（Task 子代理，并发 3）
对每批 3 个 factor（按 `SUBMIT_CONCURRENCY=3`）：
  - 主会话**在一个消息内同时发 3 个 Task tool call**（Claude Code 的 parallel tool use）
  - 每个 Task：subagent_type="run-factor-agent"，prompt={factor, idea, run_id}
  - 等待全部 3 个返回，收集 {xname, failure_layer, evidence, retry_trace}
  - 逐个 MCP run_save {patch: {factors[i]: result}}
下一批 3 个，直到所有 factor 跑完。

**注意**：`parent_session` 字段不显式传——Claude Code 没有暴露"拿当前会话 id"的 API。子代理的"父上下文"通过 prompt 字符串显式注入（brainstorm 阶段已检索的 DB 关键摘要）来模拟。

## Step 3 · evaluate（主会话直接跑，串行）
筛选 `failure_layer=check_done` 的因子（其它跳过，不参与评估）。
对每个 check_done 因子：
  - 从 state.json 读 `factors[i].evidence`（不重新调 check_factor）
  - 读 prompts/evaluate.md
  - 执行（输入 evidence.seven_dim_summary + hypothesis + idea）
  - 产出 verdict
  - MCP persist_factor {factor, verdict, checkResult, retryInfo, ideaId}
  - MCP run_save {patch: {factors[i].verdict, factors[i].persisted}}

## Step 4 · 汇总
- MCP run_save {patch: {status: "done", finished_at}}
- 报告：N 个因子，verdict 分布
```

### Task 子代理: `run-factor-agent`

**位置**：`/home/lgao/work/quant/.claude/agents/run-factor-agent.md`

**工具白名单**：`Skill, Read, Edit, Write, mcp__quant-mcp__*`（不给 Bash 防漫游）

**职责**：单个因子的 write → submit → check → rewrite 状态机（最多 3 次重试）

**状态机**（从原 stages/run-factor.mjs 搬过来）：

```
loop:
  - write 步：调 Skill write-factor（带 factor.formula/intuition）
  - submit 步：MCP submit_factor {xname, categories, params}
    - compile_error → rewrite（调 Skill write-factor 修，带 STL 清单）
    - auth_failed → give_up
    - transient → 重试 submit
  - check 步：MCP check_factor {xname, submitRef}
    - check_done → 返回成功
    - platform_failed/compile → rewrite
    - timeout → 重试 check
    - 其它 → give_up
```

**返回**：`{xname, failure_layer, success, evidence, retry_trace, last_rewrite}`

**输入**：`{factor, idea, run_id, parent_session}`

### 复用现有 skill

`/home/lgao/work/quant/.claude/skills/write-factor/SKILL.md` 保持原样，继续用 Claude Code 内置 Write/Edit 工具写因子文件。SDK 原来的 `skills: ["write-factor"]` 注入机制废弃，改为：Claude Code 会话内通过 Skill 工具显式触发。

### Prompt 抽取

原 `stages/brainstorm.mjs` 和 `stages/evaluate.mjs` 里写在代码字符串里的 prompt，抽成独立 markdown：

- `sdk-demo/prompts/brainstorm.md`
- `sdk-demo/prompts/evaluate.md`

Skill 和（第二期的）headless 入口都读这两个文件。好处：改 prompt 不用改代码；prompt 与代码解耦。

## 6. 数据流与状态

### 一次完整 run 的数据流

```
主会话: /research-loop
  │
  ├─ run_init {} → run_id=2026-06-22-abc123
  │
  ├─ [Step 1] brainstorm（主会话）
  │   ├─ factor_counts → {factors: 42, lessons: 18, evaluated: 12}
  │   ├─ factor_search "大单冲击" → [...]
  │   ├─ factor_detail "..." → {...}
  │   ├─ Claude 推理 → factors[]
  │   ├─ persist_idea → idea_id=88
  │   └─ run_save {patch: {idea, factors, parent_session}}
  │
  ├─ [Step 2] 并行 Task 子代理（concurrency=3）
  │   ├─ Task(run-factor-agent, Alpha1) → {...}
  │   ├─ Task(run-factor-agent, Alpha2) → {...}
  │   └─ Task(run-factor-agent, Alpha3) → {...}
  │   每个 run_save patch factors[i]
  │
  └─ [Step 3] evaluate（主会话，串行）
      ├─ evaluate[Alpha1]：读 evidence → Claude 推理 → verdict=pass
      │   └─ persist_factor → factors+evals+success_lesson
      ├─ evaluate[Alpha3]：读 evidence → verdict=fail
      │   └─ persist_factor → dead_end lesson
      └─ run_save {patch: {status: "done", finished_at}}
```

### state.json 结构

```json
{
  "run_id": "2026-06-22-abc123",
  "run_dir": "/tmp/research-run-...",
  "status": "running | done | failed | paused",
  "idea": "...",
  "idea_id": 88,
  "parent_session": "<claude code session id>",
  "factors": [
    {
      "name": "Alpha1",
      "formula": "...",
      "hypothesis": "...",
      "status": "writing | submitting | checking | done | failed",
      "factor_file": "/home/lgao/work/quant/factors/Alpha1.h",
      "failure_layer": "check_done | submit_failed | ...",
      "retry_trace": [{...}],
      "evidence": {...},
      "verdict": "pass | fail",
      "persisted": {...}
    }
  ],
  "finished_at": "..."
}
```

## 7. 错误处理

| 错误类型 | 处理策略 |
|---|---|
| 主会话中途被打断 | state.json 已记录到当前 step；下次 `/research-loop <run_id>` 自动续 |
| 子代理超时/崩溃 | Task 工具返回错误；主会话把这个 factor 标 `failure_layer=agent_crashed`，继续跑下一个 |
| MCP 工具调用连续失败 | **同一工具连续失败 3 次**，skill 暂停 run（status=paused），报告给人，等介入 |
| 平台 submit/check 5xx | MCP server 内部保留原 retry 逻辑（exponential backoff 10/30/60/120/300s，MAX_RETRY=5） |
| write-factor 反复 rewrite 修不好 | 子代理 budget=3 用完，标 failure_layer=give_up，返回主会话继续 |
| 断点续传时 factor 文件已存在 | skill 检测 status：done 跳过；writing/submitting **删除半成品 .h 文件后从 write 步重开**（避免 rewrite 写一半的损坏文件） |

**第一期 vs 第二期差异**：
- 第一期（会话内）：skill prompt 告诉 Claude 遇到异常就暂停问人
- 第二期（`--print`）：state.json status 严格，cron 脚本靠 status 决定 retry/skip/alert

## 8. 测试策略

### L1 · MCP 工具单元测试（第一期必做）

- 位置：`sdk-demo/mcp/tests/test_*.mjs`
- 每个工具一个测试文件
- 用临时 sqlite + 临时 RUN_DIR
- 重点：state_save/load 的原子性、persist_factor 的 verdict 分支、submit/check 的平台 mock

### L2 · Skill 烟雾测试（第一期必做）

- 手动 `/research-loop`，`BRAINSTORM_ONLY=1` 只到 Step 1
- 验证：state.json 写出、idea 入库、factor 列表合理
- 然后 `N_FACTORS=1` 走完整流程
- 形式：人肉跑，dump=1 / full=1 留证据

### L3 · 双 host 对比测试（第二期）

- 同一个 prompt 分别在会话内和 `claude --print -p` 跑
- 对比 state.json 结果差异
- 跑两次，`git diff state.json`

## 9. 实施分期

### 第一期：会话内一键跑（跑通完整循环）

估时图例：S = 半天以内，M = 1-2 天，L = 3 天以上

| # | 任务 | 估时 |
|---|---|---|
| 1 | 建 `sdk-demo/mcp/` 目录，init MCP server 骨架（Node.js + `@modelcontextprotocol/sdk`） | S |
| 2 | 实现组 1 工具（factor_*）— 包装 `factor-db.mjs` | S |
| 3 | 实现组 3 工具（submit_factor / check_factor）— 包装 `submit.mjs` / `check.mjs` | M |
| 4 | 实现组 4 工具（run_init/load/save/list）— 改造 `lib/state.mjs` | S |
| 5 | 实现组 5 工具（persist_idea / persist_factor）— 改造 `persist.mjs` | S |
| 6 | 抽 `prompts/brainstorm.md` + `prompts/evaluate.md` | S |
| 7 | 写 `research-loop` skill | S |
| 8 | 写 `run-factor-agent` 子代理 | S |
| 9 | 注册 MCP server 到 Claude Code settings | S |
| 10 | 写 L1 单元测试 | M |
| 11 | 跑 L2 烟雾测试 | M |

**第一期总估时**：约 7-10 个工作日（单人）。

### 第二期：外部调度（无人值守）

| # | 任务 |
|---|---|
| 12 | 写 `scripts/research-loop-headless.sh`：包装 `claude --print -p "/research-loop"` |
| 13 | 完善 state.json status 状态机（中间态持久化） |
| 14 | 加断点续传：headless 启动如遇 paused run 先问续不续 |
| 15 | 接入 cron / systemd timer |
| 16 | L3 对比测试 + 监控 |

## 10. 现有代码处置

| 文件 | 处置 | 说明 |
|---|---|---|
| `factor-db.mjs` | 保留 | MCP server 组 1 直接 import |
| `submit.mjs` / `check.mjs` | 保留 | MCP server 组 3 直接 import programmatic 入口 |
| `persist.mjs` | 保留 | MCP server 组 5 直接 import |
| `lib/state.mjs` | 改造 | 加 run_list 工具支持，改为可被 MCP server 调用 |
| `lib/config.mjs` / `_env.mjs` | 保留 | MCP server 启动时仍要加载 |
| `lib/llm.mjs` | 废弃 | 不再调 SDK |
| `stages/brainstorm.mjs` | 废弃 | prompt 抽到 prompts/，逻辑搬到 skill |
| `stages/run-factor.mjs` | 废弃 | 状态机搬到 run-factor-agent |
| `stages/evaluate.mjs` | 废弃 | prompt 抽到 prompts/，逻辑搬到 skill |
| `stages/write-factor.mjs` | 废弃 | 由 Claude Code 会话 + write-factor skill 替代 |
| `research-loop.mjs` | 废弃 | 主循环搬到 skill。**第一期不保留 SDK fallback**，第二期视需求再加 env flag 切换 |
| `factor-cli.mjs` | 废弃 | 由 MCP factor_* 工具替代。CLI 入口不再维护（如需诊断直接用 sqlite CLI） |

## 11. 核心收益

1. **不再吃 SDK 的 opus 额度**：走会话订阅，API 额度与订阅额度互不冲突
2. **AI 严格通过接口操作**：所有动作走 MCP 工具，可审计、可限流、可加 hook
3. **双 host 入口共用逻辑**：会话内 / 外部调度一套 skill + MCP，无需重写
4. **现有业务代码大量复用**：factor-db / submit / check / persist 原样保留，只换"调"的方式
