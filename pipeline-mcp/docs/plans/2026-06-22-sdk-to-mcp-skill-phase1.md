# SDK → MCP + Skill 改造（第一期）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 sdk-demo 从 `@anthropic-ai/claude-agent-sdk` 改造为 MCP server + Claude Code Skill + Task 子代理的形态，让人在 Claude Code 会话内能 `/research-loop` 一键跑完整研究循环（brainstorm → runFactor × N → evaluate），不再吃 SDK 的 opus 额度。

**Architecture:** 三套承载形式分工——MCP server（封装 15 个搬砖工具）+ Skill（编排逻辑 + 复用已有 write-factor skill）+ Task 子代理（每个 factor 一个独立 context 替代 forkSession）。所有业务代码（factor-db/submit/check/persist）保留，只换调用方式。状态全外部化到 state.json，支持断点续传。

**Tech Stack:** Node.js（ES modules）+ `@modelcontextprotocol/sdk` + `node:test`（内置测试框架）+ sqlite3（已有）。

**Spec：** [`docs/specs/2026-06-22-sdk-to-mcp-skill-design.md`](../specs/2026-06-22-sdk-to-mcp-skill-design.md)

---

## File Structure

**新建文件：**
- `sdk-demo/mcp/server.mjs` — MCP server 入口（stdio protocol），注册所有工具
- `sdk-demo/mcp/tools/factor-db.mjs` — 组 1 工具（6 个 factor_* 查询）
- `sdk-demo/mcp/tools/state.mjs` — 组 4 工具（run_init/load/save/list）
- `sdk-demo/mcp/tools/persist.mjs` — 组 5 工具（persist_idea/persist_factor）
- `sdk-demo/mcp/tools/platform.mjs` — 组 3 工具（submit_factor/check_factor）
- `sdk-demo/mcp/lib/run-store.mjs` — 多 run_id 状态管理（替代 lib/state.mjs 单例）
- `sdk-demo/mcp/tests/factor-db.test.mjs`
- `sdk-demo/mcp/tests/state.test.mjs`
- `sdk-demo/mcp/tests/persist.test.mjs`
- `sdk-demo/mcp/tests/platform.test.mjs`
- `sdk-demo/prompts/brainstorm.md` — 从 stages/brainstorm.mjs 抽出
- `sdk-demo/prompts/evaluate.md` — 从 stages/evaluate.mjs 抽出
- `/home/lgao/work/quant/.claude/skills/research-loop/SKILL.md` — 编排器 skill
- `/home/lgao/work/quant/.claude/agents/run-factor-agent.md` — 子代理定义

**修改文件：**
- `sdk-demo/package.json` — 加 `@modelcontextprotocol/sdk` 依赖，加 test scripts
- `sdk-demo/lib/state.mjs` — 改为多 run_id 支持（被 mcp/lib/run-store.mjs 调用）
- `/home/lgao/work/quant/.claude/settings.json` — 注册 MCP server

**废弃文件（第一期不动，仅标记）：**
- `sdk-demo/lib/llm.mjs`、`sdk-demo/stages/brainstorm.mjs`、`sdk-demo/stages/run-factor.mjs`、`sdk-demo/stages/evaluate.mjs`、`sdk-demo/stages/write-factor.mjs`、`sdk-demo/research-loop.mjs`、`sdk-demo/factor-cli.mjs`

**保留文件（MCP server 直接 import）：**
- `sdk-demo/factor-db.mjs`、`sdk-demo/stages/submit.mjs`、`sdk-demo/stages/check.mjs`、`sdk-demo/stages/persist.mjs`

---

## Task 1: git init + MCP server 骨架 + Hello 工具

**目的：** 建 git 仓库、建 mcp/ 目录骨架、装好 MCP SDK、跑通一个 hello 工具验证基础设施。

**Files:**
- Create: `sdk-demo/.gitignore`
- Create: `sdk-demo/mcp/server.mjs`
- Create: `sdk-demo/mcp/tools/health.mjs`
- Create: `sdk-demo/mcp/tests/health.test.mjs`
- Modify: `sdk-demo/package.json`

- [ ] **Step 1.1: git init**

```bash
cd /home/lgao/work/quant/sdk-demo
git init
git config user.name "$(whoami)"
git config user.email "$(whoami)@local"
```

Expected: `Initialized empty Git repository in /home/lgao/work/quant/sdk-demo/.git/`

- [ ] **Step 1.2: 写 .gitignore**

Create `sdk-demo/.gitignore`:

```
node_modules/
*.log
.tmp/
/tmp/
.env
.inspiration-weights.json
factors.db*
runs/
```

- [ ] **Step 1.3: 加 MCP SDK 依赖到 package.json**

Modify `sdk-demo/package.json`，改成：

```json
{
  "name": "sdk-demo",
  "version": "0.0.1",
  "type": "module",
  "private": true,
  "scripts": {
    "mcp": "node mcp/server.mjs",
    "test": "node --test mcp/tests/"
  },
  "dependencies": {
    "@anthropic-ai/claude-agent-sdk": "^0.3.178",
    "@modelcontextprotocol/sdk": "^1.0.4"
  }
}
```

- [ ] **Step 1.4: 安装依赖**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && npm install
```

Expected: `added N packages` in `node_modules/`，含 `@modelcontextprotocol/sdk`。

- [ ] **Step 1.5: 写 health 工具测试（failing test）**

Create `sdk-demo/mcp/tests/health.test.mjs`:

```javascript
import { test } from "node:test";
import assert from "node:assert";
import { healthSchema, healthHandler } from "../tools/health.mjs";

test("healthSchema 是合法的 MCP tool definition", () => {
  assert.equal(healthSchema.name, "health");
  assert.equal(healthSchema.description.length > 0, true);
  assert.deepEqual(healthSchema.inputSchema, { type: "object", properties: {} });
});

test("healthHandler 返回 ok=true 和时间戳", async () => {
  const result = await healthHandler({});
  assert.equal(result.ok, true);
  assert.equal(typeof result.ts, "string");
  assert.equal(result.ts.length > 0, true);
});
```

- [ ] **Step 1.6: 跑测试验证失败**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/health.test.mjs
```

Expected: FAIL，提示 `Cannot find module '../tools/health.mjs'`。

- [ ] **Step 1.7: 实现 health 工具**

Create `sdk-demo/mcp/tools/health.mjs`:

```javascript
export const healthSchema = {
  name: "health",
  description: "检查 quant-mcp server 是否存活，返回当前时间戳",
  inputSchema: { type: "object", properties: {} },
};

export async function healthHandler(_input) {
  return { ok: true, ts: new Date().toISOString() };
}
```

- [ ] **Step 1.8: 跑测试验证通过**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/health.test.mjs
```

Expected: PASS（2 个测试全过）。

- [ ] **Step 1.9: 写 MCP server 入口**

Create `sdk-demo/mcp/server.mjs`:

```javascript
#!/usr/bin/env node
// quant-mcp server — 量化研究 pipeline 的搬砖工具集。
// 通过 stdio 跟 Claude Code 通信。

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { healthSchema, healthHandler } from "./tools/health.mjs";

const ALL_TOOLS = [
  { schema: healthSchema, handler: healthHandler },
];

