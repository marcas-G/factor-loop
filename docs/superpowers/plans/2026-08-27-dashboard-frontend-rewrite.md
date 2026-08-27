# 因子库看板前端重写 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按设计文档 `docs/superpowers/specs/2026-08-27-dashboard-frontend-rewrite-design.md` 重写看板前端：模板拆分 + 暗色终端风 + 血缘 tidy tree + 三个新功能（路径追踪/自动刷新/代际趋势图）。

**Architecture:** Python 生成器瘦身为"取数+模板拼装"；HTML/CSS/JS 拆到 `core/tools/dashboard_template/`；输出仍是单文件 HTML，serve.py/entrypoint/docker 零改动。血缘树用内联 d3-hierarchy；图表手写 SVG。

**Tech Stack:** Python3 (sqlite3/json/argparse) + 原生 JS/CSS/SVG + d3-hierarchy@3 (vendor 内联)。

**基线:** 现有测试 `python3 core/tools/test_generate_factor_dashboard.py` 绿（已验证）。
**运行目录:** 所有命令在 `/home/lgao/work/factor-autoloop` 下执行。
**TDD 约定:** Python 侧先写断言再实现；JS/CSS 无构建链不加测试框架（设计决策），每任务以"生成快照 + 浏览器人工验收点"收尾。
**全局注意:** `style.css`/`app.js`/`vendor js` 内容中**不得出现** `__CSS__` `__JS__` `__DATA__` `__GENERATED_AT__` `__VENDOR__` 字样（会被拼装误替换）；JS 插值一律走 `esc()`。

---

### Task 0: 新建工作分支

**Files:** 无（git 操作）

- [ ] **Step 1: 从当前 HEAD 新建分支**

```bash
cd /home/lgao/work/factor-autoloop
git checkout -b feat/dashboard-frontend-rewrite
```

Expected: `Switched to a new branch`

- [ ] **Step 2: 提交设计文档**

```bash
git add docs/superpowers/specs/2026-08-27-dashboard-frontend-rewrite-design.md
git commit -m "docs: dashboard frontend rewrite design spec"
```

---

### Task 1: 模板拆分（纯重构，行为不变）

**Files:**
- Create: `core/tools/dashboard_template/template.html`
- Create: `core/tools/dashboard_template/style.css`
- Create: `core/tools/dashboard_template/app.js`
- Modify: `core/tools/generate_factor_dashboard.py`（删 CSS/HTML 常量，新增模板加载）
- Test: `core/tools/test_generate_factor_dashboard.py`

- [ ] **Step 1: 写失败测试（占位符全替换 + JS 注入点存在）**

在 `test_generate_factor_dashboard.py` 的 `test_snapshot_and_html_render` 内追加断言：

```python
    html = render_html(snapshot)
    for marker in ("__CSS__", "__JS__", "__DATA__", "__GENERATED_AT__", "__VENDOR__"):
        self.assertNotIn(marker, html, f"placeholder {marker} not substituted")
    self.assertIn("window.FACTOR_DASHBOARD_DATA = {", html)
    self.assertIn("<style>", html)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 core/tools/test_generate_factor_dashboard.py`
Expected: FAIL（`__JS__`/`__GENERATED_AT__` 未替换——旧 render_html 不处理它们；且旧产物含 `__CSS__` 替换后不含新占位但 `__JS__` 断言直接命中不存在）

- [ ] **Step 3: 拆出三个模板文件**

从 `generate_factor_dashboard.py` 原样搬运（内容不改一字节）：
- `CSS` 常量（`CSS = r"""..."""`）→ `dashboard_template/style.css`
- `HTML` 常量 → `dashboard_template/template.html`，同时做两处改造：
  - `<style>__CSS__</style>` → `<style>__CSS__</style>`（不变）
  - `<script>window.FACTOR_DASHBOARD_DATA = __DATA__;` 那个 script 块尾部 `</script>` 前，把**整个现有 JS 逻辑**（`window.FACTOR_DASHBOARD_DATA = __DATA__;` 之后到 `init();` 及之后全部 JS）移入 `dashboard_template/app.js`，template.html 中该 script 块改为：

```html
<script>
window.FACTOR_DASHBOARD_DATA = __DATA__;
</script>
<script>__VENDOR__</script>
<script>__JS__</script>
```

  - `<body>` 起 template.html 顶部 meta 区加生成时间占位（header 内 dbMeta 之后）：

