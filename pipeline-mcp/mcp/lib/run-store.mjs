// 多 run_id 状态管理。所有 state 文件存到 <runsRoot>/<run_id>/state.json。
// runsRoot 默认 ~/.quant-runs，可被测试 override。

import fs from "node:fs";
import path from "node:path";
import os from "node:os";

let runsRoot = path.join(os.homedir(), ".quant-runs");
if (process.env.QUANT_MCP_RUNS_ROOT) {
  runsRoot = process.env.QUANT_MCP_RUNS_ROOT;
}

const _saveChains = new Map();
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
  const prev = _saveChains.get(runId) || Promise.resolve();
  const next = prev.then(() => doRunSave(runId, patch));
  _saveChains.set(runId, next);
  // Keep the map clean: when this chain settles, drop it if it's still the latest
  next.finally(() => {
    if (_saveChains.get(runId) === next) _saveChains.delete(runId);
  });
  return next;
}

async function doRunSave(runId, patch) {
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
