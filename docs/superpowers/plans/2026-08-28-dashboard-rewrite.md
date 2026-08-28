# 因子库 Dashboard 重写实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Vite + React + TS 重写因子库看板:server.py 提供 `/api/snapshot` 实时读库,前端原地更新数据永不整页刷新,血缘图改横向可折叠树,因子表加多维筛选。

**Architecture:** 新建顶层 `dashboard/`(frontend/ + server.py)。server.py 纯 stdlib,复用从 `generate_factor_dashboard.py` 抽出的 `collect_snapshot()`,以 db 文件 mtime+size 做 ETag 内存缓存。前端 React 手写 SVG 图表 + 手写 CSS 设计系统,构建产物 dist/ 由 server.py 托管;开发时 Vite dev server 代理 /api。旧静态 HTML 链路退役进 attic/。

**Tech Stack:** React 18 + TypeScript + Vite(仅构建期依赖);server 纯 Python stdlib;测试沿用项目惯例 `python3 test_xxx.py`(unittest 断言 + main() 尾部打印 ✓);图表手写 SVG(仅 npm 装 `d3-zoom` + 复用现有 `d3-hierarchy`)。

**约定(全任务适用):**
- 仓库根:`/home/lgao/work/factor-autoloop`,下文相对路径均以此为基
- 前端命令一律 `cd dashboard/frontend && npm ...`
- 数据规模:factors 88 / lineage_edges 53 / 最大分支 44 节点 6 层——全量 JSON 无分页
- 不要动 `newfactor/`、`attic/`(用户的工作产物)
- spec: `docs/superpowers/specs/2026-08-28-dashboard-rewrite-design.md`

---

## Phase 0:保护现场

### Task 1: 提交现有 WIP,建立干净基线

**Files:**
- 无新文件;提交工作区现有未提交改动

- [ ] **Step 1: 确认待提交内容与 dashboard 相关**

```bash
cd /home/lgao/work/factor-autoloop && git status --short
```

预期:`core/db/db.py`、`core/mcp/tools/factor_db.py`、`core/tools/dashboard_template/*`、`generate_factor_dashboard.py`、`test_generate_factor_dashboard.py` 为 M;`dashboard-server/*`、`attic/` 为 ??。注意 `core/db/db.py` 的改动(leaderboard_gates/聚合分常数)是 dashboard 依赖,server.py 将 import 它,**必须先落库**。

- [ ] **Step 2: 跑一遍现有 dashboard 测试确认绿**

```bash
python3 core/tools/test_generate_factor_dashboard.py
```

预期输出:`✓ generate_factor_dashboard tests passed`

- [ ] **Step 3: 分两笔提交(无关改动隔离)**

```bash
git add core/db/db.py core/mcp/tools/factor_db.py
git commit -m "feat(db): leaderboard gates + aggregate score helpers"
git add core/tools/dashboard_template/ core/tools/generate_factor_dashboard.py core/tools/test_generate_factor_dashboard.py dashboard-server/
git commit -m "wip(dashboard): legacy template state before React rewrite"
```

- [ ] **Step 4: 确认工作区只剩 untracked 的用户产物**

```bash
git status --short
```

预期:仅 `?? attic/`、`?? newfactor/`(不动它们)。若 `docs/superpowers/` 下 spec/plan 未提交也一并提交。

---

## Phase 1:快照模块抽出 + API server

### Task 2: 抽出 dashboard_snapshot.py(TDD:先迁测试)

**Files:**
- Create: `core/tools/dashboard_snapshot.py`
- Modify: `core/tools/generate_factor_dashboard.py`(删采集部分,保留 CLI 兼容或直接退役)
- Create: `core/tools/test_dashboard_snapshot.py`
- Test 基础:复用 `test_generate_factor_dashboard.py` 的 SCHEMA + `_fixture_db`(整段拷贝,不改语义)

- [ ] **Step 1: 写失败测试**

`core/tools/test_dashboard_snapshot.py`:

```python
"""Tests for the dashboard snapshot collector (shared by API server)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools.dashboard_snapshot import collect_snapshot

# SCHEMA 与 _fixture_db 从 test_generate_factor_dashboard.py 原样拷贝
# (factors/factor_evals/iteration_suggestions/factor_lineage_edges/lessons/
#  tags/factor_tags 七张表 + TestFactor 一行数据)
SCHEMA = """ ...同 test_generate_factor_dashboard.py SCHEMA 全文... """

def _fixture_db(path: Path) -> None:
    ...同 test_generate_factor_dashboard.py 原文...


def test_collect_snapshot_fields() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "factors.db"
        _fixture_db(db_path)
        snap = collect_snapshot(db_path)
        f = snap["factors"][0]
        assert f["xname"] == "TestFactor"
        assert f["gate_pass"] is True and f["failed_gates"] == []
        assert abs(f["agg_score"] - 0.25 * (0.12 / 0.15 + 2.4 / 8 + 1.0 + (0.7 - 0.35) / 0.7)) < 1e-6
        assert f["tags"][0]["name"] == "order_book"
        assert abs(f["resic_ic_ratio"] - 0.08 / 0.12) < 1e-9
        for key in ("evaluations", "iterations", "lineage_edges",
                    "lineage_branches", "lessons", "meta"):
            assert key in snap
        assert "generatedAt" in snap["meta"]


def test_uri_db_path() -> None:
    # server 会传 file:...?mode=ro&immutable=1 形式,必须与裸路径等价
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "factors.db"
        _fixture_db(db_path)
        snap = collect_snapshot(f"file:{db_path}?mode=ro&immutable=1")
        assert snap["factors"][0]["xname"] == "TestFactor"


def main() -> None:
    test_collect_snapshot_fields()
    test_uri_db_path()
    print("✓ dashboard_snapshot tests passed")


if __name__ == "__main__":
    main()
```

注:`collect_snapshot` 参数类型注解改为 `Path | str`(URI 形式是 str)。

- [ ] **Step 2: 跑测试确认失败**

```bash
python3 core/tools/test_dashboard_snapshot.py
```

预期:`ModuleNotFoundError: No module named 'core.tools.dashboard_snapshot'`

- [ ] **Step 3: 建 dashboard_snapshot.py——把 generate_factor_dashboard.py 的采集部分原样迁移**