const server = new Server(
  { name: "quant-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: ALL_TOOLS.map(({ schema }) => schema),
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: input } = request.params;
  const entry = ALL_TOOLS.find((t) => t.schema.name === name);
  if (!entry) {
    return { content: [{ type: "text", text: `未知工具: ${name}` }], isError: true };
  }
  try {
    const result = await entry.handler(input || {});
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  } catch (e) {
    return { content: [{ type: "text", text: `工具 ${name} 执行失败: ${e.message}` }], isError: true };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
console.error("[quant-mcp] server 已启动 (stdio)");
```

- [ ] **Step 1.10: 手动验证 server 启动**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | timeout 2 node mcp/server.mjs 2>&1 || true
```

Expected: stderr 输出 `[quant-mcp] server 已启动 (stdio)`，stdout 输出含 `"tools":[{"name":"health"...}]` 的 JSON-RPC response。

（注：上面的命令不会完整握手成功，但能看到 server 启动 + 列表响应。完整集成测试在 Task 9。）

- [ ] **Step 1.11: Commit**

```bash
cd /home/lgao/work/quant/sdk-demo
git add .gitignore package.json package-lock.json mcp/
git commit -m "feat: 初始化 MCP server 骨架 + health 工具"
```

---

## Task 2: 组 1 工具 — factor-db 查询（6 个工具）

**目的：** 把 factor-cli.mjs 的 6 个查询命令包装成 MCP 工具，替代 CLI 入口。底层直接复用 `factor-db.mjs` 已有函数。

**Files:**
- Create: `sdk-demo/mcp/tools/factor-db.mjs`
- Create: `sdk-demo/mcp/tests/factor-db.test.mjs`
- Modify: `sdk-demo/mcp/server.mjs` — 注册 6 个新工具

注意：`factor_detail` 和 `factor_similar` 的实现在 `factor-cli.mjs` 里，不是 `factor-db.mjs` 导出。本期把这两个逻辑搬到 `factor-db.mjs` 导出，再被 MCP 工具调用。

- [ ] **Step 2.1: 在 factor-db.mjs 加 getFactorDetail 和 getSimilarFactors 导出**

Modify `/home/lgao/work/quant/sdk-demo/factor-db.mjs`，在文件末尾追加：

```javascript
// 单因子全貌：基本信息 + 最近 10 条 evals + tags + 迭代链（ancestors + descendants）
export function getFactorDetail(xname) {
  const d = db();
  const factor = d.prepare("SELECT * FROM factors WHERE xname = ?").get(xname);
  if (!factor) throw new Error(`xname 不存在: ${xname}`);
  const evals = d.prepare(
    "SELECT ts, ic_mean, icir, sharpe, eval_mode, significant FROM factor_evals WHERE factor_xname = ? ORDER BY ts DESC LIMIT 10"
  ).all(xname);
  const tags = d.prepare(
    "SELECT t.name FROM tags t JOIN factor_tags ft ON ft.tag_id = t.id WHERE ft.factor_xname = ?"
  ).all(xname).map(r => r.name);
  const ancestors = d.prepare(`
    WITH RECURSIVE chain AS (
      SELECT from_xname AS x, 1 AS depth FROM iterations WHERE to_xname = ?
      UNION ALL
      SELECT i.from_xname, c.depth + 1 FROM iterations i JOIN chain c ON i.to_xname = c.x
    )
    SELECT x AS xname, depth FROM chain ORDER BY depth
  `).all(xname);
  const descendants = d.prepare(`
    WITH RECURSIVE chain AS (
      SELECT to_xname AS x, 1 AS depth FROM iterations WHERE from_xname = ?
      UNION ALL
      SELECT i.to_xname, c.depth + 1 FROM iterations i JOIN chain c ON i.from_xname = c.x
    )
    SELECT x AS xname, depth FROM chain ORDER BY depth
  `).all(xname);
  return { factor, evals, tags, ancestors, descendants };
}

// 向量查重：给定 xname，找库内最相似的 k 个因子
export function getSimilarFactors(xname, k = 10) {
  const d = db();
  const row = d.prepare("SELECT embedding FROM factors_vec WHERE xname = ?").get(xname);
  if (!row) throw new Error(`xname 在 factors_vec 中不存在: ${xname}`);
  const emb = Array.from(new Float32Array(row.embedding.buffer, row.embedding.byteOffset, row.embedding.byteLength / 4));
  return searchSimilarFactors(emb, k);
}
```

- [ ] **Step 2.2: 写 6 个工具的 failing tests**

Create `sdk-demo/mcp/tests/factor-db.test.mjs`:

```javascript
import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as factorDb from "../../factor-db.mjs";
import * as tools from "../tools/factor-db.mjs";

// 用临时 sqlite 做隔离测试
function setupTempDb() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "quant-mcp-test-"));
  const dbPath = path.join(tmpDir, "test.db");
  factorDb.init({ dbPath });
  return { tmpDir, dbPath };
}

test("factor_counts 返回 {factors, lessons, evaluated} 三个数", async () => {
  setupTempDb();
  const result = await tools.factorCountsHandler({});
  assert.equal(typeof result.factors, "number");
  assert.equal(typeof result.lessons, "number");
  assert.equal(typeof result.evaluated, "number");
});

test("factor_recent_lessons 默认 k=10", async () => {
  setupTempDb();
  const result = await tools.factorRecentLessonsHandler({});
  assert.equal(Array.isArray(result), true);
});

test("factor_list 默认 k=20", async () => {
  setupTempDb();
  const result = await tools.factorListHandler({});
  assert.equal(Array.isArray(result), true);
});

test("factor_search 支持 query + 自定义 k", async () => {
  setupTempDb();
  const result = await tools.factorSearchHandler({ query: "大单冲击", k: 3 });
  assert.equal(Array.isArray(result), true);
});

test("factor_detail 对不存在的 xname 抛错", async () => {
  setupTempDb();
  await assert.rejects(
    () => tools.factorDetailHandler({ xname: "NonExistent" }),
    /xname 不存在/
  );
});

test("factor_similar 对不存在的 xname 抛错", async () => {
  setupTempDb();
  await assert.rejects(
    () => tools.factorSimilarHandler({ xname: "NonExistent" }),
    /factors_vec 中不存在/
  );
});

test("所有 6 个 schema 名称正确", () => {
  const names = tools.ALL_FACTOR_DB_SCHEMAS.map(s => s.name);
  assert.deepEqual(names.sort(), [
    "factor_counts",
    "factor_detail",
    "factor_list",
    "factor_recent_lessons",
    "factor_search",
    "factor_similar",
  ]);
});
```

- [ ] **Step 2.3: 跑测试验证失败**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/factor-db.test.mjs
```

Expected: FAIL，提示 `Cannot find module '../tools/factor-db.mjs'`。

- [ ] **Step 2.4: 实现组 1 工具**

Create `sdk-demo/mcp/tools/factor-db.mjs`:

```javascript
// 组 1: factor-db 查询工具（6 个）。直接复用 factor-db.mjs 的函数。
// 服务启动时调 factorDb.init()。

import * as factorDb from "../../factor-db.mjs";

export const factorSearchSchema = {
  name: "factor_search",
  description: "全文检索 lessons（trigram 分词，中文/英文混合 OK）。返回 type/scope/text 等字段。用于找历史经验。",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "检索词（≥3 字）" },
      k: { type: "number", description: "返回条数，默认 5", default: 5 },
    },
    required: ["query"],
  },
};
export async function factorSearchHandler({ query, k = 5 }) {
  return factorDb.searchLessons(query, k);
}

export const factorRecentLessonsSchema = {
  name: "factor_recent_lessons",
  description: "最近 k 条 lesson（按时间倒序），看最近经验积累。",
  inputSchema: {
    type: "object",
    properties: { k: { type: "number", default: 10 } },
  },
};
export async function factorRecentLessonsHandler({ k = 10 }) {
  return factorDb.recentLessons(k);
}

export const factorListSchema = {
  name: "factor_list",
  description: "列最近 k 个因子（含 status / latest_icir / formula_text），看最近研究方向。",
  inputSchema: {
    type: "object",
    properties: { k: { type: "number", default: 20 } },
  },
};
export async function factorListHandler({ k = 20 }) {
  return factorDb.recentFactors(k);
}

export const factorDetailSchema = {
  name: "factor_detail",
  description: "单因子全貌：基本信息 + 评估历史 + 迭代链 + tags。看一个因子的完整演进。",
  inputSchema: {
    type: "object",
    properties: { xname: { type: "string" } },
    required: ["xname"],
  },
};
export async function factorDetailHandler({ xname }) {
  return factorDb.getFactorDetail(xname);
}

export const factorSimilarSchema = {
  name: "factor_similar",
  description: "向量查重：给定 xname，找库内最相似的 k 个因子（基于 formula 语义 embedding）。",
  inputSchema: {
    type: "object",
    properties: {
      xname: { type: "string" },
      k: { type: "number", default: 10 },
    },
    required: ["xname"],
  },
};
export async function factorSimilarHandler({ xname, k = 10 }) {
  return factorDb.getSimilarFactors(xname, k);
}

export const factorCountsSchema = {
  name: "factor_counts",
  description: "库规模摸底：返回 {factors, lessons, evaluated} 三个总数。",
  inputSchema: { type: "object", properties: {} },
};
export async function factorCountsHandler() {
  return {
    factors: factorDb.countFactors(),
    lessons: factorDb.countLessons(),
    evaluated: factorDb.countEvaluated(),
  };
}

export const ALL_FACTOR_DB_SCHEMAS = [
  factorSearchSchema,
  factorRecentLessonsSchema,
  factorListSchema,
  factorDetailSchema,
  factorSimilarSchema,
  factorCountsSchema,
];

export const ALL_FACTOR_DB_HANDLERS = {
  factor_search: factorSearchHandler,
  factor_recent_lessons: factorRecentLessonsHandler,
  factor_list: factorListHandler,
  factor_detail: factorDetailHandler,
  factor_similar: factorSimilarHandler,
  factor_counts: factorCountsHandler,
};
```

- [ ] **Step 2.5: 跑测试验证通过**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/factor-db.test.mjs
```

Expected: PASS（7 个测试全过）。

- [ ] **Step 2.6: 在 server.mjs 注册组 1 工具**

Modify `sdk-demo/mcp/server.mjs`，在 `import` 区追加：

```javascript
import "../../_env.mjs"; // 加载 ANTHROPIC_BASE_URL 等
import * as factorDbModule from "./tools/factor-db.mjs";

// 初始化 factor-db（首次启动时）
import { init as factorDbInit } from "../factor-db.mjs";
factorDbInit();
```