```html
<p id="generatedMeta" title="快照生成时间">生成于 __GENERATED_AT__</p>
```

- [ ] **Step 4: 改造生成器**

删除 `CSS`、`HTML` 两个模块级常量（约 250-1605 行的字符串字面量），替换为：

```python
TEMPLATE_DIR = Path(__file__).resolve().parent / "dashboard_template"


def _read_template(name: str) -> str:
    path = TEMPLATE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"dashboard template part missing: {path}")
    return path.read_text(encoding="utf-8")


def render_html(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).replace("</", "<\\/")
    vendor = _read_template("vendor" / "d3-hierarchy.min.js") if (TEMPLATE_DIR / "vendor" / "d3-hierarchy.min.js").is_file() else ""
    return (_read_template("template.html")
            .replace("__VENDOR__", vendor)
            .replace("__CSS__", _read_template("style.css"))
            .replace("__JS__", _read_template("app.js"))
            .replace("__GENERATED_AT__", snapshot.get("meta", {}).get("generatedAt", ""))
            .replace("__DATA__", payload))
```

vendor 目录 Task 2 才建，这里先做存在性兜底（空串），避免 Task 1 红。

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 core/tools/test_generate_factor_dashboard.py`
Expected: `✓ generate_factor_dashboard tests passed`

- [ ] **Step 6: 用真库生成验证产物等价可用**

```bash
python3 core/tools/generate_factor_dashboard.py
ls -la data/factor_dashboard.html
grep -c '__VENDOR__\|__CSS__\|__JS__\|__DATA__\|__GENERATED_AT__' data/factor_dashboard.html || echo OK
```
Expected: 生成成功，grep 计数 0（OK）。

- [ ] **Step 7: Commit**

```bash
git add core/tools/generate_factor_dashboard.py core/tools/dashboard_template/ core/tools/test_generate_factor_dashboard.py
git commit -m "refactor: split dashboard HTML/CSS/JS into template files"
```

---

### Task 2: vendor d3-hierarchy 入库

**Files:**
- Create: `core/tools/dashboard_template/vendor/d3-hierarchy.min.js`
- Modify: `core/tools/generate_factor_dashboard.py`（去掉 Task 1 的兜底，vendor 必须存在）
- Test: `core/tools/test_generate_factor_dashboard.py`

- [ ] **Step 1: 写失败测试（vendor 内联完整）**

```python
    self.assertIn("d3", html)  # vendor UMD 全局
    # d3-hierarchy UMD 特征: stratify/tree/cluster 导出
    for feat in ("hierarchy", "stratify"):
        self.assertIn(feat, html)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 core/tools/test_generate_factor_dashboard.py`
Expected: FAIL（vendor 尚未下载，产物无 UMD 内容）

- [ ] **Step 3: 下载 min 版并固定**

```bash
mkdir -p core/tools/dashboard_template/vendor
curl -sL -o core/tools/dashboard_template/vendor/d3-hierarchy.min.js \
  https://cdn.jsdelivr.net/npm/d3-hierarchy@3.1.2/dist/d3-hierarchy.min.js