`core/tools/dashboard_snapshot.py` 结构(内容从旧文件 1-287 行平移,**不改逻辑**,仅:
- 模块 docstring 改为 "Snapshot collector shared by the API server and legacy generator."
- `collect_snapshot` 签名 `def collect_snapshot(db_path: Path | str) -> dict[str, Any]:`
- 保留 `_connect` 对 `file:` URI 的既有处理
- `from core.config import DB_PATH` 保留但仅在模块级 `DEFAULT_DB` 中使用:

```python
"""Snapshot collector for the factor dashboard (shared by API server)."""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.config import DB_PATH
from core.db.db import (
    GATE_R2_MAX, NORM_IC_SAT, NORM_ICIR_SAT, NORM_RES_IC_SAT,
    leaderboard_gates,
)

DEFAULT_DB = DB_PATH

# —— 以下整段从 generate_factor_dashboard.py 平移,函数名与行为不变 ——
FACTOR_COLUMNS = [...同旧文件 35-42 行...]

def _connect(db_path): ...
def _existing_columns(conn, table): ...
def _require_tables(conn): ...
def _select_factors(conn): ...
def _select_evals(conn): ...
def _select_iterations(conn): ...
def _select_lineage_edges(conn): ...
def _select_lineage_branches(conn): ...
def _select_lessons(conn): ...
def _select_tags(conn): ...
def _json_value(value): ...
def _clean_records(records): ...
def _attach_agg_scores(factors): ...
def collect_snapshot(db_path: Path | str) -> dict[str, Any]: ...
```

- [ ] **Step 4: 跑新测试确认通过**

```bash
python3 core/tools/test_dashboard_snapshot.py
```

预期:`✓ dashboard_snapshot tests passed`

- [ ] **Step 5: generate_factor_dashboard.py 改为从新模块 import(旧 CLI 与 HTML 渲染暂留,Phase 5 一并退役)**

`generate_factor_dashboard.py` 顶部改为:

```python
from core.tools.dashboard_snapshot import (
    FACTOR_COLUMNS, collect_snapshot,
)
```

并删除已被迁移的函数体(`_connect` 到 `collect_snapshot`),`render_html`/`write_atomic`/`main` 保留原样。

```bash
python3 core/tools/test_generate_factor_dashboard.py
```

预期:`✓ generate_factor_dashboard tests passed`(旧测试不回归)

- [ ] **Step 6: 提交**

```bash
git add core/tools/dashboard_snapshot.py core/tools/test_dashboard_snapshot.py core/tools/generate_factor_dashboard.py
git commit -m "refactor(dashboard): extract snapshot collector to shared module"
```

### Task 3: server.py —— /api/snapshot + ETag + 静态托管(TDD)

**Files:**
- Create: `dashboard/server.py`
- Create: `dashboard/test_server.py`

- [ ] **Step 1: 写失败测试(用 stdlib 起真服务打真请求)**

`dashboard/test_server.py`:

```python
"""Tests for dashboard/server.py (in-process HTTP round-trips)."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.server import SnapshotCache, make_handler


SCHEMA = """ ...同 Task 2 SCHEMA... """

def _fixture_db(path: Path) -> None:
    ...同 Task 2...


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_api_snapshot_etag_cycle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "factors.db"
        _fixture_db(db)
        cache = SnapshotCache(db)
        port = _free_port()
        httpd = make_server(("127.0.0.1", port), cache, dist_dir=None)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        # 1) 首次 GET:200 + JSON + ETag
        r1 = urllib.request.urlopen(f"{base}/api/snapshot", timeout=5)
        body1 = r1.read()
        etag = r1.headers["ETag"]
        assert r1.status == 200 and etag
        assert json.loads(body1)["factors"][0]["xname"] == "TestFactor"

        # 2) db 未变:If-None-Match → 304,且不重算(cache.calls == 1)
        req = urllib.request.Request(f"{base}/api/snapshot",
                                     headers={"If-None-Match": etag})
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected 304")
        except urllib.error.HTTPError as e:
            assert e.code == 304
        assert cache.calls == 1

        # 3) db 变了(mtime 变):同 ETag 再请求 → 200 新体
        import time
        conn = sqlite3.connect(db)
        conn.execute("UPDATE factors SET latest_ic = 0.2 WHERE xname='TestFactor'")
        conn.commit(); conn.close()
        # mtime 秒级精度兜底:显式前移 mtime
        import os
        stamp = db.stat().st_mtime + 2
        os.utime(db, (stamp, stamp))
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            assert resp.status == 200
            assert json.loads(resp.read())["factors"][0]["latest_ic"] == 0.2
        except urllib.error.HTTPError as e:
            raise AssertionError(f"expected 200 after db change, got {e.code}")

        httpd.shutdown()


def test_static_fallback_to_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "factors.db"
        _fixture_db(db)
        dist = Path(tmp) / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
        port = _free_port()
        httpd = make_server(("127.0.0.1", port), SnapshotCache(db), dist_dir=dist)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        assert urllib.request.urlopen(base, timeout=5).read() == b"<html>app</html>"
        # 前端路由路径回退 index.html
        assert urllib.request.urlopen(f"{base}/factor/x", timeout=5).read() == b"<html>app</html>"
        # dist 里不存在的资产不回退(避免把 404 当 html)
        try:
            urllib.request.urlopen(f"{base}/assets/nope.js", timeout=5)
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        httpd.shutdown()


def main() -> None:
    test_api_snapshot_etag_cycle()
    test_static_fallback_to_index()
    print("✓ server tests passed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python3 dashboard/test_server.py
```

预期:`ModuleNotFoundError: No module named 'dashboard'`(或 `dashboard.server` 不存在)

- [ ] **Step 3: 实现 server.py**

`dashboard/server.py`:

```python
#!/usr/bin/env python3
"""Factor dashboard HTTP server (stdlib only).

- GET /api/snapshot : fresh JSON from the SQLite db, ETag-cached on (mtime, size)
- GET /*            : static files from the Vite build (dist/), SPA fallback
The db is opened read-only (immutable=1) per snapshot; no pip dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools.dashboard_snapshot import DEFAULT_DB, collect_snapshot

DIST_DIR = Path(__file__).resolve().parent / "frontend" / "dist"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".map": "application/json",
}


class SnapshotCache:
    """(mtime_ns, size) → ETag;db 未变直接回缓存,变了重算。"""

    def __init__(self, db_path: Path | str) -> None:
        raw = str(db_path)
        self._fs_path = Path(raw.partition("?")[0].removeprefix("file:"))
        self._uri = raw if raw.startswith("file:") else f"file:{raw}?mode=ro&immutable=1"
        self._lock = threading.Lock()
        self._etag: str | None = None
        self._body: bytes = b""
        self.calls = 0  # 实际执行 collect_snapshot 的次数(测试用)

    def _stamp(self) -> tuple[int, int]:
        st = self._fs_path.stat()
        return st.st_mtime_ns, st.st_size

    def etag(self) -> str:
        mtime_ns, size = self._stamp()
        return f'W/"{mtime_ns:x}-{size:x}"'

    def get(self) -> tuple[str, bytes]:
        etag = self.etag()
        with self._lock:
            if etag == self._etag:
                return etag, self._body
        snapshot = collect_snapshot(self._uri)
        body = json.dumps(
            snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        with self._lock:
            self._etag, self._body = etag, body
            self.calls += 1
        return etag, body


def make_handler(cache: SnapshotCache, dist_dir: Path | None) -> type[BaseHTTPRequestHandler]:
    dist = dist_dir if dist_dir is not None else DIST_DIR

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, code: int, body: bytes, ctype: str,
                   extra: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] == "/api/snapshot":
                return self._api()
            return self._static()

        def _api(self) -> None:
            try:
                etag, body = cache.get()
            except Exception as exc:  # db 缺失/损坏:503 而不是崩
                self._reply(503, f'{{"error":"{type(exc).__name__}"}}'.encode(),
                            "application/json; charset=utf-8")
                return
            if self.headers.get("If-None-Match") == etag:
                self._reply(304, b"", "application/json; charset=utf-8",
                            {"ETag": etag})
                return
            self._reply(200, body, "application/json; charset=utf-8",
                        {"ETag": etag})

        def _static(self) -> None:
            if dist is None or not dist.is_dir():
                self._reply(503, "frontend not built; run: cd dashboard/frontend && npm run build"
                            .encode(), "text/plain; charset=utf-8")
                return
            rel = self.path.split("?", 1)[0].lstrip("/")
            candidate = (dist / rel).resolve()
            if (str(candidate).startswith(str(dist.resolve()))
                    and candidate.is_file()):
                return self._send_file(candidate)
            index = dist / "index.html"
            if index.is_file():
                return self._send_file(index)
            self._reply(404, b"not found", "text/plain; charset=utf-8")

        def _send_file(self, path: Path) -> None:
            body = path.read_bytes()
            self._reply(200, body, MIME.get(path.suffix, "application/octet-stream"))

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[http] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def make_server(addr: tuple[str, int], cache: SnapshotCache,
                dist_dir: Path | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(addr, make_handler(cache, dist_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Factor dashboard server")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite factor db (path or file: URI)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", "8765")))
    parser.add_argument("--dist", type=Path, default=DIST_DIR, help="frontend build dir")
    args = parser.parse_args()
    httpd = make_server(("0.0.0.0", args.port), SnapshotCache(args.db), dist_dir=args.dist)
    print(f"[http] dashboard on 0.0.0.0:{args.port} (db={args.db}, dist={args.dist})", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

注意:`dashboard/` 需要 `__init__.py`(空文件)让 `from dashboard.server import ...` 在测试里可 import。

- [ ] **Step 4: 跑测试确认通过**

```bash
python3 dashboard/test_server.py
```

预期:`✓ server tests passed`

- [ ] **Step 5: 真库冒烟(手动)**

```bash
python3 dashboard/server.py --port 8901 &
sleep 1 && curl -s -D- -o /dev/null http://127.0.0.1:8901/api/snapshot | grep -i etag
kill %1
```

预期:响应头有 `ETag: W/"..."`;二次请求带 If-None-Match 返回 304。

- [ ] **Step 6: 提交**

```bash
git add dashboard/__init__.py dashboard/server.py dashboard/test_server.py
git commit -m "feat(dashboard): stdlib API server — /api/snapshot with ETag cache + SPA static"
```

---

## Phase 2:前端骨架

### Task 4: Vite + React + TS 脚手架

**Files:**
- Create: `dashboard/frontend/`(package.json、vite.config.ts、tsconfig、index.html、src/main.tsx、src/App.tsx 骨架)

- [ ] **Step 1: 初始化(npm create 只用一次,产物入库)**

```bash
cd /home/lgao/work/factor-autoloop/dashboard
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install d3-zoom d3-hierarchy
npm install -D @types/d3-zoom @types/d3-hierarchy
```

- [ ] **Step 2: vite.config.ts —— dev 代理 /api,build 出到 dist/**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8901",
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
```

- [ ] **Step 3: 清掉模板演示代码,写最小 App**

`src/App.tsx`:

```tsx
import { useEffect, useState } from "react";

export default function App() {
  const [msg, setMsg] = useState("loading…");
  useEffect(() => {
    fetch("/api/snapshot").then(r => r.json()).then(d => {
      setMsg(`factors: ${d.factors?.length ?? "?"}`);
    }).catch(() => setMsg("api unreachable"));
  }, []);
  return <main style={{ padding: 24, fontFamily: "monospace" }}>{msg}</main>;
}
```

- [ ] **Step 4: 端到端冒烟(dev server + API server 同时跑)**

```bash
# 终端 A(仓库根)
python3 dashboard/server.py --port 8901 &
# 终端 B
cd dashboard/frontend && npm run dev -- --port 5173 &
curl -s http://127.0.0.1:5173/ | grep -o "<title>.*</title>"
curl -s http://127.0.0.1:5173/api/snapshot | head -c 120
kill %1 %2 2>/dev/null
```

预期:第二个 curl 返回 JSON 开头 `{"factors":[...`(代理生效)。

- [ ] **Step 5: 构建冒烟 + 提交**

```bash
cd dashboard/frontend && npm run build && ls dist/
```

预期:`dist/index.html`、`dist/assets/*.js` 存在。

`.gitignore` 追加(dashboard/frontend 下不提交 node_modules/dist):

```
node_modules/
dist/
```

(若仓库根 .gitignore 已含则跳过。)

```bash
git add dashboard/frontend/.gitignore dashboard/frontend/package.json dashboard/frontend/package-lock.json dashboard/frontend/vite.config.ts dashboard/frontend/tsconfig*.json dashboard/frontend/index.html dashboard/frontend/src/
git commit -m "feat(dashboard): Vite + React + TS scaffold with /api proxy"
```

### Task 5: 数据层 —— types + api + state(URL hash 同步)

**Files:**
- Create: `dashboard/frontend/src/types.ts`
- Create: `dashboard/frontend/src/api.ts`
- Create: `dashboard/frontend/src/state.ts`

- [ ] **Step 1: types.ts(与 collect_snapshot 输出一一对应)**

```ts
export interface Tag { name: string; description: string | null }

export interface Factor {
  xname: string;
  class_name: string | null;
  file_path: string | null;
  formula_text: string | null;
  params: string | null;
  status: string;
  verdict: string | null;
  latest_ic: number | null;
  latest_icir: number | null;
  latest_sharpe: number | null;
  latest_rank_ic: number | null;
  latest_r2_x: number | null;
  latest_res_ic: number | null;
  created_ts: string | null;
  last_updated_ts: string | null;
  quality_score: number | null;
  quality_grade: string | null;
  intuition: string | null;
  anchor_text: string | null;
  origin_type: string | null;
  cohort_tag: string | null;
  operator_chain: string | null;
  evaluation_status: string | null;
  tags: Tag[];
  resic_ic_ratio: number | null;
  gate_pass: boolean;
  failed_gates: string[];
  s_ic: number | null; s_icir: number | null; s_res_ic: number | null; s_r2: number | null;
  agg_score: number | null;
}

export interface Eval {
  id: number; factor_xname: string; idea_id: number | null; ts: string | null;
  symbol: string | null; freq: string | null;
  ic_mean: number | null; icir: number | null; sharpe: number | null; rank_ic: number | null;
  eval_metrics: string | null; eval_mode: string | null; significant: number | null; raw_path: string | null;
}

export interface Iteration {
  id: number; from_xname: string; to_xname: string; idea_id: number | null;
  change_note: string | null; reason: string | null;
  outcome: string | null; icir_delta: number | null; ts: string | null; status: string | null;
}

export interface LineageEdge {
  parent_xname: string; child_xname: string; relation_type: string | null;
  outcome: string | null; confidence: number | null; op_id: number | null; operator_name: string | null;
}

export interface LineageBranch {
  root_xname: string; root_status: string | null; member_count: number;
  max_depth: number; evaluated_count: number | null; dead_end_count: number | null;
}

export interface Lesson {
  id: number; type: string; scope: string; text: string;
  evidence: string | null; idea_id: number | null; factor_xname: string | null;
  created_ts: string | null; deprecated_at: string | null;
}

export interface Snapshot {
  factors: Factor[];
  evaluations: Eval[];
  iterations: Iteration[];
  lineage_edges: LineageEdge[];
  lineage_branches: LineageBranch[];
  lessons: Lesson[];
  meta: { dbPath: string; dbModifiedAt: string; generatedAt: string };
}
```

- [ ] **Step 2: api.ts —— ETag 探测 + 拉取**

```ts
import type { Snapshot } from "./types";

let etag: string | null = null;

export interface FetchResult { data: Snapshot; changed: boolean }

export async function fetchSnapshot(): Promise<FetchResult> {
  const headers: Record<string, string> = {};
  if (etag) headers["If-None-Match"] = etag;
  const res = await fetch("/api/snapshot", { headers, cache: "no-store" });
  if (res.status === 304 && lastData) return { data: lastData, changed: false };
  if (!res.ok) throw new Error(`api ${res.status}`);
  const newEtag = res.headers.get("ETag");
  if (newEtag) etag = newEtag;
  lastData = await res.json() as Snapshot;
  return { data: lastData, changed: true };
}

let lastData: Snapshot | null = null;
```

- [ ] **Step 3: state.ts —— URL hash 双向同步(筛选/选中/血缘分支)**

```ts
export interface FilterState {
  q: string;                    // 文本搜索
  status: string[];             // 状态多选
  tags: string[];               // 标签多选
  gates: string[];              // 闸门分项: "ic"|"icir"|"res_ic"|"r2"|"pass"
  origin: string[];             // origin_type/class_name 多选
  opChainMin: number | null;    // 算子链长度区间
  opChainMax: number | null;
  createdFrom: string | null;   // ISO 日期
  createdTo: string | null;
  sortKey: string;              // 排序列
  sortDir: "asc" | "desc";
  selected: string | null;      // 选中因子 xname
  branch: string;               // 血缘分支 "all"|root_xname
}

export const DEFAULT_FILTERS: FilterState = {
  q: "", status: [], tags: [], gates: [], origin: [],
  opChainMin: null, opChainMax: null, createdFrom: null, createdTo: null,
  sortKey: "agg_score", sortDir: "desc", selected: null, branch: "all",
};

export function parseHash(): FilterState {
  const out = { ...DEFAULT_FILTERS };
  const h = new URLSearchParams(location.hash.replace(/^#/, ""));
  if (h.has("q")) out.q = h.get("q") ?? "";
  for (const key of ["status", "tags", "gates", "origin"] as const) {
    const v = h.get(key);
    if (v) out[key] = v.split(",").filter(Boolean);
  }
  const num = (k: keyof FilterState) => {
    const v = h.get(k as string);
    if (v !== null && v !== "") (out as any)[k] = Number(v);
  };
  num("opChainMin"); num("opChainMax");
  if (h.get("from")) out.createdFrom = h.get("from");
  if (h.get("to")) out.createdTo = h.get("to");
  if (h.get("sort")) out.sortKey = h.get("sort")!;
  if (h.get("dir") === "asc" || h.get("dir") === "desc") out.sortDir = h.get("dir") as "asc" | "desc";
  if (h.get("sel")) out.selected = h.get("sel");
  if (h.get("branch")) out.branch = h.get("branch")!;
  return out;
}

export function writeHash(f: FilterState): void {
  const h = new URLSearchParams();
  if (f.q) h.set("q", f.q);
  for (const key of ["status", "tags", "gates", "origin"] as const) {
    if (f[key].length) h.set(key, f[key].join(","));
  }
  if (f.opChainMin !== null) h.set("opChainMin", String(f.opChainMin));
  if (f.opChainMax !== null) h.set("opChainMax", String(f.opChainMax));
  if (f.createdFrom) h.set("from", f.createdFrom);
  if (f.createdTo) h.set("to", f.createdTo);
  if (f.sortKey !== DEFAULT_FILTERS.sortKey || f.sortDir !== DEFAULT_FILTERS.sortDir) {
    h.set("sort", f.sortKey); h.set("dir", f.sortDir);
  }
  if (f.selected) h.set("sel", f.selected);
  if (f.branch !== "all") h.set("branch", f.branch);
  const s = h.toString();
  const next = s ? `#${s}` : "";
  if (location.hash !== next) history.replaceState(null, "", next || location.pathname);
}
```

- [ ] **Step 4: tsc 通过 + 提交**

```bash
cd dashboard/frontend && npx tsc --noEmit
```

预期:无错误。

```bash
git add dashboard/frontend/src/types.ts dashboard/frontend/src/api.ts dashboard/frontend/src/state.ts
git commit -m "feat(dashboard): frontend data layer — types, ETag api, hash-synced filter state"
```

---

## Phase 3:页面骨架 + 刷新交互

### Task 6: App 布局 + 手动刷新 + 后台探测角标

**Files:**
- Modify: `dashboard/frontend/src/App.tsx`
- Create: `dashboard/frontend/src/components/Header.tsx`
- Create: `dashboard/frontend/src/hooks/useSnapshot.ts`

- [ ] **Step 1: useSnapshot hook —— 唯一的数据入口**

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchSnapshot } from "../api";
import type { Snapshot } from "../types";

export type LoadState = "loading" | "ready" | "error";

export function useSnapshot() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [stale, setStale] = useState(false);       // 探测到新数据,未应用
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const applyRef = useRef<(() => void) | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { data: snap } = await fetchSnapshot();
      setData(snap);
      setUpdatedAt(new Date().toISOString());
      setStale(false);
      setLoadState("ready");
    } catch {
      setLoadState((s) => (s === "ready" ? s : "error"));
    }
  }, []);

  // 首次加载
  useEffect(() => { void refresh(); }, [refresh]);

  // 后台探测:60s 一次,只亮角标,绝不自动应用
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const { changed } = await fetchSnapshot();
        if (changed) {
          // fetchSnapshot 拿到 200 即有新数据;但应用与否由用户决定。
          // 注意:这里 changed=true 时 lastData 已被更新,需要回退角标语义——
          // 见 Step 2 的 probe 实现说明。
          setStale(true);
        }
      } catch { /* 断网静默 */ }
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  applyRef.current = () => { void refresh(); };

  return { data, loadState, stale, updatedAt, refresh,
           applyStale: () => applyRef.current?.() };
}
```