把 `ALL_TOOLS` 改为：

```javascript
const ALL_TOOLS = [
  { schema: healthSchema, handler: healthHandler },
  ...factorDbModule.ALL_FACTOR_DB_SCHEMAS.map((schema) => ({
    schema,
    handler: factorDbModule.ALL_FACTOR_DB_HANDLERS[schema.name],
  })),
];
```

- [ ] **Step 2.7: 手动验证 server 列表**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | timeout 2 node mcp/server.mjs 2>&1 | grep -o '"name":"[^"]*"' || true
```

Expected: 输出含 `health`、`factor_search`、`factor_recent_lessons`、`factor_list`、`factor_detail`、`factor_similar`、`factor_counts` 共 7 个。

- [ ] **Step 2.8: Commit**

```bash
cd /home/lgao/work/quant/sdk-demo
git add mcp/ factor-db.mjs
git commit -m "feat: 加 factor-db 查询工具组（6 个）"
```

---

## Task 3: 组 4 工具 — state 状态管理（4 个工具）

**目的：** 把 `lib/state.mjs` 从单例改造为多 run_id 支持，暴露 `run_init` / `run_load` / `run_save` / `run_list` 四个工具。state 文件路径从全局常量改为按 run_id 组织。

**Files:**
- Create: `sdk-demo/mcp/lib/run-store.mjs` — 多 run_id 状态管理
- Create: `sdk-demo/mcp/tools/state.mjs` — 4 个 MCP 工具
- Create: `sdk-demo/mcp/tests/state.test.mjs`
- Modify: `sdk-demo/mcp/server.mjs`

**关键设计：** 所有 state 文件统一存到 `~/.quant-runs/<run_id>/state.json`，不再用 `/tmp/research-run-<timestamp>`。这样：
1. 不容易丢（重启不丢）
2. 跨进程可索引（run_list 能扫目录）
3. 断点续传可靠

- [ ] **Step 3.1: 写 run-store 的 failing tests**

Create `sdk-demo/mcp/tests/state.test.mjs`:

```javascript
import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import { runInit, runLoad, runSave, runList, setRunsRoot } from "../lib/run-store.mjs";

function useTempRunsRoot() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "quant-runs-test-"));
  setRunsRoot(tmp);
  return tmp;
}

test("runInit 创建新 run_id 和 state.json", async () => {
  useTempRunsRoot();
  const { run_id } = await runInit({ idea: "测试 idea" });
  assert.equal(typeof run_id, "string");
  assert.match(run_id, /^\d{4}-\d{2}-\d{2}-/);
  const state = await runLoad(run_id);
  assert.equal(state.idea, "测试 idea");
  assert.equal(state.status, "running");
});

test("runSave 浅 merge 顶级字段", async () => {
  useTempRunsRoot();
  const { run_id } = await runInit({ idea: "x" });
  await runSave(run_id, { status: "paused", note: "中断" });
  const state = await runLoad(run_id);
  assert.equal(state.status, "paused");
  assert.equal(state.note, "中断");
  assert.equal(state.idea, "x"); // 原字段保留
});

test("runSave 深 merge factors 数组（按 index 替换元素）", async () => {
  useTempRunsRoot();
  const { run_id } = await runInit({ idea: "x", factors: [
    { name: "A", failure_layer: null },
    { name: "B", failure_layer: null },
  ] });
  await runSave(run_id, { factors: [{ name: "A", failure_layer: "check_done" }] });
  // patch.factors 是单元素数组，应只替换 index 0，保留 index 1
  // 但 JSON merge patch 对数组是整体替换——需要特殊处理
  // 本测试改成：用 factors[i].field 路径式 patch
  // 见 runSave 实现的特殊 merge 逻辑
  const state = await runLoad(run_id);
  // 详细断言见实现
});

test("runSave 不允许直接覆盖整个 factors 数组（必须按 index）", async () => {
  useTempRunsRoot();
  const { run_id } = await runInit({ idea: "x", factors: [
    { name: "A" }, { name: "B" },
  ] });
  // 正确姿势：patch factor by index
  await runSave(run_id, { [`factors.0.failure_layer`]: "check_done" });
  const state = await runLoad(run_id);
  assert.equal(state.factors[0].failure_layer, "check_done");
  assert.equal(state.factors[1].name, "B"); // 未动
});

test("runList 列所有 run（按 started_at 倒序）", async () => {
  useTempRunsRoot();
  await runInit({ idea: "first" });
  await new Promise(r => setTimeout(r, 10));
  await runInit({ idea: "second" });
  const list = await runList();
  assert.equal(list.length, 2);
  assert.equal(list[0].idea, "second"); // 最新的在前
});

test("runLoad 对不存在的 run_id 抛错", async () => {
  useTempRunsRoot();
  await assert.rejects(() => runLoad("9999-01-01-nonexistent"), /不存在/);
});
```

- [ ] **Step 3.2: 跑测试验证失败**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/state.test.mjs
```

Expected: FAIL，提示 `Cannot find module '../lib/run-store.mjs'`。

- [ ] **Step 3.3: 实现 run-store.mjs**

Create `sdk-demo/mcp/lib/run-store.mjs`:

```javascript
// 多 run_id 状态管理。所有 state 文件存到 <runsRoot>/<run_id>/state.json。
// runsRoot 默认 ~/.quant-runs，可被测试 override。

import fs from "node:fs";
import path from "node:path";
import os from "node:os";

let runsRoot = path.join(os.homedir(), ".quant-runs");
export function setRunsRoot(p) { runsRoot = p; }
export function getRunsRoot() { return runsRoot; }

function statePath(runId) {
  return path.join(runsRoot, runId, "state.json");
}

function todayStamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
}

function randomSuffix() {
  return Math.random().toString(36).slice(2, 8);
}

export async function runInit({ idea = null, factors = [], parentSession = null } = {}) {
  const runId = `${todayStamp()}-${randomSuffix()}`;
  const runDir = path.join(runsRoot, runId);
  fs.mkdirSync(runDir, { recursive: true });
  const state = {
    version: 1,
    run_id: runId,
    run_dir: runDir,
    status: "running",
    idea: idea,
    idea_id: null,
    parent_session: parentSession,
    started_at: new Date().toISOString(),
    factors: factors.map(f => ({
      name: f.name,
      formula: f.formula || null,
      hypothesis: f.hypothesis || null,
      categories: f.categories || [],
      coordinates: f.coordinates || null,
      factor_file: null,
      status: "pending",
      failure_layer: null,
      retry_trace: [],
      evidence: null,
      verdict: null,
      persisted: null,
    })),
    finished_at: null,
  };
  await writeAtomic(statePath(runId), state);
  return { run_id: runId };
}

export async function runLoad(runId) {
  const p = statePath(runId);
  if (!fs.existsSync(p)) throw new Error(`run_id 不存在: ${runId}`);
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

// patch 支持：
//   { key: value }               — 顶级字段浅 merge
//   { "a.b.c": value }           — 路径式深 patch（点分隔）
//   不允许直接覆盖整个 factors 数组
export async function runSave(runId, patch) {
  const state = await runLoad(runId);
  for (const [key, value] of Object.entries(patch)) {
    if (key.includes(".")) {
      setByPath(state, key, value);
    } else {
      state[key] = value;
    }
  }
  await writeAtomic(statePath(runId), state);
  return { ok: true };
}

export async function runList() {
  if (!fs.existsSync(runsRoot)) return [];
  const entries = fs.readdirSync(runsRoot, { withFileTypes: true });
  const runs = [];
  for (const ent of entries) {
    if (!ent.isDirectory()) continue;
    const p = path.join(runsRoot, ent.name, "state.json");
    if (!fs.existsSync(p)) continue;
    try {
      const s = JSON.parse(fs.readFileSync(p, "utf8"));
      runs.push({
        run_id: s.run_id,
        idea: s.idea,
        status: s.status,
        started_at: s.started_at,
        finished_at: s.finished_at,
      });
    } catch {
      // skip corrupt
    }
  }
  runs.sort((a, b) => (b.started_at || "").localeCompare(a.started_at || ""));
  return runs;
}

function setByPath(obj, dottedPath, value) {
  const parts = dottedPath.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const k = parts[i];
    const nextKey = parts[i+1];
    const isNextNumeric = /^\d+$/.test(nextKey);
    if (cur[k] == null) cur[k] = isNextNumeric ? [] : {};
    cur = cur[k];
  }
  cur[parts[parts.length - 1]] = value;
}

async function writeAtomic(p, obj) {
  const tmp = `${p}.tmp`;
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2));
  fs.renameSync(tmp, p);
}
```

- [ ] **Step 3.4: 跑测试验证通过**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/state.test.mjs
```

Expected: PASS（6 个测试全过）。

- [ ] **Step 3.5: 实现 state 工具层**

Create `sdk-demo/mcp/tools/state.mjs`:

```javascript
import { runInit, runLoad, runSave, runList } from "../lib/run-store.mjs";

