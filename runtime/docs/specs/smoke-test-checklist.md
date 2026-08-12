# 第一期烟雾测试 Checklist

## 环境

```bash
export QUANT_MCP_MOCK_PLATFORM=1
export BRAINSTORM_ONLY=0
```

启动 Claude Code（在 quant 根目录，让它加载 .claude/settings.json 注册的 quant-mcp server）：
```bash
cd /home/lgao/work/quant && claude
```

新会话起来后，先确认 MCP server 加载：
- 让 Claude 调 `mcp__quant-mcp__health` 工具，应返回 `{ok: true, ts: "..."}`
- 让 Claude 列出可用的 mcp__quant-mcp__* 工具，应有 15 个

## 测试 A：BRAINSTORM_ONLY（只到 Step 1）

1. 在会话里说：`用 research-loop skill，N_FACTORS=1，只跑到 brainstorm 阶段就停`
2. 或：直接告诉 Claude "执行 /research-loop 但只到 Step 1"

**期望**：
- [ ] Claude 调 `run_init` 拿到 run_id
- [ ] Claude 调 `factor_counts` / `factor_list` / `factor_recent_lessons`
- [ ] Claude 调几次 `factor_search`（围绕 idea 的关键词）
- [ ] 产出 1 个候选 factor（含 formula/intuition/categories/params）
- [ ] 调 `persist_idea` 拿到 idea_id
- [ ] 按 index 调 `run_save` 写入 idea + idea_id + factors.<index>
- [ ] 停在 Step 1 末，向用户报告 brainstorm 结果

**验证命令**（在 sdk-demo 跑）：
```bash
ls -la ~/.quant-runs/<run_id>/
cat ~/.quant-runs/<run_id>/state.json | jq '.idea, .idea_id, .factors'
```

**通过标准**：
- state.json 存在且合法
- idea 字段非空
- factors[0] 含 name/formula/hypothesis（拼接的）/categories

## 测试 B：完整循环（mock 平台，1 个 factor）

1. 在会话里说：`跑完整 research-loop，N_FACTORS=1`

**期望**：
- [ ] Step 1 完成（见测试 A）
- [ ] Step 2：Claude 在一个消息里发 1 个 Task tool call 调起 run-factor-agent
- [ ] run-factor-agent 调 Skill write-factor 写出 `.h` 文件
- [ ] run-factor-agent 调 `mcp__quant-mcp__submit_factor`（mock 返回 ok=true）
- [ ] run-factor-agent 调 `mcp__quant-mcp__check_factor`（mock 返回 check_done + evidence.eval_metrics）
- [ ] run-factor-agent 返回 `{failure_layer: "check_done", evidence: {...}}`
- [ ] Claude 调 `run_save` 写 factors[0].failure_layer + last_rewrite
- [ ] Step 3：Claude 加载 evaluate.md，推理出 verdict（pass/fail）
- [ ] Claude 调 `persist_factor` 写库
- [ ] Claude 调 `run_save` 写 factors[0].verdict + status=done
- [ ] 报告：1 个因子，verdict=<pass 或 fail>

**验证命令**：
```bash
ls -la /home/lgao/work/quant/factors/<AlphaName>.h
sqlite3 /home/lgao/work/quant/sdk-demo/factors.db "SELECT xname, status FROM factors WHERE xname='<AlphaName>'"
sqlite3 /home/lgao/work/quant/sdk-demo/factors.db "SELECT type, substr(text, 1, 50) FROM lessons ORDER BY id DESC LIMIT 1"
cat ~/.quant-runs/<run_id>/state.json | jq '.status, .factors[0].verdict, .factors[0].last_rewrite'
```

**通过标准**：
- .h 文件存在
- factors 表有该 xname（status=evaluated 或 dead_end，取决于 verdict）
- lessons 表新增一条（type=success_pattern 或 dead_end）
- state.json 的 status="done"，factors[0].verdict 非空

## 测试 C：断点续传

1. 跑测试 B，但在 Step 2 中途（子代理还没返回时）按 Ctrl+C 打断会话
2. 重启 Claude Code，说：`/research-loop <之前的 run_id>`

**期望**：
- [ ] Claude 调 `run_load {run_id}` 读到 state
- [ ] 看到 status=running 且 factors[0].status=submitting/pending，决定从 write 步重开
- [ ] 删除半成品 `.h` 文件（如存在）
- [ ] 继续跑下去直到完成

**通过标准**：
- 至少能识别断点状态（不要求完美续传，能报告"已存在的 run 状态"即可）
- 完美续传非必需（可留给第二期）

## 失败处理

- 任何 MCP 工具调用失败：先看 `~/.quant-runs/<run_id>/state.json` 的 status
- 子代理返回 agent_crashed：看 Task 工具的 error 信息
- 写库失败：直接看 sqlite 报错
- MCP server 没加载：检查 `/home/lgao/work/quant/.claude/settings.json` 的 `mcpServers.quant-mcp` 配置 + `cd /home/lgao/work/quant/sdk-demo && node mcp/server.mjs` 能否手动启动

## 完成后的清理

```bash
# 备份测试产物（不要直接删）
mkdir -p ~/quant-mcp-smoke-backup
cp -r ~/.quant-runs/<run_id> ~/quant-mcp-smoke-backup/

# 如果因子入库了，给 xname 加 _smoke 后缀避免污染正式库（或直接 sqlite3 删）：
# sqlite3 /home/lgao/work/quant/sdk-demo/factors.db "DELETE FROM factors WHERE xname='<AlphaName>'"
# sqlite3 /home/lgao/work/quant/sdk-demo/factors.db "DELETE FROM factor_evals WHERE factor_xname='<AlphaName>'"
# sqlite3 /home/lgao/work/quant/sdk-demo/factors.db "DELETE FROM lessons WHERE text LIKE '%<AlphaName>%'"
```

## 测试结果（实跑后填）

### 测试 A 结果

- 跑了：[ ] 是 [ ] 否
- run_id: 
- 实际现象：
- 偏离期望的地方：
- 结论：[ ] PASS [ ] FAIL（原因：）

### 测试 B 结果

- 跑了：[ ] 是 [ ] 否
- run_id: 
- 因子 xname: 
- failure_layer: 
- verdict: 
- 实际现象：
- 偏离期望的地方：
- 结论：[ ] PASS [ ] FAIL（原因：）

### 测试 C 结果

- 跑了：[ ] 是 [ ] 否
- 原 run_id: 
- 续传起点：
- 实际现象：
- 偏离期望的地方：
- 结论：[ ] PASS [ ] FAIL [ ] PARTIAL（原因：）

## 第一期完成标准

- [ ] 20 个 L1 单元测试全过（health 2 + factor-db 7 + state 5 + persist 3 + platform 3）
- [ ] 测试 A 跑通
- [ ] 测试 B 跑通至少 1 次
- [ ] 测试 C 能识别断点状态
- [ ] git log 清晰（每个 Task 一个或多个 commit）