**Step 2 说明(实现时照此修正):** 上面的探测直接复用 `fetchSnapshot` 会把新数据悄悄写进 `lastData`,导致下次 refresh 304 而不更新 UI。正确做法:在 `api.ts` 增加**只探测不落缓存**的函数,探测走 `HEAD /api/snapshot` 比较 ETag:

```ts
// api.ts 追加
export async function probeSnapshot(): Promise<boolean> {
  const res = await fetch("/api/snapshot", { method: "HEAD", cache: "no-store" });
  if (!res.ok) return false;
  const server = res.headers.get("ETag");
  if (!server) return false;
  if (etag === null) { etag = server; return false; } // 首次仅记录基线
  return server !== etag;
}
```

server.py 的 `do_HEAD` 已复用 `do_GET`(304 分支不写 body),`HEAD /api/snapshot` 天然支持。useSnapshot 的探测改用 `probeSnapshot()`,角标条件 `server !== etag && etag !== null`。

- [ ] **Step 3: Header 组件(品牌区 + 刷新按钮 + stale 角标 + 生成时间)**

```tsx
import type { LoadState } from "../hooks/useSnapshot";

interface Props {
  loadState: LoadState;
  stale: boolean;
  updatedAt: string | null;
  generatedAt: string;
  onRefresh: () => void;
  onApplyStale: () => void;
}

export function Header({ loadState, stale, updatedAt, generatedAt, onRefresh, onApplyStale }: Props) {
  return (
    <header className="app-header">
      <div className="brand">
        <div className="brand-mark" aria-hidden>F</div>
        <div>
          <h1>因子库看板</h1>
          <p className="meta">快照 {new Date(generatedAt).toLocaleString()}</p>
        </div>
      </div>
      <div className="header-actions">
        <span className={`stale-badge ${stale ? "show" : ""}`}
              role="status" title="数据已更新,点击应用(不会打断当前浏览)">
          {stale && <button onClick={onApplyStale}>有新数据 · 应用</button>}
        </span>
        <button className="icon-button" onClick={onRefresh}
                title="手动刷新(保留筛选与滚动位置)">↻</button>
        <span className="load-dot" data-state={loadState} title={updatedAt ?? ""} />
      </div>
    </header>
  );
}
```

- [ ] **Step 4: App.tsx 组装(占位 section,后续任务逐个替换)**

```tsx
import { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { useSnapshot } from "./hooks/useSnapshot";
import { DEFAULT_FILTERS, parseHash, writeHash, type FilterState } from "./state";

export default function App() {
  const { data, loadState, stale, updatedAt, refresh, applyStale } = useSnapshot();
  const [filters, setFilters] = useState<FilterState>(() => parseHash());

  useEffect(() => { writeHash(filters); }, [filters]);
  useEffect(() => {
    const onHash = () => setFilters(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (loadState === "loading") return <div className="fullpad">加载中…</div>;
  if (loadState === "error" || !data) return <div className="fullpad">API 不可达,稍后重试</div>;

  return (
    <>
      <Header loadState={loadState} stale={stale} updatedAt={updatedAt}
              generatedAt={data.meta.generatedAt}
              onRefresh={refresh} onApplyStale={applyStale} />
      <main className="layout">
        {/* Task 7-11 逐个填充:MetricCards / 图表 / LineageTree / FactorTable / DetailPanel */}
      </main>
    </>
  );
}
```

- [ ] **Step 5: 冒烟验证刷新行为**

dev 双进程跑起来后浏览器验证(或 curl 检查):初始 200;改 db(触碰 factors.db mtime)后 60s 内出现角标;点"应用"数据更新且 hash 不变;**全程无页面重载**(DevTools Network 无 document 请求)。

- [ ] **Step 6: tsc + 提交**

```bash
cd dashboard/frontend && npx tsc --noEmit
git add -A dashboard/frontend/src
git commit -m "feat(dashboard): app shell with manual refresh + stale badge (no page reloads)"
```

---

## Phase 4:可视化组件

(设计语言统一到 Task 12 的全局 CSS;每个组件先写最小可用版,Task 12 统一打磨。图表一律手写 SVG。)

### Task 7: MetricCards + 状态分布

**Files:**
- Create: `dashboard/frontend/src/components/MetricCards.tsx`
- Create: `dashboard/frontend/src/components/charts/StatusChart.tsx`

- [ ] **Step 1: MetricCards —— 6 张卡:总数/评估通过/闸门通过/中位 |IC|/中位 ICIR/失败数,每张尾部 sparkline(近 20 次 eval)**

实现要点:
- props: `{ factors: Factor[]; evaluations: Eval[] }`
- sparkline 用 `<svg viewBox="0 0 100 24">` polyline,数据点 = 按 ts 排序的近 20 条 eval 的 `ic_mean`
- 数字变化时 CSS transition(`transition: .3s` on transform/opacity,key 不变)
- 卡片可点击的只有"评估通过/闸门通过"两张:点击设置 `filters.gates = ["pass"]`(通知父级,props 传 `onFilterGate?: () => void`)

```tsx
import type { Eval, Factor } from "../types";

interface Props {
  factors: Factor[];
  evaluations: Eval[];
  onFilterGate?: () => void;
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) =>
    `${(i / (values.length - 1)) * 100},${24 - ((v - min) / span) * 22 - 1}`);
  const zeroY = 24 - ((0 - min) / span) * 22 - 1;
  return (
    <svg className="spark" viewBox="0 0 100 24" preserveAspectRatio="none">
      {min < 0 && max > 0 && <line x1="0" x2="100" y1={zeroY} y2={zeroY} />}
      <polyline points={pts.join(" ")} />
    </svg>
  );
}

export function MetricCards({ factors, evaluations, onFilterGate }: Props) {
  const evaluated = factors.filter(f => f.status === "evaluated");
  const passed = factors.filter(f => f.gate_pass);
  const median = (xs: number[]) =>
    xs.length ? xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)] : null;
  const ics = factors.map(f => f.latest_ic).filter((v): v is number => v !== null);
  const icirs = factors.map(f => f.latest_icir).filter((v): v is number => v !== null);
  const recentIc = [...evaluations]
    .sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
    .slice(-20).map(e => e.ic_mean).filter((v): v is number => v !== null);

  const cards = [
    { label: "因子总数", value: factors.length, spark: recentIc },
    { label: "已评估", value: evaluated.length, spark: recentIc },
    { label: "闸门通过", value: passed.length, spark: recentIc, onClick: onFilterGate },
    { label: "中位 |IC|", value: median(ics.map(Math.abs)), fmt: (v: number) => v.toFixed(3), spark: recentIc },
    { label: "中位 ICIR", value: median(icirs), fmt: (v: number) => v.toFixed(2), spark: recentIc },
    { label: "闸门未过", value: factors.length - passed.length, spark: recentIc },
  ];
  return (
    <div className="metrics">
      {cards.map(c => (
        <div key={c.label} className={`metric-card${c.onClick ? " clickable" : ""}`}
             onClick={c.onClick}>
          <span className="metric-label">{c.label}</span>
          <span className="metric-value">
            {c.value === null ? "—" : c.fmt ? c.fmt(c.value) : c.value}
          </span>
          <Sparkline values={c.spark} />
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: StatusChart —— 水平堆叠条 + 图例(状态→数量)**

```tsx
import type { Factor } from "../../types";

const STATUS_COLORS: Record<string, string> = {
  evaluated: "#34d399", draft: "#94a3b8", submitted: "#fbbf24",
  deprecated: "#f87171", failed: "#c084fc",
};

export function StatusChart({ factors }: { factors: Factor[] }) {
  const counts = new Map<string, number>();
  for (const f of factors) counts.set(f.status, (counts.get(f.status) ?? 0) + 1);
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const total = factors.length || 1;
  return (
    <figure className="chart-box">
      <figcaption>状态分布</figcaption>
      <div className="hbar">
        {entries.map(([status, n]) => (
          <div key={status} className="hbar-seg"
               style={{ width: `${(n / total) * 100}%`, background: STATUS_COLORS[status] ?? "#5d7089" }}
               title={`${status}: ${n}`} />
        ))}
      </div>
      <ul className="legend">
        {entries.map(([status, n]) => (
          <li key={status}><i style={{ background: STATUS_COLORS[status] ?? "#5d7089" }} />{status} · {n}</li>
        ))}
      </ul>
    </figure>
  );
}
```

- [ ] **Step 3: 接进 App + tsc + 提交**

App.tsx 的 `<main>` 顶部加:

```tsx
<MetricCards factors={data.factors} evaluations={data.evaluations}
             onFilterGate={() => setFilters(f => ({ ...f, gates: ["pass"] }))} />