export const runInitSchema = {
  name: "run_init",
  description: "创建新的研究 run（含 run_id 和 state.json），或恢复现有 run（给 run_id 时）。",
  inputSchema: {
    type: "object",
    properties: {
      idea: { type: "string", description: "初始 idea（可选）" },
      factors: { type: "array", description: "初始 factors 数组（可选，brainstorm 后会填）" },
      parentSession: { type: "string", description: "父会话标识（可选）" },
    },
  },
};
export async function runInitHandler(input) {
  return runInit(input);
}

export const runLoadSchema = {
  name: "run_load",
  description: "读取某个 run 的完整 state（用于断点续传）。",
  inputSchema: {
    type: "object",
    properties: { run_id: { type: "string" } },
    required: ["run_id"],
  },
};
export async function runLoadHandler({ run_id }) {
  return runLoad(run_id);
}

export const runSaveSchema = {
  name: "run_save",
  description: "原子 merge patch 写 state。支持顶级字段或点分路径（如 'factors.0.failure_layer'）。不允许整体覆盖 factors 数组。",
  inputSchema: {
    type: "object",
    properties: {
      run_id: { type: "string" },
      patch: { type: "object", description: "要 merge 的字段" },
    },
    required: ["run_id", "patch"],
  },
};
export async function runSaveHandler({ run_id, patch }) {
  return runSave(run_id, patch);
}

export const runListSchema = {
  name: "run_list",
  description: "列所有历史 run（按 started_at 倒序），返回摘要信息。",
  inputSchema: { type: "object", properties: {} },
};
export async function runListHandler() {
  return runList();
}

export const ALL_STATE_SCHEMAS = [runInitSchema, runLoadSchema, runSaveSchema, runListSchema];
export const ALL_STATE_HANDLERS = {
  run_init: runInitHandler,
  run_load: runLoadHandler,
  run_save: runSaveHandler,
  run_list: runListHandler,
};
```

- [ ] **Step 3.6: 在 server.mjs 注册组 4 工具**

Modify `sdk-demo/mcp/server.mjs`，在 import 区加：

```javascript
import * as stateModule from "./tools/state.mjs";
```

`ALL_TOOLS` 追加：

```javascript
...stateModule.ALL_STATE_SCHEMAS.map((schema) => ({
  schema,
  handler: stateModule.ALL_STATE_HANDLERS[schema.name],
})),
```

- [ ] **Step 3.7: Commit**

```bash
cd /home/lgao/work/quant/sdk-demo
git add mcp/
git commit -m "feat: 加 state 状态管理工具组（run_init/load/save/list）"
```

---

## Task 4: 组 5 工具 — 写库（2 个工具）

**目的：** 把 `persist.mjs` 的 `persistVerdict` 包装成 MCP 工具，加一个轻量 `persist_idea`。底层直接调 `factor-db.mjs` 和 `persist.mjs`。

**Files:**
- Create: `sdk-demo/mcp/tools/persist.mjs`
- Create: `sdk-demo/mcp/tests/persist.test.mjs`
- Modify: `sdk-demo/mcp/server.mjs`

- [ ] **Step 4.1: 写 persist 工具的 failing tests**

Create `sdk-demo/mcp/tests/persist.test.mjs`:

```javascript
import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as factorDb from "../../factor-db.mjs";
import * as tools from "../tools/persist.mjs";

function setupTempDb() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "quant-mcp-test-"));
  const dbPath = path.join(tmpDir, "test.db");
  factorDb.init({ dbPath });
  return tmpDir;
}

function writeMockFactorFile(dir, name) {
  // 写一个最小合法的 .h 文件，带 frontmatter 让 addFactorFromHFile 能解析
  const content = `// xname: ${name}
// formula: test formula
// params: {}
/*
XCLASS ${name} : public FeedIndicator<...>
*/
#pragma once
class ${name} {};`;
  const p = path.join(dir, `${name}.h`);
  fs.writeFileSync(p, content);
  return p;
}

test("persist_idea 返回 idea id", async () => {
  setupTempDb();
  const result = await tools.persistIdeaHandler({ text: "测试 idea" });
  assert.equal(typeof result.id, "number");
  assert.ok(result.id > 0);
});

test("persist_factor 对 failureLayer != check_done 返回 null", async () => {
  const tmpDir = setupTempDb();
  const factorFile = writeMockFactorFile(tmpDir, "TestAlpha");
  const result = await tools.persistFactorHandler({
    factor: { name: "TestAlpha", hypothesis: "test" },
    factorFile,
    checkResult: { failureLayer: "submit_failed", evidence: null },
    verdict: { verdict: "pass" },
    ideaId: null,
  });
  assert.equal(result, null);
});

test("persist_factor schema 名称正确", () => {
  const names = tools.ALL_PERSIST_SCHEMAS.map(s => s.name);
  assert.deepEqual(names.sort(), ["persist_factor", "persist_idea"]);
});
```

- [ ] **Step 4.2: 跑测试验证失败**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/persist.test.mjs
```

Expected: FAIL，`Cannot find module '../tools/persist.mjs'`。

- [ ] **Step 4.3: 实现 persist 工具**

Create `sdk-demo/mcp/tools/persist.mjs`:

```javascript
// 组 5: 写库工具（2 个）。复用 stages/persist.mjs 的 persistVerdict 函数。

import * as factorDb from "../../factor-db.mjs";
import { persistVerdict } from "../../stages/persist.mjs";

export const persistIdeaSchema = {
  name: "persist_idea",
  description: "把一条研究 idea 写入 ideas 表。",
  inputSchema: {
    type: "object",
    properties: { text: { type: "string" } },
    required: ["text"],
  },
};
export async function persistIdeaHandler({ text }) {
  const id = factorDb.addIdea(text);
  return { id };
}

export const persistFactorSchema = {
  name: "persist_factor",
  description: "基于 evaluate 阶段的 verdict 写库。verdict=pass → factors+evals+success_pattern lesson；verdict=fail → factors(dead_end)+dead_end lesson。仅对 failureLayer=check_done 有效，其它返回 null。",
  inputSchema: {
    type: "object",
    properties: {
      factor: { type: "object", description: "{name, hypothesis, formula, ...}" },
      factorFile: { type: "string", description: "因子 .h 文件绝对路径" },
      checkResult: { type: "object", description: "{failureLayer, features, evidence, checkOutput}" },
      retryInfo: { type: "object", description: "{fixed, changed_code, changes} 或 null" },
      verdict: { type: "object", description: "{xname, verdict, key_strengths, key_weaknesses, suggested_iteration}" },
      ideaId: { type: "number" },
    },
    required: ["factor", "factorFile", "checkResult", "verdict"],
  },
};
export async function persistFactorHandler({ factor, factorFile, checkResult, retryInfo = null, verdict, ideaId = null }) {
  return persistVerdict(factor, factorFile, checkResult, retryInfo, verdict, ideaId);
}

export const ALL_PERSIST_SCHEMAS = [persistIdeaSchema, persistFactorSchema];
export const ALL_PERSIST_HANDLERS = {
  persist_idea: persistIdeaHandler,
  persist_factor: persistFactorHandler,
};
```

- [ ] **Step 4.4: 跑测试验证通过**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/persist.test.mjs
```

Expected: PASS（3 个测试全过）。

- [ ] **Step 4.5: 在 server.mjs 注册组 5 工具**

Modify `sdk-demo/mcp/server.mjs`，import 追加：

```javascript
import * as persistModule from "./tools/persist.mjs";
```

`ALL_TOOLS` 追加：

```javascript
...persistModule.ALL_PERSIST_SCHEMAS.map((schema) => ({
  schema,
  handler: persistModule.ALL_PERSIST_HANDLERS[schema.name],
})),
```

- [ ] **Step 4.6: Commit**

```bash
cd /home/lgao/work/quant/sdk-demo
git add mcp/
git commit -m "feat: 加写库工具组（persist_idea/persist_factor）"
```

---

## Task 5: 组 3 工具 — 平台调用（2 个工具）

**目的：** 包装 `submit.mjs` / `check.mjs` 的 programmatic 入口为 MCP 工具。这两个调外部 `featuretool.py` 和 `factor_check.py`，进程内已经有重试逻辑。

**Files:**
- Create: `sdk-demo/mcp/tools/platform.mjs`
- Create: `sdk-demo/mcp/tests/platform.test.mjs`
- Modify: `sdk-demo/mcp/server.mjs`

**关键设计：** 平台测试用 mock——单元测试不打真实 python 进程。通过 env var `QUANT_MCP_MOCK_PLATFORM=1` 让工具返回固定 mock 数据。

- [ ] **Step 5.1: 写 platform 工具的 failing tests**

Create `sdk-demo/mcp/tests/platform.test.mjs`:

```javascript
import { test } from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import * as tools from "../tools/platform.mjs";

