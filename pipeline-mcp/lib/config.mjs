// 全局配置：路径常量 + CLI flag。import 时副作用创建 RUN_DIR / FACTORS_DIR。

import fs from "node:fs";
import path from "node:path";

export const CWD = "/home/lgao/work/quant";
export const CONSTRAINTS_FILE = path.join(CWD, ".claude", "CONSTRAINTS.yaml");
export const PRINCIPLES_FILE = path.join(CWD, ".claude", "PRINCIPLES.md");
export const FACTORS_DIR = path.join(CWD, "factors");
export const RUN_DIR = `/tmp/research-run-${Date.now()}`;
export const STATE_PATH = path.join(RUN_DIR, "state.json");
export const FEATURETOOL_PY = path.join(CWD, "pipeline-py", "featuretool.py");
export const FACTOR_CHECK_PY = path.join(CWD, "pipeline-py", "factor_check.py");

export const DRY_RUN = process.argv.includes("--dry-run");
export const QUIET = process.argv.includes("--quiet");
export const DUMP = process.env.DEBUG_DUMP === "1" || process.argv.includes("--dump");
export const TRACE = process.env.DEBUG === "2" || process.argv.includes("--trace");
export const FULL = process.argv.includes("--full");
export const SUBMIT_CONCURRENCY = 3;
export const BRAINSTORM_ONLY = process.env.BRAINSTORM_ONLY === "1";

fs.mkdirSync(RUN_DIR, { recursive: true });
fs.mkdirSync(FACTORS_DIR, { recursive: true });