```

```bash
cd dashboard/frontend && npx tsc --noEmit
git add dashboard/frontend/src
git commit -m "feat(dashboard): metric cards with sparklines + status distribution bar"
```

### Task 8: 散点图(冗余度 × 预测强度)+ 代际趋势

**Files:**
- Create: `dashboard/frontend/src/components/charts/Scatter.tsx`
- Create: `dashboard/frontend/src/components/charts/Trend.tsx`

- [ ] **Step 1: Scatter —— R² 为 x、|ICIR| 为 y;中位十字线;悬停十字线+数据卡;点点击选中因子**

实现要点(完整组件,SVG viewBox `0 0 720 355`):
- 布局:左 48px y 轴、下 28px x 轴、右 12px 上 12px 留白
- 域:x = [0, max(r2)*1.1],y = [0, max(|icir|)*1.1],空安全(无数据返回占位)
- 点:半径 4,`fill` 按状态色(同 StatusChart 常量,抽出 `src/charts/colors.ts` 共享),闸门通过加发光描边
- 中位虚线十字(x=median r2, y=median |icir|,`stroke-dasharray 4 4`,色 `--border`)
- 悬停:距最近点 < 10px 显示 `<line>` 十字 + `<foreignObject>` 或绝对定位 div 数据卡(因子名/IC/ICIR/R²/残差IC);`onPointerMove` on svg
- 点击点 → `onSelect(xname)`
- 数据更新动画:点用 CSS `transition: cx .3s, cy .3s`(SVG 属性 transition 对 cx/cy 在 Chrome 生效;用 style transform 亦可——实现取 transform: translate 包 `<g>`)
- 选中因子对应的点放大 + 常显标签

```tsx
import { useMemo, useState } from "react";
import type { Factor } from "../../types";
import { STATUS_COLORS } from "../../charts/colors";

interface Props {
  factors: Factor[];
  selected: string | null;
  onSelect: (xname: string) => void;
}

const W = 720, H = 355, M = { l: 48, r: 14, t: 14, b: 30 };

export function Scatter({ factors, selected, onSelect }: Props) {
  const pts = useMemo(() => factors
    .filter(f => f.latest_r2_x != null && f.latest_icir != null)
    .map(f => ({ x: f.latest_r2_x!, y: Math.abs(f.latest_icir!),
                 color: STATUS_COLORS[f.status] ?? "#5d7089",
                 glow: f.gate_pass, name: f.xname,
                 ic: f.latest_ic, r2: f.latest_r2_x, res: f.latest_res_ic })), [factors]);
  const [hover, setHover] = useState<number | null>(null);

  if (!pts.length) return <figure className="chart-box"><figcaption>冗余度 × 预测强度</figcaption><p className="empty">无数据</p></figure>;

  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  const xMax = Math.max(...xs) * 1.1 || 1, yMax = Math.max(...ys) * 1.1 || 1;
  const med = (a: number[]) => a.slice().sort((m, n) => m - n)[Math.floor(a.length / 2)];
  const sx = (v: number) => M.l + (v / xMax) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - (v / yMax) * (H - M.t - M.b);

  const ticks = (max: number) => [0.25, 0.5, 0.75, 1].map(t => max * t);
  const hovered = hover !== null ? pts[hover] : null;

  return (
    <figure className="chart-box scatter">
      <figcaption>冗余度 × 预测强度</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`}
           onPointerMove={e => {
             const r = (e.target as SVGElement).ownerSVGElement
                       ?? (e.currentTarget as SVGSVGElement);
             const box = r.getBoundingClientRect();
             const mx = (e.clientX - box.left) / box.width * W;
             const my = (e.clientY - box.top) / box.height * H;
             let best: number | null = null, bd = 12;
             pts.forEach((p, i) => {
               const d = Math.hypot(sx(p.x) - mx, sy(p.y) - my);
               if (d < bd) { bd = d; best = i; }
             });
             setHover(best);
           }}
           onPointerLeave={() => setHover(null)}>
        {ticks(yMax).map(t => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} className="grid" />
            <text x={M.l - 6} y={sy(t) + 4} className="tick" textAnchor="end">{t.toFixed(1)}</text>
          </g>
        ))}
        {ticks(xMax).map(t => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={M.t} y2={H - M.b} className="grid" />
            <text x={sx(t)} y={H - M.b + 16} className="tick" textAnchor="middle">{t.toFixed(2)}</text>
          </g>
        ))}
        <line x1={sx(med(xs))} x2={sx(med(xs))} y1={M.t} y2={H - M.b} className="median" />
        <line x1={M.l} x2={W - M.r} y1={sy(med(ys))} y2={sy(med(ys))} className="median" />
        <text x={W - M.r} y={H - 6} className="tick" textAnchor="end">R² →</text>
        <text x={M.l - 34} y={M.t + 4} className="tick">|ICIR| ↑</text>
        {pts.map((p, i) => (
          <g key={p.name} className="dot-wrap"
             style={{ transform: `translate(${sx(p.x).toFixed(1)}px, ${sy(p.y).toFixed(1)}px)` }}
             onClick={() => onSelect(p.name)}>
            <circle r={p.name === selected ? 6 : 4}
                    fill={p.color} className={`dot${p.glow ? " glow" : ""}${hover === i ? " hot" : ""}`} />
            {(hover === i || p.name === selected) && (
              <text y={-10} className="dot-label" textAnchor="middle">{p.name.slice(0, 28)}</text>
            )}
          </g>
        ))}
        {hovered && (
          <line x1={M.l} x2={W - M.r} y1={sy(hovered.y)} y2={sy(hovered.y)} className="crosshair" />
        )}
      </svg>
      {hovered && (
        <div className="hover-card">
          <b>{hovered.name}</b>
          <span>IC {hovered.ic?.toFixed(3) ?? "—"}</span>
          <span>|ICIR| {hovered.y.toFixed(2)}</span>
          <span>R² {hovered.r2?.toFixed(2) ?? "—"}</span>
          <span>残差IC {hovered.res?.toFixed(3) ?? "—"}</span>
        </div>
      )}
    </figure>
  );
}
```

- [ ] **Step 2: colors.ts(共享状态色)**

```ts
export const STATUS_COLORS: Record<string, string> = {
  evaluated: "#34d399", draft: "#94a3b8", submitted: "#fbbf24",
  deprecated: "#f87171", failed: "#c084fc",
};
export const STATUS_LABELS: Record<string, string> = {
  evaluated: "已评估", draft: "草稿", submitted: "已提交",
  deprecated: "已放弃", failed: "失败",
};
```

- [ ] **Step 3: Trend —— 代际(按血缘深度分组)IC/ICIR 中位数折线 + 通过率柱**

实现要点:
- 代际计算:复用旧逻辑——对每个因子沿 lineage_edges 向上数深度(缓存 Map);无边的因子深度 0
- 每个深度 d 统计:median(|IC|)、median(|ICIR|)、gate 通过率
- SVG viewBox `0 0 720 260`:双 y 轴(左 IC/ICIR,右通过率 0-100%),x 为代际序号
- 折线 `polyline` + 每点 `<circle>`;通过率用底部细柱(`<rect>`)
- 数据更新时 polyline 的 points 属性变化,加 CSS `transition: d .3s`(path)或直接重渲染(折线过渡可选,不阻塞)

```tsx
import { useMemo } from "react";
import type { Factor, LineageEdge } from "../../types";

interface Props { factors: Factor[]; edges: LineageEdge[] }

const W = 720, H = 260, M = { l: 44, r: 44, t: 14, b: 30 };

export function Trend({ factors, edges }: Props) {
  const series = useMemo(() => {
    const parent = new Map(edges.map(e => [e.child_xname, e.parent_xname]));
    const depth = (name: string, seen = new Set<string>()): number => {
      if (seen.has(name)) return 0;
      const p = parent.get(name);
      if (!p) return 0;
      seen.add(name);
      return 1 + depth(p, seen);
    };
    const byGen = new Map<number, Factor[]>();
    for (const f of factors) {
      const d = depth(f.xname);
      byGen.set(d, [...(byGen.get(d) ?? []), f]);
    }
    return [...byGen.entries()].sort((a, b) => a[0] - b[0]).map(([gen, fs]) => {
      const med = (xs: number[]) =>
        xs.length ? xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)] : null;
      return {
        gen, n: fs.length,
        ic: med(fs.map(f => f.latest_ic).filter((v): v is number => v !== null).map(Math.abs)),
        icir: med(fs.map(f => f.latest_icir).filter((v): v is number => v !== null).map(Math.abs)),
        passRate: fs.length ? fs.filter(f => f.gate_pass).length / fs.length : 0,
      };
    });
  }, [factors, edges]);

  if (!series.length) return <figure className="chart-box"><figcaption>代际趋势</figcaption><p className="empty">无数据</p></figure>;

  const icMax = Math.max(...series.map(s => s.ic ?? 0), 0.1) * 1.15;
  const icirMax = Math.max(...series.map(s => s.icir ?? 0), 0.5) * 1.15;
  const xs = series.map((_, i) => M.l + (i + 0.5) * (W - M.l - M.r) / series.length);
  const line = (vals: (number | null)[]) => vals
    .map((v, i) => v === null ? null : `${xs[i]},${H - M.b - (v / (v === (vals.find(x => x !== null)) ? 1 : 1)) * 0}`)
    .filter(Boolean).join(" ");
  // ↑ 简化实现:分别对 ic/icir 用各自 max 归一
  const norm = (v: number | null, max: number) =>
    v === null ? null : `${String(0)},${0}`; // 占位,实现时按下面真代码写

  const yIc = (v: number) => H - M.b - (v / icMax) * (H - M.t - M.b);
  const yIcir = (v: number) => H - M.b - (v / icirMax) * (H - M.t - M.b);
  const bw = (W - M.l - M.r) / series.length * 0.5;

  return (
    <figure className="chart-box trend">
      <figcaption>代际趋势 · IC / ICIR 中位数与通过率</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`}>
        {[0.25, 0.5, 0.75, 1].map(t => (
          <line key={t} x1={M.l} x2={W - M.r}
                y1={H - M.b - t * (H - M.t - M.b)} y2={H - M.b - t * (H - M.t - M.b)} className="grid" />
        ))}
        {series.map((s, i) => (
          <rect key={s.gen} x={xs[i] - bw / 2} y={H - M.b - s.passRate * (H - M.t - M.b)}
                width={bw} height={s.passRate * (H - M.t - M.b)} className="pass-bar"
                rx={2}>
            <title>第 {s.gen} 代 · {s.n} 因子 · 通过率 {(s.passRate * 100).toFixed(0)}%</title>
          </rect>
        ))}
        {series.some(s => s.ic !== null) && (
          <polyline className="trend-ic" points={series.map((s, i) => s.ic === null ? null : `${xs[i]},${yIc(s.ic)}`).filter(Boolean).join(" ")} />
        )}
        {series.some(s => s.icir !== null) && (
          <polyline className="trend-icir" points={series.map((s, i) => s.icir === null ? null : `${xs[i]},${yIcir(s.icir)}`).filter(Boolean).join(" ")} />
        )}
        {series.map((s, i) => (
          <g key={s.gen}>
            {s.ic !== null && <circle cx={xs[i]} cy={yIc(s.ic)} r={3} className="trend-ic-dot" />}
            {s.icir !== null && <circle cx={xs[i]} cy={yIcir(s.icir)} r={3} className="trend-icir-dot" />}
            <text x={xs[i]} y={H - M.b + 16} className="tick" textAnchor="middle">G{s.gen}</text>
          </g>
        ))}
        <text x={M.l - 6} y={M.t + 4} className="tick" textAnchor="end">IC</text>
        <text x={W - M.r + 6} y={M.t + 4} className="tick">ICIR</text>
      </svg>
      <div className="legend">
        <li><i className="sw ic" />|IC| 中位</li>
        <li><i className="sw icir" />|ICIR| 中位</li>
        <li><i className="sw pass" />通过率</li>
      </div>
    </figure>
  );
}
```

(上面 `line`/`norm` 两行是推导残留,实现时删除,只用 `yIc`/`yIcir` 真代码。)

- [ ] **Step 4: 接进 App + tsc + 提交**

```tsx
<div className="chart-grid">
  <Scatter factors={data.factors} selected={filters.selected}
           onSelect={xname => setFilters(f => ({ ...f, selected: xname }))} />
  <StatusChart factors={data.factors} />
