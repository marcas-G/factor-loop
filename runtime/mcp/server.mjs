#!/usr/bin/env node
// quant-mcp server — 量化研究 pipeline 的搬砖工具集。
// 通过 stdio 跟 Claude Code 通信。

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { healthSchema, healthHandler } from "./tools/health.mjs";
import * as factorDbModule from "./tools/factor-db.mjs";
import * as stateModule from "./tools/state.mjs";
import * as persistModule from "./tools/persist.mjs";
import * as hypothesisModule from "./tools/hypothesis-chain.mjs";
import * as discoverModule from "./tools/discover.mjs";
import * as platformModule from "./tools/platform.mjs";
import * as graphModule from "./tools/graph-traversal.mjs";

// 初始化 factor-db（首次启动时；_db 单例，重复调用无副作用）
import { init as factorDbInit } from "../lib/factor-db.mjs";
factorDbInit();

const ALL_TOOLS = [
  { schema: healthSchema, handler: healthHandler },
  ...factorDbModule.ALL_FACTOR_DB_SCHEMAS.map((schema) => ({
    schema,
    handler: factorDbModule.ALL_FACTOR_DB_HANDLERS[schema.name],
  })),
  ...stateModule.ALL_STATE_SCHEMAS.map((schema) => ({
    schema,
    handler: stateModule.ALL_STATE_HANDLERS[schema.name],
  })),
  ...persistModule.ALL_PERSIST_SCHEMAS.map((schema) => ({
    schema,
    handler: persistModule.ALL_PERSIST_HANDLERS[schema.name],
  })),
  ...hypothesisModule.ALL_HYPOTHESIS_SCHEMAS.map((schema) => ({
    schema,
    handler: hypothesisModule.ALL_HYPOTHESIS_HANDLERS[schema.name],
  })),
  ...discoverModule.ALL_DISCOVER_SCHEMAS.map((schema) => ({
    schema,
    handler: discoverModule.ALL_DISCOVER_HANDLERS[schema.name],
  })),
  ...platformModule.ALL_PLATFORM_SCHEMAS.map((schema) => ({
    schema,
    handler: platformModule.ALL_PLATFORM_HANDLERS[schema.name],
  })),
  ...graphModule.ALL_GRAPH_TRAVERSAL_SCHEMAS.map((schema) => ({
    schema,
    handler: graphModule.ALL_GRAPH_TRAVERSAL_HANDLERS[schema.name],
  })),
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