head -c 200 core/tools/dashboard_template/vendor/d3-hierarchy.min.js
wc -c core/tools/dashboard_template/vendor/d3-hierarchy.min.js
```
Expected: 文件 ~30KB，头部含 `(function(global,factory)`。

- [ ] **Step 4: 移除 Task 1 兜底，vendor 必选**

`render_html` 中 vendor 行改为：

```python
    vendor = _read_template("vendor/d3-hierarchy.min.js")
```

- [ ] **Step 5: 跑测试 + 生成确认**

Run: `python3 core/tools/test_generate_factor_dashboard.py` → PASS；
`python3 core/tools/generate_factor_dashboard.py` → 生成成功。

- [ ] **Step 6: Commit**

```bash
git add core/tools/dashboard_template/vendor/ core/tools/generate_factor_dashboard.py core/tools/test_generate_factor_dashboard.py
git commit -m "build: vendor d3-hierarchy 3.1.2 into dashboard template"
```

---

### Task 3: 暗色设计系统（style.css 全量重写）

**Files:**
- Modify: `core/tools/dashboard_template/style.css`（全量替换）
- Modify: `core/tools/dashboard_template/template.html`（legend 色值改 token）

- [ ] **Step 1: 重写 style.css —— token 层**

全量替换 style.css，开头为（后续任务在此文件上追加组件样式）：

```css
:root {
  color-scheme: dark;
  --bg: #0a0e14;
  --panel: #0f141d;
  --raised: #161d29;
  --border: #1e2836;
  --border-hover: #2d3b52;
  --up: #34d399;
  --down: #f87171;
  --accent: #22d3ee;
  --warn: #fbbf24;
  --muted: #94a3b8;
  --ink: #e2e8f0;
  --ink-dim: #94a3b8;
  --ink-faint: #64748b;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
}
```

- [ ] **Step 2: 组件层 —— 按设计文档 §2/§3 逐块实现**

同文件内实现（每块都是完整 CSS，无 TODO）：
1. **基础**：`html{background:var(--bg)}` `body{margin:0;font:14px/1.5 var(--sans);color:var(--ink)}`；所有数字类 `.number{font-variant-numeric:tabular-nums}`；滚动条暗色（`::-webkit-scrollbar` 用 `--raised/--border`）。
2. **Header**：sticky、`--panel` 底、底部 1px `--border`；brand-mark 方形 `--accent` 描边等宽 "F"；`#generatedMeta` 用 `--ink-faint` 12px。
3. **面板**：`.section{background:var(--panel);border:1px solid var(--border);border-radius:10px}`；标题 13px 字距 0.02em；hover 时 border 过渡到 `--border-hover`。
4. **指标卡**：`.metrics` 网格；卡片 `--raised` 底，大数字 26px `--mono`，sparkline 区 40px 高，环比箭头 `--up/--down`。
5. **图表容器**：`.chart-box{background:var(--panel)}`；`.chart-title` 11px `--ink-faint` 大写字距；SVG 轴线/网格用 `--border`，文字 `--ink-faint` 11px。
6. **血缘画布**：`.lineage-stage{background:var(--bg)}`，网格底纹：
   `background-image:linear-gradient(var(--border) 1px,transparent 1px),linear-gradient(90deg,var(--border) 1px,transparent 1px);background-size:32px 32px;` 透明度通过 `opacity` 包一层伪元素实现（网格 0.35）。
7. **表格**：thead `--raised` 底 sticky；行 hover `--raised`；斑马纹 `tr:nth-child(even){background:rgba(22,29,41,.45)}`；排序按钮 `--accent` 激活。
8. **徽章/控件**：状态点 + 文字；select/input `--raised` 底 1px `--border`，focus 描边 `--accent`；按钮 hover 发光 `box-shadow:0 0 0 3px rgba(34,211,238,.15)`。
9. **详情面板**：`--panel` 底 sticky；分节标题前缀 `▮ `（`--accent`）；路径面包屑用 `--mono` 12px，箭头 `--ink-faint`。
10. **动效**：面板进场 `fadeUp`（translateY(6px)→0，240ms，stagger 30ms）；`@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}`。
11. **打印**：`@media print` 白底黑字降级（现有 print 按钮保留）。
12. **响应式**：<1080px 详情面板下移单列（沿用现有断点行为）。

- [ ] **Step 3: template.html 图例色值换 token**

现有 lineage-legend 内联 `#12805c/#c2410c/...` 改为对应新 token 类：`<i class="lg up"></i>` 等，CSS 里 `.lg.up{background:var(--up)}`。状态映射改为：已评估 `--up`、放弃 `--down`、草稿 `--accent`、已提交 `--warn`、失败 `#c084fc`（紫，无 token，图例与 JS STATUS_COLORS 同步用同一常量）。

- [ ] **Step 4: 生成 + 浏览器验收**

```bash
python3 core/tools/generate_factor_dashboard.py
```
浏览器（8765）验收：全页暗色无残留白块；表格/图表/控件全部暗色；无样式裸奔区域。**此任务后图表可能仍为旧浅色绘制色——允许，Task 4-5 处理**，本任务只看容器/文字/控件。

- [ ] **Step 5: 跑测试 + Commit**

```bash
python3 core/tools/test_generate_factor_dashboard.py
git add core/tools/dashboard_template/
git commit -m "feat(dashboard): dark terminal design system tokens and components"
```

---

### Task 4: app.js 基础层 + 指标卡 sparkline

**Files:**
- Modify: `core/tools/dashboard_template/app.js`（重写基础层与指标卡渲染）

- [ ] **Step 1: 重写基础层**

app.js 头部（替换旧同名内容，保留 `window.FACTOR_DASHBOARD_DATA` 由 template 注入）：

```js
"use strict";
const DATA = window.FACTOR_DASHBOARD_DATA;

const STATUS_COLORS = {
  evaluated: "#34d399", deprecated: "#f87171", draft: "#22d3ee",
  committed: "#fbbf24", failed: "#c084fc"
};
const STATUS_LABELS = { evaluated: "已评估", deprecated: "放弃", draft: "草稿", committed: "已提交", failed: "失败" };
const EDGE_COLORS = { improved: "#34d399", declined: "#f87171", plain: "#4a5a70" };

const state = { selected: null, search: "", statusFilter: "all", tagFilter: "all",
  sortKey: "last_updated_ts", sortDir: -1, autoRefreshPaused: false };
const $ = id => document.getElementById(id);

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtNum(v, digits = 3) {
  return (v === null || v === undefined || Number.isNaN(+v)) ? "—" : (+v).toFixed(digits);
}
function shortFactorName(name) { return String(name || "").split(/_(?=W\d|G\d|Tf|K\d)/)[0] || name; }
function parseTs(value) {
  return new Date(String(value || "").includes("T")
    ? value + (String(value).endsWith("Z") ? "" : "Z")
    : String(value).replace(" ", "T") + "Z");
}
```

`byName`、`render()` 总调度、`init()` 结构沿用旧版逻辑（选中态/筛选态驱动各区块 render 子函数）。

- [ ] **Step 2: 指标卡 + sparkline**

```js
function sparkline(values, w = 120, h = 36) {
  if (!values || values.length < 2) return "";
  const min = Math.min(...values), max = Math.max(...values);
  const span = (max - min) || 1;
  const pts = values.map((v, i) =>
    `${(i / (values.length - 1) * w).toFixed(1)},${(h - 3 - (v - min) / span * (h - 6)).toFixed(1)}`);
  const up = values[values.length - 1] >= values[0];
  const color = up ? "var(--up)" : "var(--down)";
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/>
    <circle cx="${pts[pts.length - 1].split(",")[0]}" cy="${pts[pts.length - 1].split(",")[1]}" r="2.2" fill="${color}"/></svg>`;
}
```

指标卡数据：沿用旧 metricCards 的取数口径（因子总数/已评估/通过/活跃分支），每卡加大数字 + 最近 8 次更新时间序列 sparkline（用 `DATA.factors` 按 `last_updated_ts` 排序计数分桶）。环比箭头：比较前后两桶计数。

- [ ] **Step 3: 生成 + 浏览器验收**

验收点：指标卡大数字等宽、sparkline 显示、hover 发光；点击因子列表行为暂不要求（Task 8 前 render 桩函数允许空实现占位但**不报错**）。

- [ ] **Step 4: 测试 + Commit**

```bash
python3 core/tools/test_generate_factor_dashboard.py
git add core/tools/dashboard_template/app.js
git commit -m "feat(dashboard): js base layer and metric cards with sparklines"
```

---

### Task 5: 概览区（散点图 + 状态堆叠条）

**Files:**
- Modify: `core/tools/dashboard_template/app.js`

- [ ] **Step 1: 散点图（R² × |ICIR|）**

`renderScatter()`：容器 `#scatterChart`（viewBox 720×355 保留）。实现：
- 网格：横纵各 5 条 `--border` 色 1px 线；
- 轴标签：x=库内解释方差 R²，y=|ICIR|，11px `--ink-faint`；
- 点：每因子 `<circle r="4">`，fill=STATUS_COLORS[status] 80% 不透明，stroke 同色全透明度；
- 中位数十字参考线（x/y 中位，`--warn` 虚线 dasharray 3,3）；
- hover：`<title>` 显示 xname + IC/ICIR/R²；点击 → `state.selected` 并联动详情面板；
- 排除 `latest_r2_x`/`latest_icir` 为 null 的因子（空态文案"无评估数据"）。