</div>
<Trend factors={data.factors} edges={data.lineage_edges} />
```

```bash
cd dashboard/frontend && npx tsc --noEmit
git add dashboard/frontend/src
git commit -m "feat(dashboard): scatter with median crosshair + generation trend charts"
```

### Task 9: 血缘树(横向 + 可折叠 + 搜索定位)—— 本重写的核心组件

**Files:**
- Create: `dashboard/frontend/src/components/LineageTree.tsx`
- Create: `dashboard/frontend/src/lib/lineage.ts`(纯函数,可单测)

- [ ] **Step 1: lineage.ts —— 布局纯函数(node test 跑)**

布局算法:横向 tidy tree。同一父的子节点按 y 紧排,父 y = 子 y 中点;深度→x。折叠状态作为输入。

```ts
// dashboard/frontend/src/lib/lineage.ts
import type { Factor, LineageEdge } from "../types";

export interface TreeNode {
  xname: string;
  label: string;        // 展示缩写
  status: string;
  icir: number | null;
  gatePass: boolean;
  children: TreeNode[];
  subtreeCount: number; // 折叠徽标用(含自身)
}

export interface LaidOutNode {
  node: TreeNode;
  x: number; y: number;        // 节点中心
  w: number; h: number;
  depth: number;
}

export interface LineageLayout {
  nodes: LaidOutNode[];
  edges: Array<{ from: LaidOutNode; to: LaidOutNode; outcome: string | null; operator: string | null }>;
}

export const NODE_W = 168, NODE_H = 40, COL_GAP = 64, ROW_GAP = 14;

export function buildTree(factors: Factor[], edges: LineageEdge[],
                          branch: string): { roots: TreeNode[]; byName: Map<string, TreeNode> } {
  const byName = new Map<string, TreeNode>();
  for (const f of factors) {
    byName.set(f.xname, {
      xname: f.xname, label: shortName(f.xname), status: f.status,
      icir: f.latest_icir, gatePass: f.gate_pass, children: [], subtreeCount: 1,
    });
  }
  const hasParent = new Set<string>();
  const childEdges = new Map<string, LineageEdge[]>();
  for (const e of edges) {
    if (!byName.has(e.parent_xname) || !byName.has(e.child_xname)) continue;
    if (!childEdges.has(e.parent_xname)) childEdges.set(e.parent_xname, []);
    childEdges.get(e.parent_xname)!.push(e);
    hasParent.add(e.child_xname);
  }
  // 分支归属:BFS from每个根(与旧实现一致)
  const rootOf = new Map<string, string>();
  const roots = [...byName.keys()].filter(n => !hasParent.has(n));
  const queue = [...roots];
  for (const r of roots) rootOf.set(r, r);
  while (queue.length) {
    const cur = queue.shift()!;
    for (const e of childEdges.get(cur) ?? []) {
      if (!rootOf.has(e.child_xname)) { rootOf.set(e.child_xname, rootOf.get(cur)!); queue.push(e.child_xname); }
    }
  }
  for (const n of byName.keys()) if (!rootOf.has(n)) rootOf.set(n, n);

  const visibleRoots: TreeNode[] = [];
  for (const r of roots) {
    if (branch !== "all" && rootOf.get(r) !== branch) continue;
    visibleRoots.push(byName.get(r)!);
  }
  // 挂子(环安全:已挂过的跳过)
  const attached = new Set<string>();
  function attach(name: string, seen: Set<string>) {
    if (seen.has(name) || attached.has(name)) return;
    seen.add(name); attached.add(name);
    const node = byName.get(name)!;
    for (const e of childEdges.get(name) ?? []) {
      if (seen.has(e.child_xname)) continue;
      attach(e.child_xname, seen);
      node.children.push(byName.get(e.child_xname)!);
    }
  }
  for (const r of visibleRoots) attach(r.xname, new Set());

  // 子树大小
  const size = (n: TreeNode): number => {
    n.subtreeCount = 1 + n.children.reduce((s, c) => s + size(c), 0);
    return n.subtreeCount;
  };
  visibleRoots.forEach(size);

  // 碎片根(不在所选分支):branch=all 时仍显示
  if (branch === "all") {
    for (const n of byName.keys()) {
      if (!attached.has(n)) visibleRoots.push(byName.get(n)!);
    }
    visibleRoots.forEach(r => { if (r.subtreeCount === 1) size(r); });
  }
  return { roots: visibleRoots, byName };
}

export function shortName(xname: string): string {
  // 截断到 22 字符,按驼峰/下划线断词优先
  if (xname.length <= 22) return xname;
  const cut = xname.slice(0, 22);
  const m = cut.match(/^.*?(?=[A-Z_])/g);
  return (m && m[0].length > 8 ? m[0] : cut) + "…";
}

export function layoutTree(roots: TreeNode[], collapsed: Set<string>): LineageLayout {
  const nodes: LaidOutNode[] = [];
  const edges: LineageLayout["edges"] = [];
  const levelGap = NODE_W + COL_GAP;

  function walk(node: TreeNode, depth: number): number {
    // 返回该子树占用的行数;叶子占 1 行
    const isCollapsed = collapsed.has(node.xname);
    const kids = isCollapsed ? [] : node.children;
    let rows: number;
    const laid: LaidOutNode = {
      node, x: 0, y: 0, w: NODE_W, h: NODE_H, depth,
    };
    if (!kids.length) {
      rows = 1;
      laid.y = nextY + rows / 2 - 0.5;
    } else {
      const childRows = kids.map(k => walk(k, depth + 1));
      rows = childRows.reduce((a, b) => a + b, 0);
      laid.y = 0; // 先占位,下面用子中点
    }
    laidOut.set(node.xname, laid);
    rowsByNode.set(node.xname, rows);
    nodes.push(laid);
    return rows;
  }
  // —— 实现说明:上面骨架展示意图;落地时用下述简单两遍法 ——
  // 第一遍 walk 只算每节点 rows(叶子1,内部=子rows和);
  // 第二遍 assign:全局游标 y=0,对每个可见节点:
  //   叶子:y = cursor + 0.5; cursor += 1
  //   折叠节点:同叶子
  //   内部:先递归 assign 子节点,父 y = (首子.y + 末子.y)/2
  //   x = depth * levelGap
  // 边:对每个可见父子对,产出 {from,to,outcome,operator}
  // (实现按此两遍法写,展开单测覆盖)
  ...
}

export function ancestorPath(target: string,
                             byName: Map<string, TreeNode>): string[] {
  // edges 反查链;由 LineageTree 传入 parentOf 更简单——见组件
  throw new Error("implemented in component via parentOf map");
}
```

**落地要求:** `layoutTree` 按上面"两遍法"注释完整实现(rows 计算 + y 游标分配 + 折叠节点同叶子 + 边收集),`ancestorPath` 改签名为 `ancestorPath(target: string, parentOf: Map<string, string>): string[]`,沿 parentOf 反向走到根,返回路径数组(含自身)。写完后补 node 单测(见 Step 2)。

- [ ] **Step 2: lineage.ts 的 node 单测(框架自带 vitest)**

`dashboard/frontend/src/lib/lineage.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildTree, layoutTree, shortName, ancestorPath, NODE_W, COL_GAP } from "./lineage";
import type { Factor, LineageEdge } from "../types";

const F = (xname: string, icir = 1): Factor => ({
  xname, class_name: null, file_path: null, formula_text: null, params: null,
  status: "evaluated", verdict: null, latest_ic: 0.1, latest_icir: icir,
  latest_sharpe: null, latest_rank_ic: null, latest_r2_x: 0.2, latest_res_ic: 0.01,
  created_ts: null, last_updated_ts: null, quality_score: null, quality_grade: null,
  intuition: null, anchor_text: null, origin_type: null, cohort_tag: null,
  operator_chain: null, evaluation_status: null, tags: [], resic_ic_ratio: 0.1,
  gate_pass: true, failed_gates: [], s_ic: 1, s_icir: 1, s_res_ic: 1, s_r2: 1, agg_score: 1,
});
const E = (p: string, c: string): LineageEdge => ({
  parent_xname: p, child_xname: c, relation_type: null, outcome: null,
  confidence: null, op_id: null, operator_name: null,
});

describe("shortName", () => {
  it("keeps short names", () => expect(shortName("Alpha")).toBe("Alpha"));
  it("truncates long names", () => {
    expect(shortName("VeryLongFactorNameThatExceedsLimit").length).toBeLessThanOrEqual(23);
  });
});

describe("buildTree", () => {
  it("builds parent-child and counts subtree", () => {
    const { roots, byName } = buildTree(
      [F("A"), F("B"), F("C")], [E("A", "B"), E("B", "C")], "all");
    expect(roots.map(r => r.xname)).toEqual(["A"]);
    expect(byName.get("A")!.subtreeCount).toBe(3);
    expect(byName.get("A")!.children[0].xname).toBe("B");
  });
  it("filters by branch", () => {
    const { roots } = buildTree([F("A"), F("B"), F("X")],
                                [E("A", "B")], "A");
    expect(roots.map(r => r.xname)).toEqual(["A"]);
  });
});

describe("layoutTree", () => {
  it("lays out leaves on distinct rows, parents centered", () => {
    // A -> (B -> D, B -> E, C)
    const { roots } = buildTree(
      [F("A"), F("B"), F("C"), F("D"), F("E")],
      [E("A", "B"), E("A", "C"), E("B", "D"), E("B", "E")], "all");
    const lay = layoutTree(roots, new Set());
    const y = (n: string) => lay.nodes.find(x => x.node.xname === n)!.y;
    expect(y("D")).not.toBe(y("E"));
    expect(y("B")).toBeCloseTo((y("D") + y("E")) / 2);
    expect(y("A")).toBeCloseTo((y("B") + y("C")) / 2);
    const x = (n: string) => lay.nodes.find(x => x.node.xname === n)!.x;
    expect(x("B") - x("A")).toBe(NODE_W + COL_GAP);
  });
  it("collapsed node hides descendants", () => {
    const { roots } = buildTree([F("A"), F("B"), F("C")],
                                [E("A", "B"), E("B", "C")], "all");
    const lay = layoutTree(roots, new Set(["B"]));
    expect(lay.nodes.map(n => n.node.xname)).not.toContain("C");
  });
});

