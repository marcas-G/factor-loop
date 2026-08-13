"""全局路径/环境常量(单一真相)。所有模块从这里 import,不再自己拼路径。

分层依赖规则(依赖只能向下,不向上):
    config.py     ← 叶子,零依赖(除 stdlib)
    db/           ← 依赖 config(DB_PATH)
    platform/     ← 依赖 config(CREDS_FILE)
    infra/        ← 依赖 config(VENV_PY)
    metrics.py    ← 纯函数
    tools/        ← 依赖 db + config(CACHE_ROOT)
    retrieval/    ← 依赖 db + config(DB_PATH)
    cog/          ← 依赖 db + platform + retrieval + config
    stages/       ← 依赖 infra + db + metrics
    mcp/          ← 依赖 db + stages + metrics + infra

规则:
    - config 零依赖(除 stdlib)
    - db 只依赖 config
    - 其余模块可依赖 config + 下层(db/infra/platform),不可反向
    - 路径常量一律从这里 import,禁止在业务模块里再拼 parents[N]/os.path.join
"""
from __future__ import annotations

import os
from pathlib import Path

# factor-autoloop 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 数据
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "factors.db"

# xycache 持久缓存(89% 命中;可 QUANT_XY_CACHE 覆盖)
CACHE_ROOT = Path(os.environ.get("QUANT_XY_CACHE", "/home/lgao/tmp/factor-vec-cache"))

# 平台
FEATURETOOL_PY = PROJECT_ROOT / "core" / "platform" / "featuretool.py"
FACTOR_CHECK_PY = PROJECT_ROOT / "core" / "platform" / "factor_check.py"
CREDS_FILE = Path.home() / "featuretool_creds.json"  # 平台自动登录账号密码

# venv python(有 sqlite_vec/pandas/sentence_transformers)
VENV_PY = os.environ.get("QUANT_VENV_PY") or "/home/lgao/quant-venv/bin/python"

# 图常量判据(双端共读 → 已单端化,retrieval/graph 判据)
GRAPH_CONSTANTS = PROJECT_ROOT / "core" / "db" / "graph_constants.json"

# schema
SCHEMA_SQL = PROJECT_ROOT / "core" / "db" / "schema.sql"