- [ ] **Step 2: 状态水平堆叠条**

`renderStatus()`：容器 `#statusChart`。单条水平堆叠条（高 28px）按 status 计数分段，段色=STATUS_COLORS，段内白描边 0；下方图例两列（色点+标签+计数）；hover 段显示 title。

- [ ] **Step 3: 生成 + 浏览器验收**

验收点：散点无平移缩放但 hover/点击正常；两图坐标文字可读（暗底对比度）；无 null 崩溃。

- [ ] **Step 4: 测试 + Commit**

```bash
python3 core/tools/test_generate_factor_dashboard.py
git add core/tools/dashboard_template/app.js
git commit -m "feat(dashboard): dark scatter plot and status bar"
```

---

### Task 6: 代际趋势图（新功能）

**Files:**
- Modify: `core/tools/dashboard_template/template.html`（概览 chart-grid 加第三图容器）
- Modify: `core/tools/dashboard_template/app.js`

- [ ] **Step 1: template.html 加容器**

库内概览 `.chart-grid` 内追加：

```html
<figure class="chart-box" id="trendBox" aria-label="指标代际趋势">
  <p class="chart-title">代际趋势 · IC/ICIR 中位数与通过率</p>
  <svg id="trendChart" viewBox="0 0 720 260" role="img"></svg>
</figure>
```