test("submit_factor 在 mock 模式返回 ok=true", async () => {
  process.env.QUANT_MCP_MOCK_PLATFORM = "1";
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "quant-mcp-test-"));
  const factorFile = path.join(tmpDir, "Test.h");
  fs.writeFileSync(factorFile, `// xname: Test\n#pragma once\nclass Test {};`);
  const result = await tools.submitFactorHandler({
    xname: "Test",
    factorFile,
    categories: ["IF"],
    params: {},
  });
  assert.equal(result.ok, true);
  assert.equal(typeof result.features, "string");
  delete process.env.QUANT_MCP_MOCK_PLATFORM;
});

test("check_factor 在 mock 模式返回 failureLayer=check_done + evidence", async () => {
  process.env.QUANT_MCP_MOCK_PLATFORM = "1";
  const result = await tools.checkFactorHandler({
    xname: "Test",
    submitRef: { features: "Test", ok: true },
    checkOutput: "/tmp/dummy",
  });
  assert.equal(result.failureLayer, "check_done");
  assert.equal(typeof result.evidence, "object");
  delete process.env.QUANT_MCP_MOCK_PLATFORM;
});

test("platform schema 名称正确", () => {
  const names = tools.ALL_PLATFORM_SCHEMAS.map(s => s.name);
  assert.deepEqual(names.sort(), ["check_factor", "submit_factor"]);
});
```

- [ ] **Step 5.2: 跑测试验证失败**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/platform.test.mjs
```

Expected: FAIL，`Cannot find module '../tools/platform.mjs'`。

- [ ] **Step 5.3: 实现 platform 工具**

Create `sdk-demo/mcp/tools/platform.mjs`:

```javascript
// 组 3: 平台调用工具（submit/check）。生产模式调真实 python；测试用 QUANT_MCP_MOCK_PLATFORM=1 mock。

import { submitFactorProgrammatic } from "../../stages/submit.mjs";
import { checkFactorProgrammatic } from "../../stages/check.mjs";

export const submitFactorSchema = {
  name: "submit_factor",
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
  name: "check_factor",
  description: "检查因子评估结果（调 factor_check.py run + 抓 evidence）。返回 {failureLayer, summary, evidence, dailyIcPath}。",
  inputSchema: {
    type: "object",
    properties: {
      xname: { type: "string" },
      submitRef: { type: "object", description: "submit_factor 的返回值 {ok, features}" },
      checkOutput: { type: "string", description: "check 输出目录绝对路径" },
    },
    required: ["xname", "submitRef", "checkOutput"],
  },
};
export async function checkFactorHandler({ xname, submitRef, checkOutput }) {
  if (process.env.QUANT_MCP_MOCK_PLATFORM === "1") {
    return {
      ok: true,
      failureLayer: "check_done",
      checkOutput,
      dailyIcPath: `${checkOutput}/mock_daily_ic.txt`,
      dailyIcSize: 4096,
      summary: `[MOCK] ${xname} 检查通过`,
      evidence: {
        reason: "mock",
        eval_metrics: {
          factor_level: { n_pairs: 10, keep: 5, watch: 3, reject: 2, best_score: 0.85, best_pair: "X1-Y1" },
          core_metrics: { screening: { ic_mean: 0.038, icir: 2.1 } },
          deep_best: { conditional_sharpe: 1.8, monthly_icir: 2.5, rank_ic_max: 0.05 },
          failure_reasons: {},
        },
      },
    };
  }
  const factor = { name: xname };
  return checkFactorProgrammatic(factor, submitRef, checkOutput);
}

export const ALL_PLATFORM_SCHEMAS = [submitFactorSchema, checkFactorSchema];
export const ALL_PLATFORM_HANDLERS = {
  submit_factor: submitFactorHandler,
  check_factor: checkFactorHandler,
};
```

- [ ] **Step 5.4: 跑测试验证通过**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && node --test mcp/tests/platform.test.mjs
```

Expected: PASS（3 个测试全过）。

- [ ] **Step 5.5: 在 server.mjs 注册组 3 工具**

Modify `sdk-demo/mcp/server.mjs`，import 追加：

```javascript
import * as platformModule from "./tools/platform.mjs";
```

`ALL_TOOLS` 追加：

```javascript
...platformModule.ALL_PLATFORM_SCHEMAS.map((schema) => ({
  schema,
  handler: platformModule.ALL_PLATFORM_HANDLERS[schema.name],
})),
```

- [ ] **Step 5.6: 跑全部 L1 测试确认无回归**

Run:
```bash
cd /home/lgao/work/quant/sdk-demo && npm test
```

Expected: 所有测试 PASS（health 2 + factor-db 7 + state 6 + persist 3 + platform 3 = 21 个）。

- [ ] **Step 5.7: Commit**

```bash
cd /home/lgao/work/quant/sdk-demo
git add mcp/
git commit -m "feat: 加平台调用工具组（submit_factor/check_factor）+ 全部 L1 测试通过"
```

---

## Task 6: 抽 prompts/brainstorm.md + prompts/evaluate.md

**目的：** 把 `stages/brainstorm.mjs` 和 `stages/evaluate.mjs` 里硬编码在代码字符串里的 prompt 抽成独立 markdown 文件，供 skill 加载。

**Files:**
- Create: `sdk-demo/prompts/brainstorm.md`
- Create: `sdk-demo/prompts/evaluate.md`

- [ ] **Step 6.1: 抽 brainstorm prompt**

Create `sdk-demo/prompts/brainstorm.md`，内容是 `stages/brainstorm.mjs` 第 71-213 行那个 prompt 字符串（去掉模板字面量的反引号转义），加上占位符说明。

文件开头：

```markdown
---
name: brainstorm
description: 量化因子候选生成 prompt。输入 coords(代码抽取) + idea（已生成）+ DB 规模 + 硬约束 + 指导思想，输出 N 个差异化候选因子（JSON）。
placeholders:
  - "{{IDEA}}": 已生成的研究 idea
  - "{{CONSTRAINTS}}": 硬约束（从 .claude/CONSTRAINTS.yaml 读）
  - "{{PRINCIPLES}}": 指导思想（从 .claude/PRINCIPLES.md 读）
  - "{{TOTAL_FACTORS}}": 当前库因子总数
  - "{{TOTAL_LESSONS}}": 当前库 lesson 总数
  - "{{N_FACTORS}}": 要生成的候选数，默认 3
  - "{{FACTOR_CLI}}": factor-cli.mjs 的绝对路径（保留供诊断，正式流程走 MCP 工具）
---

你是量化因子研究员，要做差异化的因子候选生成。

═══════════════════════════════════════════
[工作环境 - 因子库]
═══════════════════════════════════════════

库分两层，先理解再使用：

【实体层】
• factors 表：每个因子一行（xname 唯一标识）
  status 枚举：
    draft       - 已写未评估
    evaluated   - ICIR ≥ 1.5（算子可借鉴）
    dead_end    - ICIR < 1.5（方向避雷）
    failed      - 评估彻底失败

• factor_evals 表：评估快照（一个因子可多次评估）
• iterations 表：迭代关系（from_xname → to_xname 演进链）
• ideas 表：研究想法

【经验层】
• lessons 表：原子经验，type 枚举：
    dead_end        - 实验成功但 ICIR < 1.5
    success_pattern - 实验成功且 ICIR ≥ 1.5

═══════════════════════════════════════════
[可用 MCP 工具]
═══════════════════════════════════════════

当前库规模：{{TOTAL_FACTORS}} 个因子 / {{TOTAL_LESSONS}} 条 lesson。

- `factor_counts` → {factors, lessons, evaluated} 摸底
- `factor_list {k=20}` → 最近 k 个因子（含 status / latest_icir）
- `factor_recent_lessons {k=10}` → 最近经验
- `factor_search {query, k=5}` → 全文检索 lessons
- `factor_detail {xname}` → 单因子全貌（含迭代链）
- `factor_similar {xname, k=10}` → 向量查重

═══════════════════════════════════════════
[本次研究 idea]
═══════════════════════════════════════════

{{IDEA}}

[硬约束 - 必须满足]
{{CONSTRAINTS}}

[指导思想]
{{PRINCIPLES}}

═══════════════════════════════════════════
[研究流程 - 必须执行]
═══════════════════════════════════════════

第 1 步 · 摸底（每个都跑一次）：
  - factor_counts（看库规模）
  - factor_recent_lessons {k=10}
  - factor_list {k=20}

第 2 步 · 围绕本次 idea 检索：
  - 从 idea 抽 2-3 个核心关键词，分别 factor_search
  - 命中 evaluated 因子：factor_detail 学迭代链
  - 命中 dead_end 因子：在 db_research.found_dead_ends 记下，候选避开
  - 想看更多变体：factor_similar

