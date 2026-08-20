---
name: watch-loops
description: 一体化管控后台 research-loop:自动启动 auto-loops.sh + 每 10 分钟汇报新完成的轮 + 停止。触发 /watch-loops 或"监控后台loop"。新窗口手动调用,窗口保持开即持续汇报。
---

# watch-loops — 后台 research-loop 启停 + 监控汇报

一体化:首次调用**自动启动后台**(若没跑)→ 起 10min cron 汇报;停止时优雅关闭后台 + 删 cron。后台 `auto-loops.sh` 每轮 done 写 marker 到 `logs/loops/round-done.log`(`ts|lane|round|run|status`)。

> 本 skill 只汇报每轮的**因子结果**(verdict/ICIR),**不描述/假设 research-loop 内部流程**(brainstorm 还是变换引擎等由当前分支 `adapt/transform-engine` 的 research-loop SKILL.md 决定)。汇报措辞只讲"第 N 轮 done,因子 X pass/fail ICIR y",不讲流程步骤。

## 文件 / 路径
- **marker**:`logs/loops/round-done.log`(后台每轮 done append)
- **cursor**:`logs/loops/watch.cursor`(本 skill 记上次汇报到的 marker 行数)
- 项目根:`/home/lgao/work/factor-autoloop`;run state:`~/.quant-runs/<run_id>/state.json`

## 流程

### 1. 首次调用 `/watch-loops`
1. **查后台**:Bash `bash auto-loops.sh status`。
2. **若主进程未运行 → 自动启动**:
   - Bash `mkdir -p logs/loops && nohup bash auto-loops.sh 1 > logs/loops/auto.out 2>&1 &`
   - `sleep 8` 后再 `bash auto-loops.sh status` 确认:主进程 pid 存在 + `tmux ls` 出现 `rloop1`。失败 → 报错(`tail -20 logs/loops/auto.out` 看原因),退出。
   - 告知用户:"后台已自动启动(车道1,无限循环)。
3. **若已在运行**:直接进监控,告知"后台已在跑(pid=...)"。
4. **读 marker**:Bash `wc -l < logs/loops/round-done.log` + `tail -3`。文件不存在(首轮还没 done)→ 正常,告知"等首轮 done 后自动开始汇报"。
5. **初始化 cursor**:Bash `wc -l < logs/loops/round-done.log > logs/loops/watch.cursor 2>/dev/null || echo 0 > logs/loops/watch.cursor`(从当前开始,**不回报历史**)。
6. **报初始状态**:车道数 + 当前在跑第几轮(marker 最大 round)+ 最近 done run 摘要(若有)。
7. **起定时汇报**:调 `CronCreate`:
   - `cron`: `"*/10 * * * *"`,`recurring`: true,`durable`: false(session-only,窗口开才报)
   - `prompt`: 下面的 **TICK_PROMPT** 原文
8. **告知用户**:"后台跑着 + 10min 汇报已起,**保持本窗口开**。停止说『停止』(连后台一起优雅关)或『只停汇报』(后台继续)。"

**TICK_PROMPT**(原样传给 CronCreate):
```
[watch-loops tick] 第1步 Bash: 读 MARK=/home/lgao/work/factor-autoloop/logs/loops/round-done.log 总行数 N_now,和 CUR=/home/lgao/work/factor-autoloop/logs/loops/watch.cursor 的值 N_last(文件不存在当 0)。第2步: 若 N_now > N_last,对 MARK 第 (N_last+1)..N_now 行,每行解析 run=<id> round=<r>;对每个 run, Bash python3 读 ~/.quant-runs/<id>/state.json 提取每个 factor 的 name、verdict.verdict、persisted.status、persisted.metrics.icir、evidence.eval_metrics.core_metrics.screening.pair,输出 "  T<idx> <name> <pass/fail> ICIR<x.xx> (<pair里的品种@horizon>)";每个 run 汇报前加标题 "📋 第<r>轮 done (run <id短>)";本轮汇报后附累计 "X pass / Y fail";最后 Bash 把 N_now 写回 CUR。第3步: 若 N_now == N_last,只输出 "⏳ 无新完成的轮"。简洁,每因子一行,不展开。
```

### 2. cron 触发(每 10min,session idle 时)
执行 TICK_PROMPT:读 marker 增量 → 新 run 用 **Bash python3 直接读 state.json**(不要 run_load,7M 会爆)→ 汇报 → 更新 cursor。

### 3. 停止
分两种(按用户说的):

- **"停止" / "关闭" / "全停"**(默认)→ 连后台一起优雅关:
  1. `CronList` → 找到 prompt 含 `watch-loops tick` 的 cron → `CronDelete`
  2. Bash `bash auto-loops.sh stop`(优雅:跑完当前轮自停,不中断研究)
  3. 告知:"监控已停 + 后台已请求优雅关闭(跑完当前轮自停)。进度 `tail -f logs/loops/auto.out`。"

- **"只停汇报" / "后台继续"** → 只删 cron,后台继续跑:
  1. `CronList` → `CronDelete`(watch-loops tick 那条)
  2. 告知:"汇报已停,后台仍在跑。重新监控再 /watch-loops。"

## 汇报样例
```
📋 第 12 轮 done (run 2026-07-31-abc)
  T0 LogRatioOiPriceElastic   pass   ICIR 2.19  (AU@1s)
  T1 LaggedOiImpulseConfirm   fail   ICIR 1.85  (IC冗余 vs T0)
  T2 AddOiCoSignEnergy        fail   ICIR 0.73  (品种泛化)
  累计 12 轮: 2 pass / 34 fail
```

## 边界
- **不报历史**:首次 cursor 设当前行,只监控之后新完成的轮。看历史用 `run_list`。
- **续传不漏**:后台到量/异常(status=running)不写 marker,续传完成才写,不漏报不重报。
- **窗口要开**:session-only cron,窗口关汇报即停(后台脚本不受影响,继续跑)。
- **自动启动用车道1**:N=1 检测最可靠(N≥2 有竞态,脚本注释已说明)。要定轮数后台另起(`ROUNDS=K nohup bash auto-loops.sh 1 &`),别用本 skill。