- [ ] **Step 2: 代际推导 + 聚合**

```js
function computeGenerations() {
  const parent = new Map();
  for (const e of DATA.lineage_edges || []) parent.set(e.child_xname, e.parent_xname);
  const memo = new Map();
  function gen(x) {
    if (!memo.has(x)) memo.set(x, parent.has(x) ? gen(parent.get(x)) + 1 : 1);
    return memo.get(x);
  }
  return gen; // gen(xname) -> 1..N
}
function aggregateByGeneration() {
  const gen = computeGenerations();
  const buckets = new Map();
  for (const f of DATA.factors) {
    const g = gen(f.xname);
    if (!buckets.has(g)) buckets.set(g, []);
    buckets.get(g).push(f);
  }
  return [...buckets.keys()].sort((a, b) => a - b).map(g => {
    const fs = buckets.get(g);
    const median = key => {
      const vs = fs.map(f => +f[key]).filter(v => !Number.isNaN(v)).sort((a, b) => a - b);
      return vs.length ? vs[Math.floor(vs.length / 2)] : null;
    };
    const passed = fs.filter(f => f.verdict === "pass").length;
    return { gen: g, n: fs.length, ic: median("latest_ic"),
             icir: median("latest_icir"), passRate: fs.length ? passed / fs.length : null };
  });
}
```

- [ ] **Step 3: renderTrend() 双轴折线**

`#trendChart`：x=代际序号；左轴 IC/ICIR（0 附近对称域），两条折线（IC=`--accent`、ICIR=`--up`）+ 半透明面积（fill 同色 12%）；右轴通过率 0-1 映射 `--warn` 虚线步进线；每点上 `<title>`（第 N 代 · 因子数 · IC/ICIR/通过率）。代际 <2 显示"代际数据不足"文字占位。注意 verdict 字段实际值以 DATA 为准（factors.verdict），若 `pass` 判定不准以 `significant` 口径改用 evaluations 关联（实施时核对一次真实值域：`SELECT DISTINCT verdict FROM factors`）。

- [ ] **Step 4: 生成 + 浏览器验收**

验收点：代际 x 轴从 1 起；双轴不重叠遮挡；<2 代时占位文案。

- [ ] **Step 5: 测试 + Commit**

```bash
python3 core/tools/test_generate_factor_dashboard.py
git add core/tools/dashboard_template/
git commit -m "feat(dashboard): generation trend chart with lineage-derived generations"
```

---

### Task 7: 血缘 tidy tree + 路径追踪

**Files:**
- Modify: `core/tools/dashboard_template/app.js`

- [ ] **Step 1: 层次模型替换力导向**

`computeLineageLayout` 全量替换（`buildLineageModel` 保留）：