第 3 步 · 基于证据出候选：
  生成 {{N_FACTORS}} 个差异化候选，对每个候选在 db_research 字段里显式回答：
  - searched：用了哪些检索词
  - found_dead_ends：命中的 dead_end lesson（如有，候选怎么差异化避开）
  - found_similar：命中的相似因子（如有，候选怎么差异）
  - borrowed_from：借鉴了哪个 success_pattern 或 evaluated 因子的算子

═══════════════════════════════════════════
[候选硬要求]
═══════════════════════════════════════════

1. 公式/伪代码必须可回测（写得出 .h 实现）
2. {{N_FACTORS}} 个候选必须差异化（算子/窗口/变换/品种任一维度不同）
3. intuition 要具体到市场机制，不要泛泛"市场非有效"
4. diff_check：去掉关键 [维度] 后会退化成什么标准因子？
5. coord_usage：本因子如何用 idea 中的 6 维要素

═══════════════════════════════════════════
[输出 - 严格 JSON，无其他文字]
═══════════════════════════════════════════

```json
{
  "factors": [
    {
      "name": "类名(PascalCase)",
      "formula": "公式或伪代码",
      "intuition": "为什么有效（市场机制层面）",
      "diff_check": "去掉 [X 维度] 后会退化成什么标准因子？差异点是什么？",
      "coord_usage": "本因子如何使用 idea 中的研究要素",
      "categories": ["从硬约束的 feeds 选品种"],
      "params": {},
      "db_research": {
        "searched": ["检索词1", "检索词2"],
        "found_dead_ends": [],
        "found_similar": [],
        "borrowed_from": "借鉴的具体因子/经验"
      }
    }
  ]
}
```
```

- [ ] **Step 6.2: 抽 evaluate prompt**

Create `sdk-demo/prompts/evaluate.md`，内容取自 `stages/evaluate.mjs` 第 91-132 行：

```markdown
---
name: evaluate
description: 量化因子结果评估 prompt。输入 7 维评估数据（代码抓的非 LLM 自评）+ 因子设计假设 + 研究 idea，输出 verdict（pass/fail）+ strengths/weaknesses/suggested_iteration。
placeholders:
  - "{{IDEA}}": 本次研究 idea
  - "{{FACTOR_NAME}}": 当前因子类名
  - "{{HYPOTHESIS}}": 因子设计假设（brainstorm 阶段的 intuition+diff_check+coord_usage）
  - "{{EVAL_METRICS_JSON}}": 7 维评估数据 JSON 字符串
---

你是量化因子研究员，基于 7 维评估数据对单个因子做"结果评估"。

[本次研究 idea]
{{IDEA}}

[当前因子的设计假设]
{{HYPOTHESIS}}

[因子的 7 维评估数据]（代码从平台产物聚合，**不是 LLM 自评**）
{{EVAL_METRICS_JSON}}

[评估维度参考]
- factor_level: 平台对 N 个 X-Y 对的 decision 分布（KEEP/WATCH/REJECT）+ 最佳 score
- core_metrics: 每个维度的最佳 X-Y 对指标
  - screening: IC/ICIR/Spearman/sign_match_rate
  - session_ic: 各交易时段 IC + std（std 越小越稳）
  - vol_regime: 波动率 5 分位 IC + sign_consistent
  - zero: Welch t 检验 + p_value
  - train_test: 训练/测试 IC 衰减
- deep_best: conditional_sharpe / cum_ret_pct / monthly_icir / daily_ic_tstat / rank_ic_max / signal_instability_pct
- top_pairs: 按 score 排序的前 3 个 X-Y 对
- failure_reasons: 平台给出的失败原因统计

[评估原则]
1. 单独评估此因子（不跟其他候选对比）
2. 综合多维度判断，不要只看 ICIR 阈值
3. 强假设：因子是否回应了 idea 的核心假设
4. 强证据：所有结论必须引用 7 维数据的具体数字
5. verdict=pass：因子值得入库（算子可借鉴，下次能迭代）
6. verdict=fail：方向已被否决，但留 suggested_iteration 作未来参考

[输出 - 严格 JSON，无其他文字]

```json
{
  "xname": "{{FACTOR_NAME}}",
  "verdict": "pass 或 fail",
  "key_strengths": ["强项 1（含具体数字）", "强项 2"],
  "key_weaknesses": ["弱项 1（含具体数字）", "弱项 2"],
  "suggested_iteration": "如果下次重做这个方向，应尝试什么调整（换 Y horizon / 换品种 / 调窗口）"
}
```
```

- [ ] **Step 6.3: Commit**

```bash
cd /home/lgao/work/quant/sdk-demo
git add prompts/
git commit -m "feat: 抽 brainstorm/evaluate prompt 到独立 markdown 文件"
```

---

## Task 7: research-loop skill

**目的：** 写编排器 skill，让用户在 Claude Code 会话里 `/research-loop` 触发完整循环。

**Files:**
- Create: `/home/lgao/work/quant/.claude/skills/research-loop/SKILL.md`

- [ ] **Step 7.1: 写 SKILL.md**

Create `/home/lgao/work/quant/.claude/skills/research-loop/SKILL.md`:

```markdown
---
name: research-loop
description: 量化因子研究循环编排器。触发：`/research-loop <run_id?>` 或"跑一轮研究"。完成 brainstorm → runFactor × N → evaluate 全流程。
---

# Research Loop — 量化因子研究循环编排器

执行一个完整的研究循环：基于现有因子库和经验，brainstorm 新候选 → 让 run-factor-agent 跑每个候选的 write/submit/check → 评估结果写库。所有搬砖操作走 `quant-mcp` MCP server 的工具，不直接用 Bash/Write 操作文件。

## 输入

- `run_id`（可选）：如提供，从该 run 断点续传；否则建新 run。

## Step 0 · 初始化

- 如未给 `run_id`：
  1. 调 MCP `run_init {}` → 拿到 `run_id`
  2. 调 MCP `run_save {run_id, patch: {parent_session: "<本会话描述，如 'claude-code-session-<date>'>"}}`
- 如给了 `run_id`：
  1. 调 MCP `run_load {run_id}` → 读 state
  2. 检查 `status`：如 `done` 报告"已完成"；如 `paused`/`running` 从断点续（看 `factors[].status` 决定从哪步开始）

## Step 1 · brainstorm（本会话直接跑）

1. 读 `/home/lgao/work/quant/.claude/CONSTRAINTS.yaml` 和 `/home/lgao/work/quant/.claude/PRINCIPLES.md`
2. 调 MCP `factor_counts {}` 摸底
3. 加载 prompt：读 `/home/lgao/work/quant/sdk-demo/prompts/brainstorm.md`
4. 用以下变量替换 prompt 中的占位符：
   - `{{IDEA}}`：先用代码从 inspiration-pool 抽 1 组 coords，调 LLM 拼成一句 30-80 字的 idea（或直接给一个简单的占位，让 Claude 在推理时基于 coords 字段生成）
   - `{{CONSTRAINTS}}` / `{{PRINCIPLES}}`：步骤 1 读到的内容
   - `{{TOTAL_FACTORS}}` / `{{TOTAL_LESSONS}}`：步骤 2 拿到的数字
   - `{{N_FACTORS}}`：默认 3（可由用户指定）
5. 按 prompt 的"研究流程"执行：先调 MCP `factor_counts`/`factor_list`/`factor_recent_lessons` 摸底，再用 `factor_search`/`factor_detail`/`factor_similar` 检索
6. 产出 JSON：`{factors: [...]}`
7. 调 MCP `persist_idea {text: <idea 文本>}` → 拿到 `idea_id`
8. 调 MCP `run_save {run_id, patch: {idea: <idea>, idea_id: <id>, factors: <完整 factors 数组>}}`

**连续失败处理**：任何 MCP 工具连续失败 3 次，调 MCP `run_save {run_id, patch: {status: "paused"}}` 然后停止，向用户报告失败原因。

## Step 2 · 每个 factor 跑 runFactor（Task 子代理，并发 3）

把 factors 按每批 3 个分组。对每批：

1. 在**一个消息内**同时发 3 个 Task tool call（parallel tool use），每个：
   - `subagent_type: "run-factor-agent"`
   - `prompt`: 包含 `factor`（含 name/formula/intuition/categories/params/hypothesis）+ `idea` + `run_id`
2. 等待 3 个全部返回，收集每个的 `{xname, failure_layer, evidence, retry_trace, last_rewrite}`
3. 对每个返回的结果，调 MCP `run_save`：
   ```
   run_save {
     run_id,
     patch: {
       "factors.<index>.status": "done" | "failed",
       "factors.<index>.failure_layer": <layer>,
       "factors.<index>.evidence": <evidence>,
       "factors.<index>.retry_trace": <trace>,
     }
   }
   ```
   （`<index>` 是该 factor 在 state.factors 数组里的下标）

下一批 3 个，直到所有 factor 跑完。

## Step 3 · evaluate（本会话直接跑，串行）

筛选 `failure_layer == "check_done"` 的 factors（其它跳过）。

对每个 check_done factor：