describe("ancestorPath", () => {
  it("walks to root", () => {
    const parentOf = new Map([["C", "B"], ["B", "A"]]);
    expect(ancestorPath("C", parentOf)).toEqual(["A", "B", "C"]);
  });
});
```

跑:`cd dashboard/frontend && npx vitest run`(vite 模板自带 vitest 依赖;若没有,`npm i -D vitest` 并在 package.json scripts 加 `"test": "vitest run"`)。

- [ ] **Step 3: LineageTree 组件 —— 渲染 + zoom/pan + 折叠 + 搜索定位**

实现要点:
- props: `{ factors, edges, branches, branch, onBranchChange, selected, onSelect }`
- 内部 state:`collapsed: Set<string>`(默认:子节点数 ≥ 8 的节点折叠——44 节点分支默认只见前两层);`zoom transform`(d3-zoom);`search: string`
- SVG 结构:`<g transform={zoomTransform}>` 内渲染 edges(`path` 横向贝塞尔:M px py C mx py, mx cy, cx cy)+ nodes(foreignObject 或纯 SVG g:状态色圆点 + label 文本 + ICIR 徽标文本)
- 折叠节点右侧显示 `+N` 徽标(N=subtreeCount-1),点击展开;再点父节点折叠
- d3-zoom:`useEffect` 绑定 svg ref,`zoom().scaleExtent([0.2, 3]).on("zoom", e => setT(e.transform))`;双击空白重置;"适应视图"按钮:算 nodes 包围盒,`zoomIdentity.translate(...).scale(...)` fit
- 搜索命中:`ancestorPath` 得路径,路径上节点全部从 collapsed 移除,`selected` 设为命中项,视野平移到该节点
- 边样式:outcome improved/declined 绿/红;operator_name 非空虚线
- 悬停节点:高亮祖先链(path 上所有节点加 class)+ 直接子边加粗

组件骨架(落地时补全渲染细节):

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import { buildTree, layoutTree, ancestorPath, NODE_W, NODE_H, COL_GAP, ROW_GAP } from "../lib/lineage";
import { STATUS_COLORS, STATUS_LABELS } from "../charts/colors";
import type { Factor, LineageBranch, LineageEdge } from "../types";

interface Props {
  factors: Factor[];
  edges: LineageEdge[];
  branches: LineageBranch[];
  branch: string;
  onBranchChange: (b: string) => void;
  selected: string | null;
  onSelect: (xname: string | null) => void;
}

export function LineageTree({ factors, edges, branches, branch,
                              onBranchChange, selected, onSelect }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [t, setT] = useState(zoomIdentity);
  const [search, setSearch] = useState("");

  const { layout, parentOf } = useMemo(() => {
    const { roots, byName } = buildTree(factors, edges, branch);
    // 默认折叠:直接子数>=8 的节点收起(首次进入才有——用 ref 标记)
    const parentMap = new Map(edges.map(e => [e.child_xname, e.parent_xname]));
    return { layout: layoutTree(roots, collapsed), parentOf: parentMap };
  }, [factors, edges, branch, collapsed]);

  // d3-zoom 绑定
  useEffect(() => {
    if (!svgRef.current) return;
    const zb: ZoomBehavior<SVGSVGElement, unknown> = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 3])
      .on("zoom", e => setT(e.transform));
    select(svgRef.current).call(zb).on("dblclick.zoom", null);
    return () => { select(svgRef.current).on(".zoom", null); };
  }, []);

  const fit = () => {
    if (!svgRef.current || !layout.nodes.length) return;
    const xs = layout.nodes.map(n => n.x), ys = layout.nodes.map(n => n.y);
    const minX = Math.min(...xs) - NODE_W, maxX = Math.max(...xs) + NODE_W;
    const minY = Math.min(...ys) - NODE_H, maxY = Math.max(...ys) + NODE_H;
    const box = svgRef.current.getBoundingClientRect();
    const k = Math.min(box.width / (maxX - minX), box.height / (maxY - minY), 1.2);
    const nx = (minX + maxX) / 2, ny = (minY + maxY) / 2;
    const sel = select(svgRef.current);
    (sel as any).call(zoom().transform, zoomIdentity
      .translate(box.width / 2 - k * nx, box.height / 2 - k * ny).scale(k));
  };

  const runSearch = () => {
    const hit = factors.find(f =>
      f.xname.toLowerCase().includes(search.trim().toLowerCase()));
    if (!hit) return;
    const path = ancestorPath(hit.xname, parentOf);
    setCollapsed(prev => {
      const next = new Set([...prev].filter(n => !path.includes(n)));
      return next;
    });
    onSelect(hit.xname);
    // 平移到节点:直接 fit 到该节点邻域或简化为整体 fit
    requestAnimationFrame(fit);
  };

  const toggle = (xname: string) =>
    setCollapsed(prev => {
      const next = new Set(prev);
      next.has(xname) ? next.delete(xname) : next.add(xname);
      return next;
    });

  // 渲染:edges paths + node <g>(rect + 状态点 + label + icir 徽标 + 折叠 +N)
  return (
    <section className="section lineage">
      {/* 控制条:branch select + 搜索框 + 适应按钮 */}
      <svg ref={svgRef} className="lineage-svg" viewBox={undefined}>
        <g transform={`translate(${t.x},${t.y}) scale(${t.k})`}>
          {layout.edges.map((e, i) => (
            <path key={i} className={`ledge${e.outcome === "improved" ? " up" : e.outcome === "declined" ? " down" : ""}${e.operator ? " op" : ""}`}
                  d={edgePath(e)} />
          ))}
          {layout.nodes.map(n => (
            <NodeCard key={n.node.xname} n={n} collapsed={collapsed.has(n.node.xname)}
                      selected={selected === n.node.xname}
                      onToggle={() => toggle(n.node.xname)}
                      onSelect={() => onSelect(n.node.xname)} />
          ))}
        </g>
      </svg>
    </section>
  );
}

function edgePath(e: { from: { x: number; y: number; w: number }, to: { x: number; y: number } }): string {
  const x1 = e.from.x + e.from.w / 2, y1 = e.from.y;
  const x2 = e.to.x - NODE_W / 2, y2 = e.to.y;
  const mx = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
}
```

`NodeCard` 子组件(同文件):rect + 左上状态色点 + label(text) + 右侧 ICIR 值 + 折叠时右缘 `+N` 徽标;`onClick` 触发 onSelect,`onDoubleClick` 或点徽标触发 toggle。

- [ ] **Step 4: 接进 App + vitest + tsc + 提交**

```bash
cd dashboard/frontend && npx vitest run && npx tsc --noEmit
git add dashboard/frontend/src
git commit -m "feat(dashboard): horizontal collapsible lineage tree with zoom + search-locate"
```

### Task 10: FactorTable + 多维筛选栏

**Files:**
- Create: `dashboard/frontend/src/lib/filter.ts`(纯函数 + 单测)
- Create: `dashboard/frontend/src/components/FactorTable.tsx`
- Create: `dashboard/frontend/src/components/FilterBar.tsx`

- [ ] **Step 1: filter.ts 纯函数**

```ts
import type { Factor } from "../types";
import type { FilterState } from "../state";

export function operatorChainLength(f: Factor): number | null {
  const raw = f.operator_chain?.trim();
  if (!raw) return f.operator_chain === null || f.operator_chain === undefined ? null : 0;
  return raw.split(/[->+·]+/).filter(Boolean).length;
}

export function applyFilters(factors: Factor[], fl: FilterState): Factor[] {
  const q = fl.q.trim().toLowerCase();
  return factors.filter(f => {
    if (q) {
      const hay = [f.xname, f.formula_text, f.intuition,
                   ...f.tags.map(t => t.name)].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (fl.status.length && !fl.status.includes(f.status)) return false;
    if (fl.tags.length && !f.tags.some(t => fl.tags.includes(t.name))) return false;
    if (fl.gates.length) {
      if (fl.gates.includes("pass") && !f.gate_pass) return false;
      for (const g of fl.gates.filter(g => g !== "pass")) {
        if (f.failed_gates.includes(g)) return false;
      }
    }
    if (fl.origin.length) {
      const o = f.origin_type ?? f.class_name ?? "";
      if (!fl.origin.some(v => o === v || f.class_name === v)) return false;
    }
    const ocl = operatorChainLength(f);
    if (fl.opChainMin !== null && (ocl === null || ocl < fl.opChainMin)) return false;
    if (fl.opChainMax !== null && (ocl === null || ocl > fl.opChainMax)) return false;
    if (fl.createdFrom && (f.created_ts ?? "") < fl.createdFrom) return false;
    if (fl.createdTo && (f.created_ts ?? "9999") > fl.createdTo + "T23:59:59") return false;
    return true;
  });
}

export function sortFactors(factors: Factor[], key: string, dir: "asc" | "desc"): Factor[] {
  const mul = dir === "asc" ? 1 : -1;
  const val = (f: Factor): number | string | null => {
    const v = (f as unknown as Record<string, unknown>)[key];
    return typeof v === "number" ? v : typeof v === "string" ? v : null;
  };
  return [...factors].sort((a, b) => {
    const va = val(a), vb = val(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;          // null 沉底(不受 dir 影响)
    if (vb === null) return -1;
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * mul;
    return String(va).localeCompare(String(vb)) * mul;
  });
}
```

- [ ] **Step 2: filter 单测**

`dashboard/frontend/src/lib/filter.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { applyFilters, sortFactors, operatorChainLength } from "./filter";
import { DEFAULT_FILTERS } from "../state";
import type { Factor } from "../types";

const F = (over: Partial<Factor>): Factor => ({
  xname: "X", class_name: null, file_path: null, formula_text: null, params: null,
  status: "evaluated", verdict: null, latest_ic: null, latest_icir: null,
  latest_sharpe: null, latest_rank_ic: null, latest_r2_x: null, latest_res_ic: null,
  created_ts: "2026-08-01 10:00:00", last_updated_ts: null, quality_score: null,
  quality_grade: null, intuition: null, anchor_text: null, origin_type: null,
  cohort_tag: null, operator_chain: null, evaluation_status: null, tags: [],
  resic_ic_ratio: null, gate_pass: false, failed_gates: [], s_ic: null,
  s_icir: null, s_res_ic: null, s_r2: null, agg_score: null, ...over,
});

describe("operatorChainLength", () => {
  it("null chain → null", () => expect(operatorChainLength(F({}))).toBeNull());
  it("splits operators", () =>
    expect(operatorChainLength(F({ operator_chain: "rank->tsmean->zscore" }))).toBe(3));
});

describe("applyFilters", () => {
  it("text search hits formula/tags/intuition", () => {
    const list = [F({ xname: "A" }), F({ xname: "B", formula_text: "rank(imbalance)" }),
                  F({ xname: "C", tags: [{ name: "order_book", description: null }] })];
    expect(applyFilters(list, { ...DEFAULT_FILTERS, q: "order" }).map(f => f.xname))
      .toEqual(["C"]);
    expect(applyFilters(list, { ...DEFAULT_FILTERS, q: "imbalance" }).map(f => f.xname))
      .toEqual(["B"]);
  });
  it("gate combo requires pass and no failed sub-gate", () => {
    const list = [F({ xname: "A", gate_pass: true, failed_gates: [] }),
                  F({ xname: "B", gate_pass: false, failed_gates: ["ic", "r2"] }),
                  F({ xname: "C", gate_pass: false, failed_gates: ["r2"] })];
    expect(applyFilters(list, { ...DEFAULT_FILTERS, gates: ["pass", "ic"] }).map(f => f.xname))
      .toEqual(["A"]);
  });
  it("op-chain range excludes null", () => {
    const list = [F({ xname: "A" }), F({ xname: "B", operator_chain: "rank->zscore" })];
    expect(applyFilters(list, { ...DEFAULT_FILTERS, opChainMin: 1 }).map(f => f.xname))
      .toEqual(["B"]);
  });
  it("created date range", () => {
    const list = [F({ xname: "A", created_ts: "2026-07-15 08:00:00" }),
                  F({ xname: "B", created_ts: "2026-08-20 08:00:00" })];
    expect(applyFilters(list, { ...DEFAULT_FILTERS, createdFrom: "2026-08-01" }).map(f => f.xname))
      .toEqual(["B"]);
  });
});

describe("sortFactors", () => {
  it("numeric desc with nulls sunk", () => {
    const list = [F({ xname: "A", agg_score: null }), F({ xname: "B", agg_score: 0.5 }),
                  F({ xname: "C", agg_score: 0.9 })];
    expect(sortFactors(list, "agg_score", "desc").map(f => f.xname)).toEqual(["C", "B", "A"]);
  });
});
```

- [ ] **Step 3: FilterBar 组件 —— 多选下拉(自绘,不用原生 multiple)**

实现要点:
- props: `{ factors: Factor[]; filters: FilterState; onChange: (patch: Partial<FilterState>) => void; onReset: () => void }`
- 文本搜索 input(q)
- 状态多选、标签多选、来源多选、闸门组合:统一的 `MultiSelect` 子组件(同文件)——按钮 + 弹出 checkbox 列表,选项从数据派生(statuses = uniq(factors.status);tags = uniq(tags);origin = uniq(origin_type/class_name);gates = ["pass","ic","icir","res_ic","r2"])
- 算子链:两个 number input(min/max)
- 创建时间:两个 date input(from/to)
- 每个非默认维度在按钮上显示计数徽标;顶部"重置"清全部
- 任何变更 `onChange({...})` 由 App 合并进 filters(自动写 hash)

