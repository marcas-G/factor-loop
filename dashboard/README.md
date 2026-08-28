# 因子库看板 v2

实时 API + React 前端。永不整页刷新:数据更新只亮角标,点击才应用;筛选/滚动/选中全程保留。

## 架构
- `server.py` — 纯 stdlib HTTP 服务:`/api/snapshot`(JSON,ETag 按 db mtime+size 缓存)+ 前端静态托管(SPA 回退)
- `frontend/` — Vite + React + TS;手写 SVG 图表;d3-zoom 用于血缘图
- 数据只读:每次快照新开 `immutable=1` 连接,db 落库即生效,无定时重生成

## 本地开发
    # 终端1: API(仓库根)
    python3 dashboard/server.py --port 8901
    # 终端2: 前端(需要 node ≥ 20)
    cd dashboard/frontend && npm install && npm run dev
    # 打开 http://localhost:5173 (vite 把 /api 代理到 8901)
    # 注意: vite dev 可能绑 IPv6 [::1];若 127.0.0.1 连不上用 --host

## 构建与部署
    cd dashboard/frontend && npm run build
    docker compose -f dashboard/docker-compose.yml up -d --build
    # 访问 http://<host>:8765 ; data/ 以只读挂载进容器

## 刷新行为
- 页面代码中没有 location.reload;手动 ↻ 按钮原地拉取
- 每 60s HEAD 探测 ETag:有新数据只亮"有新数据 · 应用"角标,绝不自动应用
- 筛选/选中/血缘分支同步到 URL hash,刷新/分享链接可恢复现场

## 测试
    python3 core/tools/test_dashboard_snapshot.py
    python3 dashboard/test_server.py
    cd dashboard/frontend && npx vitest run && npx tsc --noEmit
