import { runInit, runLoad, runSave, runList } from "../lib/run-store.mjs";

export const runInitSchema = {
  name: "run_init",
  description: "创建新的研究 run（含 run_id 和 state.json）。",
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
