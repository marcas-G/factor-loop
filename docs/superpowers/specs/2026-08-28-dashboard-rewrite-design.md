# 因子库 Dashboard 重写设计

日期:2026-08-28
状态:已与用户对齐方向,待实施

## 背景与问题

现有因子库看板(factor-autoloop)存在三类问题:

1. **整页刷新打断阅读**:数据更新(容器内 10 分钟重生成快照)后,前端探测到 Last-Modified 变化即倒计时 `location.reload()`,用户的筛选、滚动位置、选中状态全部丢失。
2. **血缘图不可读**:垂直 tidy-tree,最大分支 44 节点 6 层,节点宽度按全局最大名字长度对齐,挤成一团。
3. **视觉整体不满意**:布局组织、信息层次、图表现代感都需要推倒重做。

用户决策:
- 重写技术栈:**Vite + React + TypeScript**(接受引入 node 工具链和构建步骤)
- 视觉:**整体推倒重来**(视觉风格 + 布局信息组织 + 图表现代感 + 血缘图可读性)
- 刷新:**手动刷新为主,自动探测只提示不应用**;绝不打断阅读
- 新增:**表格多维筛选**(因子类型/算子链长度/创建时间段/标签多选/闸门分项通过情况)

## 现状(重写的事实基础)

- 数据源:SQLite `data/factors.db`(只读挂载进容器,WAL 模式,需 `immutable=1` URI 打开)
- 数据规模(2026-08-28):factors 88 / factor_evals 88 / iteration_suggestions 60 / lineage_edges 53 / lineage_branches 33 / lessons 86;最大分支 44 节点、6 层深
- 快照逻辑:`core/tools/generate_factor_dashboard.py` 的 `collect_snapshot()`(纯读库→dict)
- 现前端:零依赖原生 JS(978 行)+ 手写 SVG 图表 + vendored d3-hierarchy,自包含单 HTML(3.4MB 数据内嵌)
- 现服务:`dashboard-server/`(serve.py 静态文件 + entrypoint.sh 每 10 分钟重生成循环)
- 聚合分/闸门公式:与 `core/db/db.py` 的 `leaderboard_gates` + 饱和常数同源

## 目标架构

```
dashboard/                      ← 新顶层目录
├── frontend/                   ← Vite + React + TS
│   ├── src/
│   │   ├── api.ts              ← /api/snapshot 拉取 + ETag 缓存
│   │   ├── state.ts            ← URL hash 同步的筛选/选中状态
│   │   ├── components/         ← MetricCards / Scatter / StatusChart / Trend / LineageTree / FactorTable / DetailPanel
│   │   ├── charts/             ← 手写 SVG 图表(不引图表库)
│   │   └── styles/             ← 手写 CSS 设计系统(无 Tailwind)
│   └── (vite.config: build outDir → ../dist)
└── server.py                   ← 纯 stdlib HTTP API + 静态托管
```

- `collect_snapshot()` 从 `generate_factor_dashboard.py` 抽到可复用模块(建议 `core/tools/dashboard_snapshot.py`),`server.py` 与旧生成器共同引用,公式不漂移。
- `server.py` 职责:
  - `GET /api/snapshot`:调用 `collect_snapshot()`,响应带 ETag(取 db 文件 mtime+size 哈希);内存缓存上次结果,db 未变不重算
  - `GET /`、静态资源:托管前端构建产物(dist/);找不到时回退 index.html(前端路由)
  - 沿用只读 + `immutable=1` 连接方式,每次快照新开连接
- **删除 entrypoint 的定时重生成循环**:数据实时性由"请求时读库"保证,不再有快照过期概念
- Docker 多阶段构建:node:22-alpine 构建 frontend → 产物拷入 python:3.12-slim,运行 `server.py`;docker-compose 结构不变(端口 8765、只读挂载 data/)

## 刷新交互(核心需求)

- 页面代码中不存在 `location.reload()`
- 手动刷新按钮:拉最新 snapshot,数据原地更新;表格行以 `xname` 为 key,选中/筛选/排序/滚动位置全部保留
- 后台每 60s 对 `/api/snapshot` 发 If-None-Match 探测:304 则静默;200 则**只亮角标"有新数据"**,不自动应用;点击角标才拉取应用
- 筛选、选中因子、血缘分支选择同步到 URL hash(如 `#f=...&s=...&sel=...`),刷新/重开可恢复

## 血缘图重做

- **横向 tidy-tree**(根在左,代际向右),节点为紧凑卡片:状态色点 + 缩写名 + ICIR 徽标
- **子树折叠**:44 节点大分支默认只展开前 2 层;折叠节点显示汇聚徽标(子树节点数)
- d3-zoom 平移缩放(vendor 或 npm 均可,构建期内联,运行时零外部请求)+ 适应视图 + 搜索定位:命中后自动展开祖先路径并高亮
- 边样式保留语义:实线=迭代、虚线=算子应用、绿/红=improved/declined
- 悬停节点高亮祖先链与直接子边(现有行为保留)

## 多维筛选(新增)

因子表筛选区升级,维度:

- 文本搜索(名称/公式/标签/意图,现有)
- 状态多选
- 标签多选
- 闸门:总通过 + 分项(IC/ICIR/残差IC/R²)任意组合
- 因子类型(origin_type / class_name)
- 算子链长度(区间)
- 创建时间段(起止)

所有筛选条件组合为 AND,与 URL hash 同步。指标卡与图表默认统计全量,不随筛选联动(保持全局态势感知;如需联动后续迭代)。

## 视觉方向

延续"交易终端"概念整体重做:近黑底色、密度分层、等宽数字、克制的荧光数据色(绿涨红跌+青色强调);图表手写 SVG + CSS transition,数据变化有过渡动画,悬停有十字线与数据卡片。不做通用 SaaS 后台风。

## 功能对齐清单(不丢现有能力)

指标卡+sparkline、冗余度×预测强度散点、状态分布、代际趋势(IC/ICIR 中位数与通过率)、因子表(搜索/筛选/排序/CSV 导出)、因子详情面板(指标/标签/意图/演化路径)、打印样式、CSV 导出。

## 退役清单

- `dashboard-server/`(serve.py、entrypoint.sh、旧 Dockerfile/docker-compose 被 dashboard/ 替代)
- `generate_factor_dashboard.py` 的 HTML 渲染部分 + `core/tools/dashboard_template/` 整目录(快照采集逻辑抽出后移入 attic/)
- 静态单文件 HTML 工作流(离线 `--open`)退役;本地查看统一 `python dashboard/server.py`

## 实施注意

- 工作区 `core/db/db.py`、`core/mcp/tools/factor_db.py` 有未提交改动(与 dashboard 无关),不动
- 旧模板的未提交改动会被重写覆盖:动手前先提交当前 WIP 一版
- `test_generate_factor_dashboard.py` 中结构断言随模板退役,快照采集逻辑的测试迁到新模块
- server.py 保持纯 stdlib,容器内无 pip 安装步骤

## 明确不做(YAGNI)

- SSE/WebSocket 推送(用户明确不追求频率)
- 后端分页/查询参数(88 因子全量返回,单 snapshot JSON 体积可控)
- 指标卡/图表随筛选联动
- 图表库(echarts/recharts 等)引入
- 认证、多用户、写操作
