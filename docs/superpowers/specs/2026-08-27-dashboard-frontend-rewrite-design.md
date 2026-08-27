# 因子库看板前端重写设计

日期：2026-08-27
状态：已获批（口头），待实施
范围：`core/tools/generate_factor_dashboard.py` 及其生成的前端

## 背景与目标

现看板由 `generate_factor_dashboard.py`（1656 行，内嵌全部 CSS/JS）生成单文件静态 HTML，
`dashboard-server/serve.py` 静态服务。问题：

1. **血缘图谱布局算法与数据不匹配**：数据是纯森林（73 因子 / 57 边 / 16 棵树 / 多父节点
   为 0 / 最深 7 层 / 最宽 16 子代），却用随机初始化的 force-directed 布局 + 直线连边，
   层级信息完全丢失、边交叉混乱。
2. 整体视觉为通用浅色模板，无设计方向，数字不可视化质感弱。

目标：全部重写前端视觉与交互，保持单文件输出架构，新增三个功能。

## 已确认决策

| 决策点 | 结论 |
|---|---|
| 技术架构 | 维持"Python 生成器 → 单文件 HTML → serve.py 静态服务"，无构建链、无 CDN、无 node_modules |
| 美学方向 | 暗色终端风（Bloomberg / 交易台质感） |
| 功能范围 | 现有功能全保留 + 血缘路径追踪、自动刷新、指标代际趋势图 |
| 实现方式 | 模板拆分：HTML/CSS/JS 移出 Python，生成器只做取数+拼装 |
| 血缘布局 | d3-hierarchy tidy tree（垂直，根在上），内联 min 版约 10KB |

## 1. 架构与文件布局

```
core/tools/generate_factor_dashboard.py      # 瘦身为：取数 + 模板拼装 + 写文件
core/tools/dashboard_template/
  template.html      # 骨架，含 __CSS__ / __JS__ / __DATA__ / __GENERATED_AT__ 占位符
  style.css          # 设计系统（CSS variables）+ 全部组件样式
  app.js             # 全部渲染与交互逻辑
  vendor/d3-hierarchy.min.js                 # 树布局，构建时内联
```

- 拼装：Python 读模板与资源，替换占位符，写出 `factor_dashboard.html`。
- `serve.py`、`entrypoint.sh`、docker、刷新周期（600s）**零改动**。
- vendor 库获取：一次性下载入库（服务器无外网时经代理）。内联进 `<script>`，与模板
  其余 JS 隔离（IIFE），不依赖加载顺序以外的东西。

## 2. 设计系统（暗色终端风）

CSS variables 全局定义，组件只引用 token：

- 底色三层：`--bg: #0a0e14`（页面）/ `--panel: #0f141d`（面板）/ `--raised: #161d29`（悬浮层）
- 边框：`--border: #1e2836`（1px），hover 描边 `--border-hover: #2d3b52`
- 数据色（暗底对比度 ≥ WCAG AA）：涨 `--up: #34d399`、跌 `--down: #f87171`、
  强调青 `--accent: #22d3ee`、警示琥珀 `--warn: #fbbf24`、中性 `--muted: #94a3b8`
- 文字：主 `#e2e8f0`、次 `#94a3b8`、弱 `#64748b`
- 字体：正文系统 UI 栈（含中文回退）；数字 `font-variant-numeric: tabular-nums`；
  因子名/公式/代码 `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`。不引外网字体。
- 质感：血缘画布细网格底纹（CSS background gradient 实现）；状态徽章（色点+文字）；
  hover 发光描边（box-shadow 低强度同色光）；页面加载 stagger 渐入动画（纯 CSS，
  `prefers-reduced-motion` 时关闭）。

## 3. 区块设计（信息架构不变）

| 区块 | 设计 |
|---|---|
| Header | 标题 + db meta + 生成时间；自动刷新状态指示（见 §4.2） |
| 指标卡 | 大数字（等宽）+ 迷你 sparkline（最近 N 代走势）+ 环比箭头 |
| 库内概览 | 散点图（R² × \|ICIR\|）暗色重制；状态分布改水平堆叠条 |
| 代际趋势图（新增） | 见 §4.3 |
| 血缘图谱 | 垂直 tidy tree：根在上、代际向下分层、贝塞尔曲线边；分支下拉保留；"全部分支"时 16 棵小树横向并排 |
| 因子列表 | 暗色表格、斑马纹、列排序/搜索/状态与标签筛选/CSV 导出全保留 |
| 详情面板 | 终端日志风：等宽字体、分节标签；顶部显示"进化路径"面包屑（见 §4.1） |

## 4. 新功能机制

### 4.1 血缘路径追踪

- hover 节点：根 → 该节点的祖先链上节点与边全亮，其余节点/边淡出至 15% 不透明度。
- 边按 outcome 着色：improved 绿、declined 红、默认中性；operator 边虚线，tooltip 显示算子名。
- 点击节点：详情面板顶部渲染完整进化路径面包屑（根 → … → 该因子），逐级可点。

### 4.2 自动刷新

- 页面内嵌 `__GENERATED_AT__` 时间戳。前端每 60s 发 `HEAD /`，对比响应头
  `Last-Modified`（serve.py 继承 SimpleHTTPRequestHandler 的 do_HEAD，后端零改动）。
- 检测到更新：顶部滑出"新数据可用"横幅，10s 倒计时后 `location.reload()`；
  横幅上可"暂停自动刷新"（本 session 内记住）。
- HEAD 失败（网络断）：静默，下轮重试。

### 4.3 指标代际趋势图

- 数据：`DATA.evaluations` 中**没有 generation 字段**（已验证，字段为 ic_mean/icir/
  sharpe/rank_ic/significant/ts 等）。代际从 `DATA.lineage_edges` 在前端推导：
  根因子 = 第 1 代，child 代数 = parent 代数 + 1（复用 buildLineageModel 的 BFS）。
  因子关联其最新评估的 ic_mean / icir，significant 即通过。
- 聚合：每代 IC 中位数、ICIR 中位数、通过率（significant 占比）。
- 呈现：双轴折线（左轴 IC/ICIR，右轴通过率 0-100%），代际为 x 轴，面积渐变填充。
- 目的：一眼判断研究循环是否随代际进步。

## 5. 数据流与错误处理

- 数据流不变：SQLite → collect_snapshot → 内嵌 JSON → 前端渲染。
- 空态：无评估因子在散点图排除；血缘为空显示现有空态文案；趋势图代际数据不足
  （<2 代）显示"数据不足"占位。
- 布局异常兜底：d3-hierarchy 输出为空时退化为空态提示，不白屏。
- `esc()` HTML 转义继续用于所有用户数据插值。

## 6. 测试与验收

- 现有 `core/tools/test_generate_factor_dashboard.py` 必须全绿；新增断言：
  - 占位符（`__CSS__` / `__JS__` / `__DATA__` / `__GENERATED_AT__`）全部被替换，产物中不残留；
  - 内嵌 `FACTOR_DASHBOARD_DATA` JSON 可被 `json.JSONDecoder` 解析；
  - 关键 DOM id 存在（lineageChart / scatterChart / trendChart / factorRows / detailPanel 等）；
  - vendor d3-hierarchy 内联完整（含首尾特征字符串）。
- 视觉验收：部署后浏览器（8765 端口）人工过一遍全部区块 + 三个新功能交互。

## 7. 非目标

- 不改数据库 schema、不改取数逻辑字段、不做多用户/鉴权、不做打印样式升级、
  不引入前端构建链。