```js
function computeLineageLayout(model) {
  const children = new Map();
  for (const e of model.edges) {
    if (!children.has(e.parent_xname)) children.set(e.parent_xname, []);
    children.get(e.parent_xname).push(e.child_xname);
  }
  const byName = new Map(model.nodes.map(n => [n.xname, n]));
  const NODE_W = 168, NODE_H = 34;
  const heights = new Map();
  function subtreeHeight(x) { // 叶=1，内部=子树高之和（横向并排时占用行数）
    if (heights.has(x)) return heights.get(x);
    const kids = children.get(x) || [];
    const h = kids.length ? kids.reduce((s, k) => s + subtreeHeight(k), 0) : 1;
    heights.set(x, h); return h;
  }
  const pos = new Map();
  function place(x, depth, rowCursor) { // 返回该子树占用的行数
    const kids = children.get(x) || [];
    if (!kids.length) { pos.set(x, { depth, row: rowCursor }); return 1; }
    let used = 0;
    for (const k of kids) used += place(k, depth + 1, rowCursor + used);
    const rows = kids.map(k => pos.get(k).row);
    pos.set(x, { depth, row: (Math.min(...rows) + Math.max(...rows)) / 2 });
    return used;
  }
  const roots = [...new Set(model.nodes.map(n => model.rootOf.get(n.xname)))];
  let cursor = 0;
  for (const r of roots) cursor += place(r, 0, cursor) + 1; // 分支间隔 1 行
  const nodes = model.nodes.map(n => {
    const p = pos.get(n.xname) || { depth: 0, row: 0 };
    return { ...n, x: p.depth * (NODE_W + 90), y: p.row * (NODE_H + 16),
             w: NODE_W, h: NODE_H, root: model.rootOf.get(n.xname) };
  });
  return { nodes, edges: model.edges, rootOf: model.rootOf,
           byName, children };
}
```

（tidy tree 一次成形，确定性布局；如实施时发现 d3-hierarchy 的 `d3.tree()` 更省事，可替换本函数内部实现，**函数签名与返回结构不变**。）

- [ ] **Step 2: 贝塞尔边替换直线**

`lineageEdgePath` 改为水平 三次贝塞尔（父右侧 → 子左侧）：

```js
function lineageEdgePath(e, byId) {
  const p = byId.get(e.parent_xname), c = byId.get(e.child_xname);
  if (!p || !c) return "";
  const x1 = p.x + p.w / 2 + 2, y1 = p.y;
  const x2 = c.x - c.w / 2 - 9, y2 = c.y;
  const mx = (x1 + x2) / 2;
  const color = EDGE_COLORS[e.outcome] || EDGE_COLORS.plain;
  const dash = e.operator_name ? ' stroke-dasharray="5,4"' : "";
  const title = e.operator_name ? `<title>算子: ${esc(e.operator_name)}</title>` : "";
  return `<path class="graph-edge" d="M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${mx.toFixed(1)} ${y1.toFixed(1)}, ${mx.toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${color}"${dash}>${title}</path>`;
}
```

（`renderLineage` 里 marker 引用与 defs 保留；箭头 marker 色 `#8da0b3` → `#4a5a70`。）

- [ ] **Step 3: 路径追踪**

`renderLineage` 渲染后挂 hover 委托（`#lineageChart` 上 addEventListener mouseover/mouseout）：

```js
function highlightAncestry(svg, xname, children, byName) {
  const parent = new Map();
  for (const e of (DATA.lineage_edges || [])) parent.set(e.child_xname, e.parent_xname);
  const chain = new Set([xname]);
  let cur = xname;
  while (parent.has(cur)) { cur = parent.get(cur); chain.add(cur); }
  svg.querySelectorAll(".graph-node").forEach(g =>
    g.classList.toggle("dim", !chain.has(g.dataset.xname)));
  svg.querySelectorAll(".graph-edge").forEach(pEl => {
    const t = pEl.getAttribute("d") || ""; // 用 data 属性代替解析 d
  });
  // 边高亮：Step 2 渲染时给每条 path 加 data-parent/data-child，
  // 此处 toggle dim = !(chain.has(parent) && chain.has(child))
}
```

实施要求：`lineageEdgePath` 输出的 `<path>` 加 `data-parent`/`data-child`；`.dim { opacity: .15 }`（Task 3 已备暗色样式，若缺在此补）。mouseout 时清除全部 dim。点击节点行为沿用（选中 + 详情）。

- [ ] **Step 4: 交互保留**

滚轮缩放/拖拽平移/适应/重置/分支下拉沿用旧实现（viewBox 操作逻辑不变，坐标系换成新布局即可）。

- [ ] **Step 5: 生成 + 浏览器验收**