```tsx
import { useEffect, useRef, useState } from "react";
import type { Factor } from "../types";
import type { FilterState } from "../state";

interface Props {
  factors: Factor[];
  filters: FilterState;
  onChange: (patch: Partial<FilterState>) => void;
  onReset: () => void;
}

const GATE_OPTIONS = [
  { value: "pass", label: "闸门全过" },
  { value: "ic", label: "IC 达标" },
  { value: "icir", label: "ICIR 达标" },
  { value: "res_ic", label: "残差IC 达标" },
  { value: "r2", label: "R² 达标" },
];

function MultiSelect({ label, options, selected, onToggle }: {
  label: string; options: { value: string; label?: string }[];
  selected: string[]; onToggle: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", away);
    return () => document.removeEventListener("click", away);
  }, []);
  return (
    <div className="ms" ref={ref}>
      <button className={`ms-btn${selected.length ? " active" : ""}`} onClick={() => setOpen(o => !o)}>
        {label}{selected.length ? ` · ${selected.length}` : ""} ▾
      </button>
      {open && (
        <div className="ms-pop">
          {options.map(o => (
            <label key={o.value}>
              <input type="checkbox" checked={selected.includes(o.value)}
                     onChange={() => onToggle(o.value)} />
              {o.label ?? o.value}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function FilterBar({ factors, filters, onChange, onReset }: Props) {
  const uniq = (xs: (string | null | undefined)[]) =>
    [...new Set(xs.filter((v): v is string => !!v))].sort();
  const toggle = (key: "status" | "tags" | "gates" | "origin") => (v: string) => {
    const cur = filters[key];
    onChange({ [key]: cur.includes(v) ? cur.filter(x => x !== v) : [...cur, v] } as Partial<FilterState>);
  };
  return (
    <div className="filter-bar">
      <input className="search" type="search" placeholder="搜索因子、公式、标签或意图"
             value={filters.q} onChange={e => onChange({ q: e.target.value })} />
      <MultiSelect label="状态" options={uniq(factors.map(f => f.status)).map(v => ({ value: v }))}
                   selected={filters.status} onToggle={toggle("status")} />
      <MultiSelect label="标签" options={uniq(factors.flatMap(f => f.tags.map(t => t.name))).map(v => ({ value: v }))}
                   selected={filters.tags} onToggle={toggle("tags")} />
      <MultiSelect label="闸门" options={GATE_OPTIONS} selected={filters.gates} onToggle={toggle("gates")} />
      <MultiSelect label="来源" options={uniq([...factors.map(f => f.origin_type), ...factors.map(f => f.class_name)]).map(v => ({ value: v }))}
                   selected={filters.origin} onToggle={toggle("origin")} />
      <label className="range">算子链
        <input type="number" min={0} value={filters.opChainMin ?? ""}
               onChange={e => onChange({ opChainMin: e.target.value === "" ? null : Number(e.target.value) })} />–
        <input type="number" min={0} value={filters.opChainMax ?? ""}
               onChange={e => onChange({ opChainMax: e.target.value === "" ? null : Number(e.target.value) })} />
      </label>
      <label className="range">创建
        <input type="date" value={filters.createdFrom ?? ""}
               onChange={e => onChange({ createdFrom: e.target.value || null })} />–
        <input type="date" value={filters.createdTo ?? ""}
               onChange={e => onChange({ createdTo: e.target.value || null })} />
      </label>
      <button className="action" onClick={onReset}>重置</button>
    </div>
  );
}
```

- [ ] **Step 4: FactorTable —— 排序表头 + CSV 导出 + 行点击选中**

列(与旧版一致):因子 / 结论 / 聚合分 / IC / ICIR / R² / 残差IC / 残差IC/IC / 更新时间。