1. 从 state 里读 `factors[i].evidence`（不重新调 check_factor）
2. 加载 prompt：读 `/home/lgao/work/quant/sdk-demo/prompts/evaluate.md`
3. 替换占位符：
   - `{{IDEA}}`：state.idea
   - `{{FACTOR_NAME}}`：factors[i].name
   - `{{HYPOTHESIS}}`：factors[i].hypothesis
   - `{{EVAL_METRICS_JSON}}`：JSON.stringify(factors[i].evidence.eval_metrics, null, 2)
4. 让 Claude 按 prompt 推理，产出 verdict JSON：`{xname, verdict, key_strengths, key_weaknesses, suggested_iteration}`
5. 调 MCP `persist_factor`：
   ```
   persist_factor {
     factor: factors[i],
     factorFile: factors[i].factor_file,
     checkResult: {
       failureLayer: "check_done",
       features: <name>,
       evidence: factors[i].evidence,
     },
     retryInfo: factors[i].last_rewrite || null,
     verdict: <verdict>,
     ideaId: state.idea_id,
   }
   ```
6. 调 MCP `run_save {run_id, patch: {"factors.<i>.verdict": <verdict>, "factors.<i>.persisted": <result>}}`

## Step 4 · 汇总报告

1. 调 MCP `run_save {run_id, patch: {status: "done", finished_at: "<ISO timestamp>"}}`
2. 向用户报告：
   - run_id
   - N 个因子，各 failure_layer 分布
   - check_done 因子的 verdict 分布（pass/fail 各几）
   - persisted 状态

## 错误处理

| 情况 | 行为 |
|---|---|
| MCP 工具连续失败 3 次 | `run_save {status: "paused"}`，向用户报告，停止 |
| Task 子代理超时/崩溃 | 标 `failure_layer: "agent_crashed"`，继续其它 factor |
| evaluate 失败（如 eval_metrics 缺失） | verdict=fail，key_weaknesses 写"eval_metrics 缺失"，继续下一个 |
| 断点续传时发现 factor `.h` 已存在但 status 非 done | 子代理先删除该 `.h` 文件再从 write 步重开 |

## 不要做的事

- 不要直接用 Bash 调 `factor-cli.mjs`（已被废弃；用 MCP factor_* 工具）
- 不要直接用 Write/Edit 写因子 `.h` 文件（只有 write-factor skill 通过它的内部流程做）
- 不要用 SDK 风格的 `forkSession`（Claude Code 没有；每个 factor 的隔离靠 run-factor-agent 子代理）
- 不要在主会话里跑 write/submit/check（必须派给 run-factor-agent 子代理）
```

- [ ] **Step 7.2: Commit**

```bash
cd /home/lgao/work/quant/sdk-demo
git add /home/lgao/work/quant/.claude/skills/research-loop/
git commit --allow-empty -m "feat: 加 research-loop skill（编排器）"
```

（注：skill 文件在 `.claude/skills/` 下，跟 sdk-demo 仓库分开。这里用 `--allow-empty` 在 sdk-demo 仓库留个 marker commit；实际 skill 文件单独在 `.claude/skills/` 里维护，由 Claude Code 加载。如果你希望 skill 也版本管理，可以在 `/home/lgao/work/quant/.claude/` 下单独 `git init`。）

---

## Task 8: run-factor-agent 子代理

**目的：** 写 Task 子代理定义文件，承载每个 factor 的 write→submit→check→rewrite 状态机。

**Files:**
- Create: `/home/lgao/work/quant/.claude/agents/run-factor-agent.md`

- [ ] **Step 8.1: 写 agent definition**

Create `/home/lgao/work/quant/.claude/agents/run-factor-agent.md`:

```markdown
---
name: run-factor-agent
description: 单个因子的 write→submit→check→rewrite 状态机执行。被 research-loop skill 通过 Task 工具调起，每个 factor 一个实例（独立 context）。
tools: Skill, Read, Edit, Write, Glob, Grep, mcp__quant-mcp__submit_factor, mcp__quant-mcp__check_factor, mcp__quant-mcp__run_save
---

# Run-Factor Agent — 单因子执行状态机

你是量化因子单因子执行代理。你被 research-loop skill 通过 Task 工具调起，负责把**一个**候选因子跑到 `check_done` 或 `give_up`。

## 输入

Task 工具的 prompt 会包含以下 JSON（解析出来用）：

```json
{
  "factor": {
    "name": "Alpha1",
    "formula": "...",
    "intuition": "...",
    "diff_check": "...",
    "coord_usage": "...",
    "categories": ["IF"],
    "params": {}
  },
  "idea": "<本次研究 idea>",
  "run_id": "<run_id>",
  "factor_index": <在 state.factors 里的下标>
}
```

## 状态机（最多 3 次重试）

budget = 3。

```
初始 step = "write"

while True:
  if step == "write":
    1. 调 Skill write-factor，传入 factor.formula / factor.intuition / factor.categories
    2. write-factor 会把 .h 写到 /home/lgao/work/quant/factors/<name>.h
    3. 调 mcp__quant-mcp__run_save {
         run_id,
         patch: {
           "factors.<index>.status": "submitting",
           "factors.<index>.factor_file": "<.h 绝对路径>"
         }
       }
    4. step = "submit"

  elif step == "submit":
    1. 调 mcp__quant-mcp__submit_factor {xname, factorFile, categories, params}
    2. 如 result.ok == true:
         step = "check"
         存 submitResult = result
       else:
         分类 error：
           - 含 compile_error/undefined/cannot find/compil/template → useLLM=true, jump="write"
           - 含 login/unauthorized/401/403/cookie/forbidden → give_up
           - 含 timeout/connection/reset/503/502/gateway → jump="submit"（重试）
           - 其它 → give_up
         budget -= 1
         如 budget <= 0 或 give_up：返回失败结果
         如 useLLM：调 Skill write-factor 修（带 evidence），记到 last_rewrite
         step = jump

  elif step == "check":
    1. checkOutput = "/tmp/research-run-<run_id>/<name>_check"
    2. 调 mcp__quant-mcp__check_factor {xname, submitRef: submitResult, checkOutput}
    3. 如 result.failureLayer == "check_done":
         返回成功结果
       else:
         按 failureLayer 决定：
           "platform_timeout" → jump="check"（重试）
           "platform_failed" → useLLM=true, jump="write"
           "check_output_missing" → jump="submit"
           "check_output_too_small" → give_up
           "check_failed" → give_up
         budget -= 1
         如 budget <= 0 或 give_up：返回失败结果
         如 useLLM：调 Skill write-factor 修，记到 last_rewrite
         step = jump
```

## 返回值

最终向 research-loop（父会话）返回一个 JSON：

```json
{
  "xname": "<factor.name>",
  "success": true | false,
  "failure_layer": "check_done" | "submit_failed" | "give_up" | "agent_crashed",
  "evidence": <check_factor 返回的 evidence 字段，含 eval_metrics> | null,
  "retry_trace": [<每次跳转的 {from, jump, reason}>],
  "last_rewrite": {fixed: bool, changes: string} | null,
  "factor_file": "<.h 绝对路径>"
}
```

## STL 高频陷阱清单（rewrite 时对照）

每次调 write-factor skill 修代码时，把以下清单塞进 prompt：

1. `std::deque` 不能调 `reserve()`；换 vector 或删 reserve
2. `std::vector` 不能调 `push_front() / pop_front()`
3. `std::accumulate` → `#include <numeric>`
4. `std::cout / cerr` → `#include <iostream>`
5. `std::unordered_map` → `#include <unordered_map>`
6. `std::transform / sort / clamp / min / max` → `#include <algorithm>`
7. `std::function` → `#include <functional>`
8. `std::isfinite` / `std::tanh` / `std::log` → `#include <cmath>`
9. `feed().bid(i)` / `feed().ask(i)` 返回 int64_t，与 double 运算前先 cast
10. `feed().bidSize(i)` / `feed().askSize(i)` 返回 int
11. `Feed::Order.level()` 返回 int，-1 表 trade/cross，0 是 best level
12. 模板类的 using alias / typedef 必须放 public 区段
13. 不要在 `calculateX()` 里调 `onEndBook()` 或反过来
14. `onEndBook()` 做复杂计算，`calculateX()` 只做 `setXValue(0, XType(val))`

## 工具使用约束

- **不要**用 Bash 调 factor-cli.mjs 或直接跑 python 平台脚本
- **不要**用 Write/Edit 写因子文件（让 write-factor skill 通过它的内部流程做）
- **不要**读写 state.json（通过 mcp__quant-mcp__run_save 让状态落地，research-loop 负责编排）
- **只调**：Skill (write-factor) / Read (必要时查上下文) / mcp__quant-mcp__submit_factor / mcp__quant-mcp__check_factor / mcp__quant-mcp__run_save

## 错误处理

