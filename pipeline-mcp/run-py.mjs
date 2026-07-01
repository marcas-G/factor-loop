import { spawn } from "node:child_process";
import fs from "node:fs";

// 所有 python 调用统一走独立 venv（系统 python3 已缺 pandas / sqlite_vec / sentence_transformers）
const VENV_PY = "/home/lgao/quant-venv/bin/python";
const PY = fs.existsSync(VENV_PY) ? VENV_PY : "python3";

// shell:false + argv 数组：规避 shell 引号 bug（如 features="ClassA<>" 会被 shell 当重定向）
export function runPy(scriptPath, args = [], { timeoutSec = 600, cwd } = {}) {
  return new Promise((resolve) => {
    const start = Date.now();
    const proc = spawn(PY, [scriptPath, ...args], {
      cwd: cwd || process.cwd(),
      stdio: ["ignore", "pipe", "pipe"],
    });

    const stdout = [];
    const stderr = [];
    let killed = false;
    const timer = setTimeout(() => {
      killed = true;
      proc.kill("SIGTERM");
    }, timeoutSec * 1000);

    proc.stdout.on("data", (d) => stdout.push(d));
    proc.stderr.on("data", (d) => stderr.push(d));

    proc.on("error", (e) => {
      clearTimeout(timer);
      resolve({
        exitCode: -1,
        stdout: "",
        stderr: e.message,
        durationMs: Date.now() - start,
        timedOut: false,
      });
    });

    proc.on("close", (code) => {
      clearTimeout(timer);
      resolve({
        exitCode: code,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
        durationMs: Date.now() - start,
        timedOut: killed,
      });
    });
  });
}

// Python 端 --json 模式输出 stdout 末尾一行 JSON，但可能混入少量日志，做容错
export function parseJsonOutput(stdout) {
  if (!stdout || !stdout.trim()) return null;
  const s = stdout.trim();
  try {
    return JSON.parse(s);
  } catch {
    const m = s.match(/(\{[\s\S]*\})/);
    if (m) {
      try { return JSON.parse(m[1]); } catch { return null; }
    }
    return null;
  }
}