```tsx
import { useMemo } from "react";
import { applyFilters, sortFactors } from "../lib/filter";
import { STATUS_LABELS } from "../charts/colors";
import type { Factor } from "../types";
import type { FilterState } from "../state";

interface Props {
  factors: Factor[];
  filters: FilterState;
  onSort: (key: string) => void;
  onSelect: (xname: string | null) => void;
}

const COLS: Array<{ key: string; label: string; num?: boolean; title?: string }> = [
  { key: "xname", label: "因子" },
  { key: "verdict", label: "结论" },
  { key: "agg_score", label: "聚合分", num: true,
    title: "|IC|/0.15 + |ICIR|/8 + |残差IC|/0.015 + (0.7-R²)/0.7 各截断[0,1]等权平均" },
  { key: "latest_ic", label: "IC", num: true },
  { key: "latest_icir", label: "ICIR", num: true },
  { key: "latest_r2_x", label: "R²", num: true },
  { key: "latest_res_ic", label: "残差IC", num: true },
  { key: "resic_ic_ratio", label: "残差IC/IC", num: true },
  { key: "last_updated_ts", label: "更新时间" },
];

export function FactorTable({ factors, filters, onSort, onSelect }: Props) {
  const rows = useMemo(
    () => sortFactors(applyFilters(factors, filters), filters.sortKey, filters.sortDir),
    [factors, filters]);

  const exportCsv = () => {
    const head = COLS.map(c => c.key).join(",");
    const lines = rows.map(r => COLS.map(c => {
      const v = (r as unknown as Record<string, unknown>)[c.key];
      return v === null || v === undefined ? "" : `"${String(v).replace(/"/g, '""')}"`;
    }).join(","));
    const blob = new Blob(["﻿" + [head, ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "factors.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <section className="section">
      <div className="section-header">
        <h2>因子列表 <span className="count">{rows.length}</span></h2>
        <button className="action" onClick={exportCsv}>CSV</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {COLS.map(c => (
                <th key={c.key} className={c.num ? "num" : ""} title={c.title}>
                  <button className={`sort-header${filters.sortKey === c.key ? " active" : ""}`}
                          onClick={() => onSort(c.key)}>
                    {c.label}
                    {filters.sortKey === c.key && <span>{filters.sortDir === "asc" ? " ↑" : " ↓"}</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.xname}
                  className={filters.selected === r.xname ? "selected" : ""}
                  onClick={() => onSelect(filters.selected === r.xname ? null : r.xname)}>
                <td className="mono">{r.xname}</td>
                <td><span className={`verdict ${r.verdict ?? ""}`}>{r.verdict ?? "—"}</span></td>
                <td className="num">{r.agg_score?.toFixed(3) ?? "—"}</td>
                <td className="num">{r.latest_ic?.toFixed(4) ?? "—"}</td>
                <td className="num">{r.latest_icir?.toFixed(2) ?? "—"}</td>
                <td className="num">{r.latest_r2_x?.toFixed(2) ?? "—"}</td>
                <td className="num">{r.latest_res_ic?.toFixed(4) ?? "—"}</td>
                <td className="num">{r.resic_ic_ratio?.toFixed(2) ?? "—"}</td>
                <td className="num dim">{r.last_updated_ts?.slice(0, 10) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
```

(渲染行数 88,不做虚拟滚动——YAGNI。)

- [ ] **Step 5: 接进 App + vitest + tsc + 提交**

App.tsx `<main>` 加(排序点击:同列翻转方向,换列重置 desc):

```tsx
<FilterBar factors={data.factors} filters={filters}
           onChange={patch => setFilters(f => ({ ...f, ...patch }))}
           onReset={() => setFilters(f => ({ ...DEFAULT_FILTERS, selected: f.selected, branch: f.branch }))} />
<FactorTable factors={data.factors} filters={filters}
             onSort={key => setFilters(f => ({
               ...f, sortKey: key,
               sortDir: f.sortKey === key ? (f.sortDir === "asc" ? "desc" : "asc") : "desc",
             }))}
             onSelect={xname => setFilters(f => ({ ...f, selected: xname }))} />
```

```bash
cd dashboard/frontend && npx vitest run && npx tsc --noEmit
git add dashboard/frontend/src
git commit -m "feat(dashboard): multi-dimension filter bar + sortable factor table + CSV export"
```

### Task 11: DetailPanel(因子详情)

**Files:**
- Create: `dashboard/frontend/src/components/DetailPanel.tsx`

- [ ] **Step 1: 详情面板 —— 指标栅格 + 标签 + 意图 + 演化路径**

实现要点(数据都已在 snapshot 里):
- props: `{ factor: Factor | null; iterations: Iteration[]; lessons: Lesson[]; onClose: () => void }`
- 指标栅格:IC/ICIR/R²/残差IC/残差IC比/聚合分 + 各分项分(s_ic 等,4 个小进度条)
- 标签 chips;意图(intuition)、锚文本(anchor_text)、公式(formula_text)代码块
- 演化路径:沿 iterations 的 from/to 链(从当前因子向根回溯,同 ancestorPath 思路,由父级传 parentOf 或在这里重建),每步显示 change_note + outcome 徽标 + icir_delta(绿/红)
- 相关 lessons:factor_xname 匹配的 lessons 列表(type + text)
- 布局:桌面右侧固定栏(sticky aside),窄屏底部滑出(CSS 处理);关闭按钮清 selected

```tsx
import type { Factor, Iteration, Lesson } from "../types";

interface Props {
  factor: Factor | null;
  iterations: Iteration[];
  lessons: Lesson[];
  parentOf: Map<string, string>;
  onClose: () => void;
}

function Bar({ label, v }: { label: string; v: number | null }) {
  return (
    <div className="subscore">
      <span>{label}</span>
      <div className="track"><div className="fill" style={{ width: `${(v ?? 0) * 100}%` }} /></div>
      <b>{v === null ? "—" : v.toFixed(2)}</b>
    </div>
  );
}

export function DetailPanel({ factor, iterations, lessons, parentOf, onClose }: Props) {
  if (!factor) return null;
  const path: string[] = [];
  let cur: string | undefined = factor.xname;
  while (cur && !path.includes(cur)) { path.unshift(cur); cur = parentOf.get(cur); }
  const steps = path.slice(1).map((name, i) => {
    const it = iterations.find(t => t.to_xname === name && t.from_xname === path[i]);
    return { name, it };
  });
  const rel = lessons.filter(l => l.factor_xname === factor.xname);
  const fmt = (v: number | null | undefined, d = 3) =>
    v === null || v === undefined ? "—" : v.toFixed(d);
  return (
    <aside className="detail-panel" aria-live="polite">
      <header>
        <h3 className="mono">{factor.xname}</h3>
        <button className="icon-button" onClick={onClose} title="关闭">✕</button>
      </header>
      <div className="detail-metrics">
        <div><span>IC</span><b>{fmt(factor.latest_ic, 4)}</b></div>
        <div><span>ICIR</span><b>{fmt(factor.latest_icir, 2)}</b></div>
        <div><span>R²</span><b>{fmt(factor.latest_r2_x, 2)}</b></div>
        <div><span>残差IC</span><b>{fmt(factor.latest_res_ic, 4)}</b></div>
        <div><span>残差IC/IC</span><b>{fmt(factor.resic_ic_ratio, 2)}</b></div>
        <div><span>聚合分</span><b>{fmt(factor.agg_score)}</b></div>
      </div>
      <Bar label="IC 分" v={factor.s_ic} />
      <Bar label="ICIR 分" v={factor.s_icir} />
      <Bar label="残差IC 分" v={factor.s_res_ic} />
      <Bar label="R² 分" v={factor.s_r2} />
      {factor.tags.length > 0 && (
        <div className="chips">{factor.tags.map(t => <span key={t.name} className="chip">{t.name}</span>)}</div>
      )}
      {factor.formula_text && (
        <section><h4>公式</h4><pre className="code">{factor.formula_text}</pre></section>
      )}
      {factor.intuition && (
        <section><h4>意图</h4><p>{factor.intuition}</p></section>
      )}
      {steps.length > 0 && (
        <section>
          <h4>演化路径</h4>
          <ol className="evo">
            {steps.map(({ name, it }) => (
              <li key={name}>
                <span className="mono">{name}</span>
                {it && <>
                  <em>{it.change_note ?? it.reason ?? ""}</em>
                  <b className={it.outcome === "improved" ? "up" : it.outcome === "declined" ? "down" : ""}>
                    {it.outcome ?? ""}{it.icir_delta != null ? ` ${it.icir_delta > 0 ? "+" : ""}${it.icir_delta.toFixed(2)}` : ""}
                  </b>
                </>}
              </li>
            ))}
          </ol>
        </section>
      )}
      {rel.length > 0 && (
        <section>
          <h4>相关教训 ({rel.length})</h4>
          <ul className="lessons">{rel.map(l => <li key={l.id}><i>{l.type}</i>{l.text}</li>)}</ul>
        </section>
      )}
    </aside>
  );
}
```

- [ ] **Step 2: 接进 App(parentOf 从 lineage_edges 建一次)+ tsc + 提交**

```tsx
const parentOf = useMemo(
  () => new Map(data.lineage_edges.map(e => [e.child_xname, e.parent_xname])),
  [data.lineage_edges]);
// <main> 之后:
<DetailPanel factor={data.factors.find(f => f.xname === filters.selected) ?? null}
             iterations={data.iterations} lessons={data.lessons}
             parentOf={parentOf}
             onClose={() => setFilters(f => ({ ...f, selected: null }))} />
```

```bash
cd dashboard/frontend && npx tsc --noEmit
git add dashboard/frontend/src
git commit -m "feat(dashboard): factor detail panel — metrics, subscores, evolution path, lessons"
```

---

## Phase 5:设计系统 + 退役旧链路 + 交付

### Task 12: 全局 CSS 设计系统(视觉重做落点)

**Files:**
- Create: `dashboard/frontend/src/styles/global.css`(替换 App.css/index.css 演示样式)

- [ ] **Step 1: 设计 tokens + 组件样式(完整写,替换脚手架 css)**

设计语言:交易终端——近黑底、密度分层、等宽数字、荧光数据色。关键内容(落地时以此为骨架补全所有 class):

```css
/* ============ Factor Terminal — design tokens ============ */
:root {
  color-scheme: dark;
  --bg: #0b0f16;
  --panel: #111825;
  --raised: #18212f;
  --border: #243044;
  --border-strong: #33425c;
  --up: #2dd4a7;
  --up-dim: rgba(45, 212, 167, .13);
  --down: #f87171;
  --down-dim: rgba(248, 113, 113, .13);
  --accent: #38bdf8;
  --accent-dim: rgba(56, 189, 248, .12);
  --warn: #fbbf24;
  --violet: #c084fc;
  --ink: #e9eef6;
  --ink-dim: #9fb0c4;
  --ink-faint: #6d7d93;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  --sans: -apple-system, "Segoe UI", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  --radius: 10px;
}
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.55 var(--sans); color: var(--ink);
       background: radial-gradient(1100px 460px at 72% -8%, rgba(56,189,248,.05), transparent 60%), var(--bg); }
.mono, td.num, .metric-value { font-family: var(--mono); font-variant-numeric: tabular-nums; }

/* header / 布局骨架 / metrics 卡 / chart-box / grid / median / crosshair /
   dot / hover-card / lineage svg(node/edge/legend) / filter-bar / ms-pop /
   table / verdict 徽标 / detail-panel / subscore track / chips / evo /
   stale-badge(呼吸动画) / load-dot / @media print —— 按组件 class 逐一补全,
   行为要求:
   - .stale-badge.show button: box-shadow 呼吸 keyframes(1.6s ease-in-out infinite)
   - .dot-wrap { transition: transform .3s ease }
   - .dot { transition: r .2s, filter .2s } .dot.hot { filter: drop-shadow(0 0 6px var(--accent)) }
   - .dot.glow { stroke: var(--up); stroke-width: 1.5 }
   - tr.selected { background: var(--accent-dim) }
   - .ledge.up { stroke: var(--up) } .ledge.down { stroke: var(--down) }
   - .ledge.op { stroke-dasharray: 5 4 }
   - @media print { .app-header .header-actions, .filter-bar, .stale-badge { display: none } }
*/
```

**落地要求:** 上述注释里列出的每个 class 都要有实际规则(网格布局 `.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:16px}`,`.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}`,`.chart-grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:12px}`,表格斑马纹+悬停行亮起,等宽数字右对齐,谱系节点卡片含状态点/label/ICIR/折叠徽标,hover-card 绝对定位毛玻璃)。写完删除脚手架的 App.css/index.css 引用,main.tsx 只引 `./styles/global.css`。

- [ ] **Step 2: 视觉自查(构建后浏览器过一遍)**

```bash
cd dashboard/frontend && npm run build
cd .. && python3 server.py --port 8901 &
# 浏览器开 http://127.0.0.1:8901 逐项核对:
# header/指标卡/散点悬停十字线/状态条/趋势/血缘(折叠-展开-搜索-适应)/
# 筛选(每个维度)/表格排序/详情面板/CSV/打印预览/窄屏(拖窄到 900px)
```

- [ ] **Step 3: 提交**

```bash
git add dashboard/frontend/src
git commit -m "feat(dashboard): terminal design system — tokens, charts, lineage, table styling"
```

### Task 13: 退役旧链路 + Docker 化

**Files:**
- Create: `dashboard/Dockerfile`
- Modify: `dashboard-server/docker-compose.yml` → 路径指向新构建(或整体挪到 `dashboard/docker-compose.yml`)
- Delete/归档: `dashboard-server/`、`core/tools/generate_factor_dashboard.py` 渲染部分、`core/tools/dashboard_template/`

- [ ] **Step 1: 旧文件进 attic(git mv 语义用 mv + git add)**

```bash
mkdir -p attic/dashboard-legacy-20260828
git mv core/tools/dashboard_template attic/dashboard-legacy-20260828/dashboard_template
git mv dashboard-server/serve.py attic/dashboard-legacy-20260828/serve.py
git mv dashboard-server/entrypoint.sh attic/dashboard-legacy-20260828/entrypoint.sh
git mv dashboard-server/Dockerfile attic/dashboard-legacy-20260828/Dockerfile
git mv dashboard-server/docker-compose.yml attic/dashboard-legacy-20260828/docker-compose.yml
git mv core/tools/generate_factor_dashboard.py attic/dashboard-legacy-20260828/generate_factor_dashboard.py
git mv core/tools/test_generate_factor_dashboard.py attic/dashboard-legacy-20260828/test_generate_factor_dashboard.py
rmdir dashboard-server
```

- [ ] **Step 2: Dockerfile(dist 本地构建,镜像零 node)**

`dashboard/Dockerfile`:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY core/config.py /app/core/config.py
COPY core/db/__init__.py /app/core/db/__init__.py 2>/dev/null || true
COPY core/db/db.py /app/core/db/db.py
COPY core/tools/dashboard_snapshot.py /app/core/tools/dashboard_snapshot.py
RUN touch /app/core/__init__.py /app/core/tools/__init__.py
COPY dashboard/server.py /app/dashboard/server.py
RUN touch /app/dashboard/__init__.py
COPY dashboard/frontend/dist /app/dashboard/frontend/dist
ENV PYTHONUNBUFFERED=1 DASHBOARD_PORT=8765
EXPOSE 8765
CMD ["python3", "/app/dashboard/server.py"]
```

注意:先查 `core/db/__init__.py` 是否存在再定 COPY 行(上面 `|| true` 写法 Docker 不支持条件,落地时按实际情况删掉该行或保留存在的文件);`dashboard_snapshot.py` 依赖 `core.db.db` 里 leaderboard_gates——确认 db.py 无第三方 import(它是纯 sqlite3 模块才能直接 COPY;若有依赖则把 gates 常量与函数一并下沉进 dashboard_snapshot.py,改完跑 `python3 dashboard/test_server.py` 验证)。

- [ ] **Step 3: docker-compose.yml**

`dashboard/docker-compose.yml`:

```yaml
services:
  dashboard:
    build:
      context: ..
      dockerfile: dashboard/Dockerfile
    image: factor-dashboard:2
    container_name: factor-dashboard
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - ../data:/app/data:ro
    environment:
      DASHBOARD_PORT: "8765"
```

**db 路径注意:** 容器内 db 在 `/app/data/factors.db`,而 `DEFAULT_DB` 来自 `core/config.py` 的 `DATA_DIR`——检查 config.py 的 DATA_DIR 解析逻辑,若它不指向 `/app/data`,在 compose environment 加 `FACTORS_DB=/app/data/factors.db` 之类(以 config.py 实际支持的环境变量为准;若不支持,server.py main 里把 `--db` 默认值改为 `os.environ.get("FACTORS_DB", str(DEFAULT_DB))`)。

- [ ] **Step 4: 全链路验证**

```bash
cd dashboard/frontend && npm run build && cd ../..
docker compose -f dashboard/docker-compose.yml down 2>/dev/null; docker stop factor-dashboard 2>/dev/null; docker rm factor-dashboard 2>/dev/null
docker compose -f dashboard/docker-compose.yml up -d --build
sleep 2
curl -s http://127.0.0.1:8765/ | grep -o "<title>[^<]*</title>"
curl -s -D- -o /dev/null http://127.0.0.1:8765/api/snapshot | grep -i etag
```

预期:页面 title 正常;ETag 存在;浏览器开 8765 全功能可用;`docker logs factor-dashboard` 无堆栈。

- [ ] **Step 5: 回归 + 提交**

```bash
python3 core/tools/test_dashboard_snapshot.py && python3 dashboard/test_server.py
git add -A && git commit -m "feat(dashboard): retire legacy static pipeline, ship dockerized v2"
```

### Task 14: 收尾 —— README + 验收清单

**Files:**
- Create: `dashboard/README.md`

- [ ] **Step 1: README**

```markdown
# 因子库看板 v2

实时 API + React 前端。永不整页刷新。

## 本地开发
    # 终端1: API(仓库根)
    python3 dashboard/server.py --port 8901
    # 终端2: 前端
    cd dashboard/frontend && npm install && npm run dev
    # 打开 http://localhost:5173 (vite 代理 /api → 8901)

## 构建与部署
    cd dashboard/frontend && npm run build
    docker compose -f dashboard/docker-compose.yml up -d --build
    # 访问 http://<host>:8765

## 行为
- 数据更新只亮角标,点击应用;筛选/滚动/选中永不丢失
- 筛选/选中/分支同步 URL hash,刷新页面可恢复
- /api/snapshot 带 ETag;db (mtime,size) 未变 → 304 不重算

## 测试
    python3 core/tools/test_dashboard_snapshot.py
    python3 dashboard/test_server.py
    cd dashboard/frontend && npx vitest run && npx tsc --noEmit
```

- [ ] **Step 2: 最终验收清单(spec 对照)**

- [ ] 页面无任何 `location.reload()`(`grep -r "location.reload" dashboard/frontend/src` 为空)
- [ ] 改 db 后 60s 内角标亮,点应用数据更新,滚动位置不动
- [ ] 筛选多维度组合生效且写进 URL hash;刷新页面状态恢复
- [ ] 血缘:44 节点分支默认可读(前两层)、折叠/展开、搜索定位高亮祖先链、zoom/pan/适应
- [ ] 散点悬停十字线+数据卡;趋势图双轴;指标卡 sparkline
- [ ] 表格全列排序 + CSV 导出
- [ ] 详情面板:指标/分项分/标签/公式/意图/演化路径/教训
- [ ] 打印样式可看
- [ ] docker compose up 后 8765 端口全功能
- [ ] `python3 core/tools/test_dashboard_snapshot.py && python3 dashboard/test_server.py && cd dashboard/frontend && npx vitest run` 全绿

- [ ] **Step 3: 提交**

```bash
git add dashboard/README.md
git commit -m "docs(dashboard): v2 readme — dev, build, deploy, behaviors"
```

---

## 任务依赖图

```
T1 → T2 → T3 → T4 → T5 → T6 → {T7, T8} → T9 → T10 → T11 → T12 → T13 → T14
                                (T7/T8 可并行)
```