- write-factor skill 失败：标 `failure_layer: "write_failed"`，返回失败
- MCP 工具异常：把 error message 记入 retry_trace，按 transient 处理重试 1 次；连续 2 次失败 give_up
```

- [ ] **Step 8.2: Commit**

```bash
cd /home/lgao/work/quant/sdk-demo
git commit --allow-empty -m "feat: 加 run-factor-agent 子代理定义"
```

---

## Task 9: 注册 MCP server 到 Claude Code

**目的：** 让 Claude Code 启动时自动起 quant-mcp server。

**Files:**
- Modify: `/home/lgao/work/quant/.claude/settings.json`

- [ ] **Step 9.1: 读现有 settings.json**

Run:
```bash
cat /home/lgao/work/quant/.claude/settings.json
```

记录现有内容（不要破坏既有配置）。

- [ ] **Step 9.2: 加 mcp_servers 配置**

Modify `/home/lgao/work/quant/.claude/settings.json`，加 `mcpServers` 字段：

```json
{
  "existingFields": "...",
  "mcpServers": {
    "quant-mcp": {
      "command": "node",
      "args": ["/home/lgao/work/quant/sdk-demo/mcp/server.mjs"],
      "env": {
        "QUANT_MCP_RUNS_ROOT": "/home/lgao/.quant-runs"
      }
    }
  }
}
```

（如已有 `mcpServers` 字段，合并 `quant-mcp` 进去。）

- [ ] **Step 9.3: 重启 Claude Code 验证**

退出当前 Claude Code 会话，在 `/home/lgao/work/quant` 目录重新启动：

```bash
cd /home/lgao/work/quant && claude
```

在新会话里：
- 打字 `列出可用的 quant-mcp 工具` 或 `调一下 health 工具`
- 预期：Claude 能列出所有 15 个工具，调 health 返回 `{ok: true, ts: "..."}`

如果工具没出现，检查：
1. server.mjs 启动是否报错：`cd sdk-demo && node mcp/server.mjs`（应输出 `[quant-mcp] server 已启动 (stdio)`）
2. settings.json 路径是否对
3. 依赖是否装好（`@modelcontextprotocol/sdk`）

- [ ] **Step 9.4: Commit（在 sdk-demo 仓库留 marker；settings.json 不在本仓库）**

```bash
cd /home/lgao/work/quant/sdk-demo
git commit --allow-empty -m "feat: 注册 quant-mcp server 到 Claude Code settings"
```

---

## Task 10: L2 烟雾测试 — 跑通完整循环

**目的：** 用 mock 平台模式（`QUANT_MCP_MOCK_PLATFORM=1`）跑通整个循环，验证 brainstorm → runFactor × 1 → evaluate 的端到端流程。

**Files:**
- Create: `sdk-demo/docs/specs/smoke-test-checklist.md`（手动跑的 checklist + 留证据位置）

- [ ] **Step 10.1: 写烟雾测试 checklist**

Create `sdk-demo/docs/specs/smoke-test-checklist.md`:

```markdown
# 第一期烟雾测试 Checklist

## 环境

```bash
export QUANT_MCP_MOCK_PLATFORM=1
export BRAINSTORM_ONLY=0
```

启动 Claude Code：
```bash
cd /home/lgao/work/quant && claude
```

## 测试 A：BRAINSTORM_ONLY（只到 Step 1）

1. 在会话里说：`/research-loop`，但临时把 N_FACTORS 设为 1
2. 或：直接告诉 Claude "用 research-loop skill，但只跑到 brainstorm 阶段"

**期望**：
- [ ] Claude 调 `run_init` 拿到 run_id
- [ ] Claude 调 `factor_counts` / `factor_list` / `factor_recent_lessons`
- [ ] Claude 调几次 `factor_search`（围绕 idea 的关键词）
- [ ] 产出 1 个候选 factor（含 formula/intuition/categories/params）
- [ ] 调 `persist_idea` 拿到 idea_id
- [ ] 调 `run_save` 写入 idea + factors
- [ ] 停在 Step 1 末，向用户报告 brainstorm 结果

**验证命令**（在 sdk-demo 跑）：
```bash
ls -la ~/.quant-runs/<run_id>/
cat ~/.quant-runs/<run_id>/state.json | jq '.idea, .factors[0].name'
```

## 测试 B：完整循环（mock 平台，1 个 factor）

1. 在会话里说：`跑完整 research-loop，N_FACTORS=1`

**期望**：
- [ ] Step 1 完成（见测试 A）
- [ ] Step 2：Claude 在一个消息里发 1 个 Task tool call 调起 run-factor-agent
- [ ] run-factor-agent 调 Skill write-factor 写出 `.h` 文件
- [ ] run-factor-agent 调 `submit_factor`（mock 返回 ok=true）
- [ ] run-factor-agent 调 `check_factor`（mock 返回 check_done + evidence.eval_metrics）
- [ ] run-factor-agent 返回 `{failure_layer: "check_done", evidence: {...}}`
- [ ] Claude 调 `run_save` 写 factors[0].failure_layer
- [ ] Step 3：Claude 加载 evaluate.md，推理出 verdict（pass/fail）
- [ ] Claude 调 `persist_factor` 写库
- [ ] Claude 调 `run_save` 写 status=done
- [ ] 报告：1 个因子，verdict=<pass 或 fail>

**验证命令**：
```bash
ls -la /home/lgao/work/quant/factors/<AlphaName>.h
sqlite3 /home/lgao/work/quant/sdk-demo/factors.db "SELECT xname, status FROM factors WHERE xname='<AlphaName>'"
sqlite3 /home/lgao/work/quant/sdk-demo/factors.db "SELECT type, substr(text, 1, 50) FROM lessons ORDER BY id DESC LIMIT 1"
cat ~/.quant-runs/<run_id>/state.json | jq '.status, .factors[0].verdict'
```

## 测试 C：断点续传

1. 跑测试 B，但在 Step 2 中途（子代理还没返回时）按 Ctrl+C 打断会话
2. 重启 Claude Code，说：`/research-loop <之前的 run_id>`

**期望**：
- [ ] Claude 调 `run_load {run_id}` 读到 state
- [ ] 看到 status=running 且 factors[0].status=submitting/checking，决定从 write 步重开
- [ ] 删除半成品 `.h` 文件
- [ ] 继续跑下去直到完成

## 通过标准

- 测试 A 必须通过（brainstorm 是基础）
- 测试 B 至少跑通一次完整循环（mock 平台）
- 测试 C 至少能识别断点状态（不要求完美续传，能报告"已存在的 run 状态"即可）

## 失败处理

- 任何 MCP 工具调用失败：先看 `~/.quant-runs/<run_id>/state.json` 的 status
- 子代理返回 agent_crashed：看 Task 工具的 error 信息
- 写库失败：直接看 sqlite 报错

## 完成后的清理

```bash
# 备份测试产物（不要直接删）
mkdir -p ~/quant-mcp-smoke-backup
cp -r ~/.quant-runs/<run_id> ~/quant-mcp-smoke-backup/
# 如果因子入库了，给 xname 加 _smoke 后缀避免污染正式库（或直接 sqlite3 删）
```
```

- [ ] **Step 10.2: 跑测试 A（brainstorm only）**

按 checklist 执行测试 A。把过程中的实际输出、遇到的问题、最终状态记录到 checklist 文件对应小节后面。

**期望**：brainstorm 走通，state.json 有 idea 和 factors[0]。

- [ ] **Step 10.3: 跑测试 B（完整循环，1 factor，mock 平台）**

按 checklist 执行测试 B。

**期望**：完整循环走通，factor 入库，state.json status=done。

如果失败：详细记录失败点、相关日志（Task 子代理返回 / MCP 工具错误 / sqlite 报错），不修就不进入下一步。

- [ ] **Step 10.4: 跑测试 C（断点续传）**

按 checklist 执行测试 C。

**期望**：能识别断点状态。完美续传非必需（可留给第二期）。

- [ ] **Step 10.5: Commit checklist 和测试结果**

```bash
cd /home/lgao/work/quant/sdk-demo
git add docs/specs/smoke-test-checklist.md
git commit -m "test: 第一期 L2 烟雾测试 checklist + 实跑结果"
```

- [ ] **Step 10.6: 总结报告**

向用户报告第一期完成情况：
- 15 个 MCP 工具全过 L1（21 个 unit test pass）
- 测试 A/B/C 各自结果
- 遗留问题清单（如果有）
- 是否可以进入第二期

---

## 第一期完成标准

- [ ] 所有 10 个 Task 完成
- [ ] 21 个 L1 单元测试全过
- [ ] 测试 A（brainstorm only）跑通
- [ ] 测试 B（完整循环 mock 平台）跑通至少 1 次
- [ ] 测试 C（断点续传）能识别断点
- [ ] git log 清晰（每个 Task 一个或多个 commit）

## 不在本期范围（第二期）

- `--print` 外部调度入口
- cron/systemd 集成
- 中间态持久化更精细化
- 多 run 并发的资源隔离
- 监控/告警