验收点：根在上、代际向下；曲线无交叉穿过节点；hover 任意节点仅祖先链亮、其余 15%；improved/declined 边色正确、算子虚线 + tooltip；16 分支"全部"视图不重叠；选单分支纵向清晰。

- [ ] **Step 6: 测试 + Commit**

```bash
python3 core/tools/test_generate_factor_dashboard.py
git add core/tools/dashboard_template/app.js
git commit -m "feat(dashboard): hierarchical tidy-tree lineage with ancestry highlight"
```

---

### Task 8: 因子表 + 详情面板（终端风 + 进化路径面包屑）

**Files:**
- Modify: `core/tools/dashboard_template/app.js`

- [ ] **Step 1: 因子表渲染**

`renderTable()`：沿用现有列（因子/结论/IC/ICIR/R²/残差IC/残差IC比/更新时间）与排序/搜索/状态/标签筛选/CSV 导出逻辑；视觉换暗色（样式已在 Task 3）；因子名单元格用 `--mono`；IC/ICIR 正值 `--up` 负值 `--down` 着色；更新时间相对化（"3h 前"，用 parseTs）。

- [ ] **Step 2: 详情面板 + 进化路径面包屑**

`renderDetail()`：选中因子时，顶部渲染：

```js
function renderPathBreadcrumb(xname) {
  const parent = new Map();
  for (const e of DATA.lineage_edges || []) parent.set(e.child_xname, e.parent_xname);
  const chain = [];
  for (let cur = xname; cur; cur = parent.get(cur) || null) chain.unshift(cur);
  return `<nav class="path-crumbs" aria-label="进化路径">` + chain.map((x, i) =>
    (i ? `<span class="crumb-sep">→</span>` : "") +
    `<button class="crumb${x === xname ? " current" : ""}" data-xname="${esc(x)}">${esc(shortFactorName(x))}</button>`
  ).join("") + `</nav>`;
}
```

点击面包屑切换 `state.selected`。其余分节（公式/参数/直觉/最近评估/迭代历史/教训）沿用旧取数口径，容器样式走终端风（`--mono` 公式块、`▮` 分节标题）。

- [ ] **Step 3: 生成 + 浏览器验收**

验收点：表格排序筛选 CSV 全可用；点击行/散点/血缘节点 → 详情联动；面包屑逐级可点；数字着色正确。

- [ ] **Step 4: 测试 + Commit**

```bash
python3 core/tools/test_generate_factor_dashboard.py
git add core/tools/dashboard_template/app.js
git commit -m "feat(dashboard): terminal-style factor table and detail with lineage breadcrumb"
```

---

### Task 9: 自动刷新

**Files:**
- Modify: `core/tools/dashboard_template/template.html`（横幅元素）
- Modify: `core/tools/dashboard_template/style.css`（横幅样式）
- Modify: `core/tools/dashboard_template/app.js`

- [ ] **Step 1: template.html 加横幅（header 后）**

```html
<div class="refresh-banner" id="refreshBanner" hidden>
  <span>新数据可用，<b id="refreshCountdown">10</b>s 后自动刷新</span>
  <button id="refreshNow" type="button">立即刷新</button>
  <button id="refreshPause" type="button">本会话暂停</button>
</div>
```

- [ ] **Step 2: style.css 横幅样式**

`.refresh-banner{position:fixed;top:0;left:50%;transform:translate(-50%,-110%);transition:transform .3s;z-index:50;background:var(--raised);border:1px solid var(--accent);border-radius:8px;padding:8px 14px;display:flex;gap:10px;align-items:center;box-shadow:0 6px 24px rgba(0,0,0,.5)}`
`.refresh-banner.show{transform:translate(-50%,8px)}`
按钮走既有控件样式。

- [ ] **Step 3: 轮询逻辑（app.js）**

