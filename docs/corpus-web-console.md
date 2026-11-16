# Corpus Research Console · 语料研究工作台

这是《道德经》81 章语料研究循环的 **React + TypeScript Web 前端**。不是原有的静态因子看板，不修改量化执行逻辑、因子库或研究台账。

## 技术栈

| 层次 | 技术 | 目的 |
|---|---|---|
| UI | React 19 + TypeScript 5.9 | 类型化组件与交互 |
| 工程 | Vite 8 | 本地开发、构建与资源处理 |
| 样式 | Tailwind CSS 4 + 独立 CSS 设计变量 | 主题、响应式布局 |
| 导航 | React Router 7 | URL 中持久化研究对象 ID |
| 数据 | TanStack Query 5 | API 查询、缓存、30 秒轮询、手动刷新 |
| 图表 | Recharts 3 | 基于真实事件的活动趋势；无事件时显示空态 |
| 图标 | Lucide React | 一致的图形语言 |
| 质量 | Vitest + Testing Library + ESLint + TypeScript | 单测、无障碍相关断言、类型和风格检查 |
| 后端 | Python 3 标准库 + SQLite 只读连接 | 无需额外服务端依赖，安全读取研究状态 |

## 运行

前置条件：在已有的 `factor-loop` 仓库根目录下执行。确保有 Node.js 22.12+ 与 Python 3.11+。

### 开发模式（两个终端）

```bash
# 终端一：仅启动只读 JSON API，不需要提前 build
python -m core.corpus_autoloop.web_api --api-only --port 8765

# 终端二：React HMR 服务器；/api 代理到上方的 API
cd web
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:5173。

### 构建并使用同一端口部署

```bash
cd web && npm install && npm run build && cd ..
python -m core.corpus_autoloop.web_api --port 8765
```

浏览器打开 http://127.0.0.1:8765。这一模式由 Python 同时提供 `web/dist` 静态资源与 `/api` JSON，**无需单独代理**。

### 指定运行数据

```bash
python -m core.corpus_autoloop.web_api --port 8765 \
  --db ~/.quant-corpus-autoloop/research.sqlite3
```

数据库不存在：显示真实的 81 章文本和“未初始化”状态；不会创建文件、虚构 IC 或入库状态。

已执行 `python -m core.corpus_autoloop.cli seed`：展示真实研究队列与已记录的假设、原文、因子、ICIR、R²、残差 IC 和研究事件。所有量化写入操作仍需原项目 CLI 明确调用。

## API 契约

| 方法与路由 | 数据 | 写操作 |
|---|---|---|
| `GET /api/health` | 数据源状态 | 无 |
| `GET /api/dashboard` | 81 章、研究对象、指标摘要、最近 200 条事件 | 无 |
| `GET /api/objects/RO-DDJ-001` | 指定研究对象、原文、分裂谱系、最近事件 | 无 |
| `POST /api/*` | `405 read-only API` | 不提供 |

默认绑定 `127.0.0.1`。接口未实现认证，不应该直接公开到互联网或没有访问控制的局域网。浏览器仅通过同源 API 访问数据，Vite 开发代理不转发任何外部地址。

## 页面功能

- 81 章章节队列，按道经／德经、状态与关键词筛选，分页与 URL 定位
- 研究对象详情四个视图：**研究假设、章节原文、实验证据、假设拆分树**
- 真实指标展示（无对应数据一律展示 `—`）、研究活动趋势、事件日志
- 手动刷新与每 30 秒轮询、JSON 导出、适配移动端
- 源语料版次与 `draft` 来源状态保留展示；模型输出与实证结果严格区分
- **只读**：不允许绕过实验、确认或入库门禁

## 质量保证

```bash
cd web
npm run typecheck
npm run lint
npm run test
npm run build
cd ..
python -m unittest discover -s tests -p test_corpus_web_api.py -v
```

CI：`.github/workflows/validate-corpus-web.yml`。

> 不应把这套页面理解为“已经找到有效因子”。前端只展示现有 SQLite 台账已有的真实字段，不宣称生产量化平台已完成部署或收益验证。