```js
function startAutoRefresh() {
  const base = document.lastModified;
  setInterval(async () => {
    if (state.autoRefreshPaused) return;
    try {
      const res = await fetch(location.pathname, { method: "HEAD", cache: "no-store" });
      if (res.ok && res.headers.get("Last-Modified") &&
          res.headers.get("Last-Modified") !== base) armReload();
    } catch (_) { /* 网络断：静默下轮重试 */ }
  }, 60_000);
}
function armReload() {
  if (state.autoRefreshPaused || armReload.armed) return;
  armReload.armed = true;
  const banner = $("refreshBanner"); banner.hidden = false;
  requestAnimationFrame(() => banner.classList.add("show"));
  let left = 10;
  const timer = setInterval(() => {
    $("refreshCountdown").textContent = --left;
    if (left <= 0) { clearInterval(timer); location.reload(); }
  }, 1000);
  $("refreshNow").onclick = () => location.reload();
  $("refreshPause").onclick = () => {
    state.autoRefreshPaused = true;
    clearInterval(timer); banner.classList.remove("show");
    setTimeout(() => banner.hidden = true, 350);
  };
}
```

`init()` 末尾调用 `startAutoRefresh()`。

- [ ] **Step 4: 生成 + 浏览器验收**

验收点：手动 `python3 core/tools/generate_factor_dashboard.py` 触发快照变化（Last-Modified 变）→ ≤60s 后横幅滑出 → 10s 倒计时 reload；暂停后不再弹。注意 serve.py 需确认响应带 Last-Modified（SimpleHTTPRequestHandler 默认带；若有 no-cache 头不影响）。

- [ ] **Step 5: 测试 + Commit**

```bash
python3 core/tools/test_generate_factor_dashboard.py
git add core/tools/dashboard_template/
git commit -m "feat(dashboard): auto refresh with countdown banner and pause"
```

---

### Task 10: Python 侧结构断言补全 + 全量回归 + 部署验收

**Files:**
- Modify: `core/tools/test_generate_factor_dashboard.py`

- [ ] **Step 1: 补结构断言**

在现有测试类中新增（`render_html(snapshot)` 产物上）：

```python
    html = render_html(snapshot)
    for dom_id in ("lineageChart", "scatterChart", "trendChart", "statusChart",
                   "factorRows", "detailPanel", "metricCards", "refreshBanner",
                   "generatedMeta"):
        self.assertIn(f'id="{dom_id}"', html)
    self.assertIn('"lineage_edges"', html)          # 数据键
    self.assertIn("d3", html)                        # vendor 在
    self.assertIn("tidy", html.lower() or True)      # 布局函数存在性以函数名断言：
    self.assertIn("computeLineageLayout", html)
    self.assertIn("startAutoRefresh", html)
    self.assertIn("aggregateByGeneration", html)
```

（JSON 可解析断言已在旧测试覆盖 payload 构造；此处补 DOM/函数存在性。）

- [ ] **Step 2: 全量回归**

Run: `python3 core/tools/test_generate_factor_dashboard.py`
Expected: PASS 全部。

- [ ] **Step 3: 真数据部署验收**

```bash
python3 core/tools/generate_factor_dashboard.py
# 若 factor-dashboard 容器在跑，重新生成本地 data/ 后按部署方式同步；
# 本机验证：docker restart factor-dashboard 或直接看 data/factor_dashboard.html
```
浏览器过一遍设计文档 §6 验收清单（全部区块 + 三个新功能交互）。

- [ ] **Step 4: Commit**

```bash
git add core/tools/test_generate_factor_dashboard.py
git commit -m "test(dashboard): structural assertions for rewritten frontend"
```

- [ ] **Step 5: 收尾**

`git log --oneline` 核对提交序列；向用户汇报并确认合入方式（merge 到当前主线 / 开 MR）。

---

## Self-Review 记录

- **Spec 覆盖**：§1 架构=Task 1/2；§2 设计系统=Task 3；§3 区块=Task 3/4/5/7/8；§4.1=Task 7；§4.2=Task 9；§4.3=Task 6；§5 错误处理=Task 5/6/7 各空态+esc；§6 测试=Task 10 + 各任务测试步；§7 非目标未违反。
- **Placeholder 扫描**：Task 3 Step 2 组件层为"要点清单+完整 token"，属样式指导而非代码占位；其余任务均含完整代码或精确指令。
- **类型一致性**：`computeLineageLayout` 返回 `{nodes, edges, rootOf, byName, children}`（Task 7 定义，renderLineage/后续 hover 使用一致）；`aggregateByGeneration`/`startAutoRefresh`/`renderPathBreadcrumb` 命名在 Task 6/9/8/10 间一致；STATUS_COLORS/EDGE_COLORS 在 Task 4 定义、Task 5/7 使用。
