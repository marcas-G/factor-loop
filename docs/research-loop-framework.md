# Research Loop 完整执行框架

> 本文是 research-loop skill 全链路的架构文档：设计哲学、各 Step 内部机制、横切质量保障、数据资产、时序视角与已知粗糙点。
> 相关文档：`docs/architecture.md`（系统架构）、`docs/research-data-flow.md`（数据流）、`.claude/skills/research-loop/SKILL.md`（执行入口）。

---

## 一、设计哲学：这条流水线在解决什么问题

因子研究的典型失败模式有四种，整个框架的每个部件都在针对性防其中一种：

| 失败模式 | 框架对策 |
|---|---|
| **重复发明**：换个写法重造库内已有的因子 | G4 归约审查 + ridge_svd 撞族检验 |
| **推理天衣无缝、代码是垃圾**：假设论证很漂亮，实现走样 | repair_contract 硬约束 + 忠实度审稿 |
| **高 IC ≠ 新信息**：ICIR 很高但全是库内已知信息的换皮 | 冗余度首要原则（res_IC 才是价值判据） |
| **线索丢失**：失败方向反复踩、成功方向无人接续 | iteration suggestions + dead_end lesson + research_state |

另一个核心理念是**三层资产分离**：

- **算子 = 资产**（可复用的测量方法，语义层注册，不受实证结果影响）
- **因子 = 产品**（算子 + 基底 + 参数的一次实证绑定，assess 管 pass/fail）
- **教训 = 记忆**（lesson 表被下一轮 brainstorm 检索，成功经验与避雷同样值钱）

---

## 二、总览：一条认知驱动的因子生产线

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 0  初始化                                                   │
│   run_init → run_save(parent_session)                            │
│   [断点续传: run_load → 看 factors[].status 从断点继续]            │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 1  认知协议（循环起点）                                        │
│   选 Research Object（iteration_list_open 优先 / dead_end / 现象） │
│   → factor_saturation_status {xname}                             │
│      ├─ saturated (branch max_depth>5) → Skill reseed            │
│      └─ not saturated → Skill cog-protocol                       │
│           ① NEW OPERATOR → register_operator → Step 2 入口 A     │
│           ② FACTOR_ITERATION → repair_contract → Step 2 入口 B   │
│           ③ RESEED SEED → seed_spec → Step 2 入口 C              │
│           ④ 无产出 → 换对象重跑（耗尽则 done）                      │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2  候选落地                                                  │
│   入口 A: operator contract → 主会话翻译 formula/params           │
│   入口 B: repair_contract 原样传（只能翻译不能发挥）                │
│   入口 C: seed_spec 最小直接公式（禁止复杂化）                     │
│   → persist_candidates {run_id, idea_text, factors[]}            │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3  执行（每因子一个 run-factor-agent 子代理）                  │
│   write(.h, 内嵌 write-factor 规范) → submit(CPU csv_ic +         │
│   GPU ridge_svd 并发) → check(分诊 failure_layer) →               │
│   restest(R2_X/res_IC) → 终态 run_save                           │
│   三类 budget: code=3 / transient=3 / quality=3                  │
│   主会话兜底: run_load 验终态, 断流则禁 Skill 重派                 │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4  评估（check_done 因子串行）                                │
│   Skill assess: 忠实度(有论证链才审) → prepare 入表 →              │
│   verdict(双闸门+冗余首要) → commit 入库 → realize/open 迭代管道   │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5/6  收尾                                                   │
│   reseed 接力(next_research_object) → support_score 汇总 →        │
│   run_save {status: done} → 报告                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、Step 0 · 初始化与断点续传

### 新建路径

```
run_init {} → 拿 run_id（格式: 日期-随机后缀, 如 2026-08-24-v2r2gj）
run_save {parent_session: "claude-code-session-<date>"}  ← 记录哪个会话拥有这个 run
```

run 的全部状态存在 `~/.quant-runs/<run_id>/state.json`，MCP 工具原子读写。

### 断点续传路径

给了 `run_id` 就 `run_load` 读 state，按下表决定从哪步恢复：

| 观察到的状态 | 恢复动作 |
|---|---|
| `status == "done"` | 报告已完成，结束 |
| `factors[i].status == "pending"` | 该因子还没跑，从 Step 3 重派 |
| `factors[i].status == "submitting"` | .h 已生成但没到终态，重派（agent 会先删旧 .h 重开） |
| `factors[i].status == "done"` 但 `verdict == null` | 跑完了但没 assess，从 Step 4 继续 |

### 定向接力机制

`state.next_research_object` 是 reseed 轮之间的交接棒：上一轮 reseed 产出的 seed 因子 persist 后，把它的 xname 写进这个字段，下一轮 Step 0 **跳过所有随机/R1 选择逻辑直接用它**。进入 Step 1 后立即清空（`run_save {next_research_object: null}`），防止污染再下一轮。

---

## 四、Step 1 · 认知协议（循环的发动机）

### 4.1 选 Research Object 的优先级

```
1. state.next_research_object（reseed 接力, 最高优先）
2. iteration_list_open {top_k: 5}（open 的迭代建议, 按 priority 降序）
   priority = (evaluated ? 2.0 : 0.5) × exp(-age_days / 14)
   —— pass 过的源因子权重 4 倍于没跑过的, 两周半衰期
3. factor_list {k} 里最近的 dead_end（避雷后再攻）
4. coverage_gaps / discover_failed_hypotheses（库级盲区扫描）
```

### 4.2 饱和度硬门槛

选中对象后**必须**先调 `factor_saturation_status {xname}`：

- `saturated == true`（branch max_depth > 5）→ 走 **reseed**，禁止继续深挖。逻辑：一条血缘分支已经迭代 5 层以上，边际收益递减，强制换根。
- `saturated == false` → 走 **cog-protocol**。

### 4.3 cog-protocol 内部（S1 → S2 → S3）

```
S1 profile(双视图隔离)
  ↓ construction_view
S2.1 assumption agent(盲态, 拆 F(A)=F(B) 假设)
  ↓ .tmp/assumptions.json
S2.1.5 概念编译 agent(角色分配+四档可观测性) ←→ concept_lexicon.json(词表回填闭环)
  ↓ .tmp/test_contracts.json
S2.2 evidence 程序(contract优先/词表fallback; 分裂检测+一致性+UNTESTABLE)
  ↓ evidence_card
S2.3 adjudicator(揭盲, 四档) ── 仅 CONTRADICTS 继续
  ↓ challenge
S2.4 hypothesis agent(≥3+H0, 回盲态) → S2.5 distinction 两层(主会话)
  → S2.6 minimal-repair(depth+identifiability)
     ├─ STRUCTURE+DERIVABLE → S3 发明链(4 Gate)
     └─ STATIC/RAW → repair_contract → factor loop
```

#### S1 · Factor Profile 构造

```bash
python3 core/cog/factor_profile.py <xname>
```

产出四个视图，其中两个关键视图**物理隔离**：

- `construction_view`：formula_text + params（公式怎么算的）→ **只给 assumption-extractor**
- `evidence_view`：IC/ICIR/lessons/siblings（跑得怎么样）→ **只给 adjudicator**

为什么隔离：假设拆解必须"从公式能推出什么"，如果拆假设的 agent 看到了 IC 表现，会不自觉地按结果倒推假设（事后归因），拆出来的假设就被行为证据污染了。

#### S2.1 · Assumption 拆解（派 agent）

拆出公式的隐含前置假设，每条必须是严格 schema：

```
F(A)=F(B) 形式     —— 公式把哪两个真实不同的市场过程压成同一个数
held_equal: [具体列名]  —— 被保持相等的量（无泛化词）
collapsed:  [具体列名]  —— 被压掉的信息
behavioral_difference: UNKNOWN  —— 行为差异必须未知
（禁止出现 IC/收益/alpha 等行为词）
```

主会话 schema 自检不过就打回重拆。典型产出 8-12 条，覆盖输入/参与者/结构三维度。

然后主会话把 assumptions 数组写进 `.tmp/assumptions.json`——这是 S2.2 程序层的输入文件。

#### S2.1.5 · 概念编译（派 agent，v2 新增）

假设是"人话"（如"成交推动 vs 撤单迁移不可区分"），程序需要的是"哪两列做检验"。中间隔一道**角色分配**问题——谁当 held（控制变量）谁当 collapsed（被压量）是句子语义，关键词匹配会反转。因此 S2.1 与 S2.2 之间插入概念编译 agent（定义在 `.zcode/agents/cog/cog-concept-compiler.md`）：

```
输入: assumptions + data/concept_lexicon.json(词表) + 89 派生列清单
输出: .tmp/test_contracts.json — {assumption_id: {held_col, collapsed_col, observability, new_concepts}}
```

- **角色规则**：held = 假设主句"公式已编码"的量；collapsed = 认知盲区段"被压掉"的量
- **四档可观测性**：DIRECT（词表命中）/ DERIVABLE（89 列语义等价物）/ PROXY_ONLY（近似代理）/ UNIDENTIFIABLE（原则性构造不出，如参与者身份/order 配对）
- **盲态保持**：编译 agent 只看字典（词表+列清单），不看任何 IC/表现——双盲链条不被新环节打破
- **概念缓存闭环**：new_concepts 由主会话回填 `concept_lexicon.json`，跑得越多词表越厚，agent 只处理真新概念

设计动机（实测数据）：历史 143 假设里 UNCLEAR 率 40%、裁判 OOD 率 23%（多数是列匹配错位）；且"可观测 ≠ 列名存在"——"成交推动"可从价动×量动构造，纯查表够不着。

#### S2.2 · Evidence Investigation（程序层，1 次 CLI，v2）

```bash
python core/cog/evidence_investigate.py \
      --assumptions-file .tmp/assumptions.json --xname <xname> \
      --contracts-file .tmp/test_contracts.json \
      [--mode investigation|legacy] 2>/dev/null
```

程序对每条假设做**偏 IC 检验**：按 held 列分 5 个分位 bin，算每个 bin 内 collapsed 列的偏 IC。v2 判定顺序（分裂优先、一致性把关、可测试性分流）：

| 判定 | 条件 | 后续 |
|---|---|---|
| CONDITIONAL_SPLIT | per-bin IC 跨零且 spread>0.04 | 送裁判，重点审分裂结构（勿看平均） |
| CONTRADICTS | 平均>0.02 **且 ≥80% bin 同号** 且 > held IC×0.3 | 送裁判语义确认 |
| SUPPORTS | 平均<0.005 | 假设成立，销案 |
| UNCLEAR | 边界或方向不一致 | 送裁判 |
| UNTESTABLE | 概念构造不出（编译判 UNIDENTIFIABLE 或词表+契约都空） | 盲区登记素材，**不派裁判** |

匹配来源两级：agent contract 优先（`match_source: agent_contract`，角色精确）→ 词表双通道 fallback（collapsed 从盲区段找、held 从全文找、互不同列）。

**历史问题与 v2 修正的对应**（143 假设/60 裁定的实测基线）：

| 旧引擎问题 | 实测 | v2 修正 |
|---|---|---|
| 平均值埋掉分裂 | A10 型真矛盾（±0.045/±0.025）被平均成 -0.0096 边界值，靠裁判肉眼救 | CONDITIONAL_SPLIT 档程序直接命中 |
| 假阳性 | CONTRADICTS 精确率 22%（67 喊 15 真） | 方向一致性 ≥80% 闸门 |
| 匹配不到即蒸发 | 谈过程/参与者的假设（常标 HIGH）永远 UNCLEAR | 概念编译 + UNTESTABLE 分流 + 盲区登记 |
| 角色反转 | 词序 heuristic 把 held/collapsed 分反 | agent 读句分配 |

**数据基底**：`evidence_derive` 从 14 原始探针派生 89 维度（深度分布/hawkes 族/事件代理/意图-行动族等）——派生列目录=库的历史概念词汇表，"可观测"定义为这个函数空间内可构造。

**为什么仍需 adjudicator 复核**：程序算数确定，但"数字能否反驳假设"是语义问题——检验构造错位（假阳性）、单 bin 覆盖不全（证据完整性）、代理近似（降置信）都需要读案判断。v2 后裁判只审有货的案子（实测 5 案/轮 vs 历史 ~10）。

#### S2.3 · Adjudicator（四档裁定）

```
CONTRADICTS  → 证据真反驳假设, 产 challenge, 继续 S2.4
CONSISTENT   → 假设无恙, 本 Factor STOP
INSUFFICIENT → 证据不足, STOP
OOD          → 检验域外(匹配错位), STOP
```

注意 **NO_CONTRADICTION 是合法成功输出**——adjudicator 的职责是判"证据是否有效"，不是"必须找到 challenge"。这个防逼供设计保证只有真矛盾才进入后续发明链。

#### S2.4 · Hypothesis 生成

对 challenge 给 ≥3 个互相竞争的结构解释 + H0，每条带 `what_it_predicts_uniquely`（它独自预言什么观测）。防"可能 A 可能 B"的和稀泥解释——竞争解释必须可区分。

#### S2.5 · Evidence-Constrained Distinction（主会话）

把最可区分的假设对拆成两层：

- **Layer 1 supported_distinction**：evidence 最小能推出的区别（可继续）
- **Layer 2 hypothesis_explanation**：机制解释（标记 UNTESTED，minimal-repair 不审）

这层拆分防止把"机制故事"当成"已证事实"往下传。

#### S2.6 · Minimal Repair v3 + 可识别性

两问合一：

1. **depth**：恢复 raw 输入（N1）+ 现有静态算子闭包（N2：max/sum/pct_rank/tanh 门控/线性组合）能否直接表达 Layer 1 的 distinction？
   - 都不够 → `STRUCTURE_NOT_REDUCIBLE`（真缺口）
   - N2 够 → `STATIC_SUFFICIENT` → FACTOR_ITERATION + repair_contract
   - N1 够 → `RAW` → 同上
2. **identifiability**（STRUCTURE 才判）：required_object 能否从当前数据域构造？
   - DIRECT/DERIVABLE → 可构造 → 进 S3
   - UNIDENTIFIABLE（OBS001 order identity 等永久边界）→ archive STOP

**v3 关闭 N3 的原因**：旧版把"动态统计够不够"（N3）也放在这判，和 N2 的静态闭包判定纠缠。v3 把动态统计语义判定移到 G4 归约——minimal-repair 只判"结构层缺口是否存在"，归约判"这个缺口是否已被现有算子覆盖"。

#### S3 · Operator Invention（4 Gate）

```
S3.0 主会话拼 Gap Card + 剥因子名/alpha/IC/交易故事（防锚定原因子语义）
S3.1 operator-abstraction: Stripped Gap View → carrier ontology + 通用测量问题
S3.2 operator-inventor:   ≤3 个正交候选（函数级/表示级/因果级等不同抽象角度）
S3.3 transfer-critic:     四道 gate
     G1 context independence —— 删掉交易故事后语义仍成立（用非金融领域复述）
     G2 heterogeneous binding —— 能绑 ≥3 种异质基底且测量语义不变
     G3 round trip —— 绑回原始数据域能还原 supported_distinction
     G4 factor disguise —— 不是现有因子的换皮
S3.4 reduction-critic:    G4 归约(NULL attack)
     现有算子+组合能否构造相同测量语义? + 库查重(semantic/composition/rename)
     → NEW_OPERATOR_NEEDED + NOVEL 才继续; REDUCIBLE → STOP
S3.5 主会话 round-trip 终检
```

**G4 是防重复发明的核心**。实证案例：3 个候选全过 transfer 四门，但 G4 给出归约构造式——`sign(滚动跳变能量比 - θ) × run_length` 只需要比较器 + 滚动比值 + 乘法，全是闭包内原语。此时**不注册算子**，改为把归约构造式直接当因子提交验证。这避免了"语义上新颖、构造上冗余"的伪资产入库。

### 4.4 认知产出闭环

每次 cog-protocol 跑完必须立即记录 research_state（R1 下一轮选对象的依据）：

```bash
python core/retrieval/derived_tables.py --record-attempt <xname> <OUTCOME>
# OUTCOME: NEW_OPERATOR / FACTOR_ITERATION / INSUFFICIENT / CONSISTENT / OOD / CONTRADICTS
```

连续无产出（INSUFFICIENT 等）会累积 exhaustion 信号，R1 后续轮会降低该对象的优先级。

---

## 五、Step 2 · 候选落地（三入口汇聚）

| 入口 | 输入 | write 的自由度 |
|---|---|---|
| A: NEW OPERATOR | operator contract（10 字段） | 主会话翻译成 formula，按基底换绑定 |
| B: FACTOR_ITERATION | **repair_contract**（结构化 spec） | **零自由度，只能翻译** |
| C: RESEED SEED | seed_spec（measurement_object + operation） | 最小直接公式，禁止复杂化 |

### repair_contract 的五要素（入口 B 硬约束）

```yaml
preserved_signals:  [必须保留的信号]     ← 少一个 → 重写
new_signals:        [新增信号+计算方式]  ← 不得自己发明度量
forbidden_drops:    [禁止丢弃的信号]     ← 即使看起来冗余
gating_logic:       [门控伪代码]         ← 精确翻译
output_composition: [输出组装伪代码]
```

主会话在 .h 写完后逐项核对代码里是否每个 preserved/forbidden 信号都在。实证案例：`RegimeModulatedRunLength_W200` 的 contract 甚至写明"regime_sign 必须硬 {+1,-1} 翻转，禁止 tanh 平滑替代"——因为 G4 判定时就是靠硬符号翻转区分于平滑门控的，实现走样等于没测假设。

### categories 语义（P0 易错）

`categories` = **品种代码数组** `["AG"]`，合法值仅 `AG/AU/CU/AL/NI`。不是 tags、不是 xname。填错被 `platform_submit_factor` 拦截返回 `config_error`（防拼出畸形 feeds 导致 DAG failed）。

### persist_candidates 的 claim 机制

```
persist_candidates {run_id, idea_text, factors[]}
→ 内部 persist_idea + 逐因子入库 + 尝试 claim suggestion_id
```

claim 是独占的：一条 open 建议**只能被一个因子 claim**（in_progress 状态不可再 claim）。已知边界：多变体共享一条建议时，第二个因子 claim 失败，只能记 `iterates_from` 弱关联 + `suggestion_ref`，不阻断流程但归档链不完整。

---

## 六、Step 3 · run-factor-agent（单因子状态机）

### 6.1 为什么是子代理 + 为什么 write 内嵌

每个因子一个独立 context 的子代理（隔离防串味）。**头号历史 bug**：agent 调 `Skill write-factor` 后停在 skill 返回处（model 把"完整交付"当任务终点），衔接硬规则治不了——这是 model 行为不是规则问题。**根治方案**：agent 的 tools 里根本不给 Skill，write 步改为 `Read write-factor/SKILL.md 规范 → 自己 Write .h`。结构上不可能在 skill 返回处停。

### 6.2 状态机与三类 budget

```
write → submit → check → restest → 终态落盘
```

failure_layer 分三侧，各自独立预算：

| 侧 | failure_layer | 动作 | budget |
|---|---|---|---|
| 因子代码 | compile_failed / factor_runtime_crash / factor_runtime_error | 读 evidence.cause_text + diagnosis 定向修 .h 重提 | 3 |
| 因子质量 | check_output_too_small / check_failed | 降分位/软化门控/缩冷启动 | 3 |
| 平台瞬时 | platform_transient / check_output_missing | 重 check / 重 submit（不重写） | 3 |

崩溃修复的头号检查项：**per-feed 容器没 resize 到 `_numFeeds` 就 `operator[]`** → SIGABRT。修崩溃优先查这个，别只盯编译。

### 6.3 平台交互细节

- `platform_submit_factor`：一次调用**并发提交** CPU csv_ic（IC 分析）+ GPU ridge_svd（冗余分析）
- `platform_check_factor`：内部阻塞等 DAG（`--wait --max-wait=540`），agent 只调 1 次不轮询；**evidence 由工具内部直接落 state**——不经 agent 的手，防 LLM 总结倾向截断/重命名字段（历史 bug：stdout_tail 被清空）
- `platform_restest_factor`：check_done 后必做收尾，等 GPU 任务 → 下载 → 聚合 R2_X/res_IC 落 state。失败重试一次，仍失败记 retry_trace，assess 会标"冗余未检"压低置信度——**不允许静默放弃**

### 6.4 主会话兜底（断流根治）

每个 agent 返回后 `run_load` 验证 `factors[i].status` 是终态且字段齐全：

```
缺失（断流特征）:
  ① ls factors/<name>.h —— .h 已生成 → 重派同 agent，prompt 明令
     禁调任何 Skill、从 platform_submit_factor 起步跑完
     （硬规则无效时的唯一可靠推进方式，已验证）
  ② 重派仍卡 → run_save 兜底 agent_crashed，继续其它因子
  ③ .h 都没生成 → 兜底 agent_crashed，后续单独补 write 再重派
```

### 6.5 迭代回滚

批次跑完后扫一遍：`status==failed` 且 `suggestion_id` 非空的（接续候选没跑成），调 `iteration_reopen` 把建议从 in_progress → open——精进线索不因一次执行失败而丢失。check_done 的不回滚（由 assess 的 realize 归档）。

---

## 七、Step 4 · assess（双轨判定）

### 7.1 判定核心：闸门 → 冗余

```
第一轨: 过关闸门（二元, 全过才活）
  忠实度 → ICIR≥0.3 → |rank_ic|≥0.01 → 可交易 → 无反转
第二轨: 冗余度首要（过闸门后, 价值由边际信息定, 不由 ICIR 定）
```

**ICIR 强弱只作闸门不作排序**——组合价值 = 信息维度多样性。实证案例：`PricePathImbLevelContribution` ICIR=13.2 全场最高，但 R2=0.853 + res_IC=0.003 → 冗余否决 fail；同时段 ICIR"只有"11.8 的拆解版因不冗余而 pass。

### 7.2 忠实度（第零维）

- 前提：假设有结构化 argument_chain（`hypothesis_get` 读）才审；散文假设跳过（无法对照）
- 派 reviewer-agent（session 隔离，只收论证链 artifact + .h 文件，不收作者推理）
- `unfaithful` → 一票否决。IC 高也是别的机制的功劳，假设未被验证

### 7.3 预测力双闸门 + 稀疏口径陷阱

```
可信口径取法:
  稀疏(zero_rate≥0.5) → daily 口径(逐日 IC mean/std)
  稠密 → screening pooled 口径
```

为什么必须切换：pooled ICIR 对稀疏因子**系统性虚高且可能反号**——被少数触发日主导。实测案例：zero_rate=0.94 的因子 pooled ICIR=5.50，真实逐日 ICIR=-0.89。稠密因子也要对照 daily，符号相反即口径异常。

低信噪比的连带后果：ICIR<0.3 的因子"和谁都低相关" → 假正交 → 冗余度判定不可信。所以双闸门不过直接 fail，连冗余分析都不用做。

### 7.4 冗余判据（唯一口径 = 平台 ridge_svd）

```
R2_X>0.8 且 |res_IC|<0.01 → X 空间冗余, fail
R2_X≤0.8                 → 不冗余
无 ridge_svd             → 冗余未检(缺维, 非 fail), verdict 谨慎
```

平台在 X 空间对 72 因子库做正交化，R2_X = 库能解释新因子的方差比例，res_IC = 剥掉库冗余后的增量 IC。

### 7.5 一票否决清单

1. 样本外秩 IC 符号反转
2. 推进式回测失败（连续多月亏/后期断崖）
3. 成本翻倍（16bps）夏普转负
4. 预测力双闸门任一不过（救场条款：变换族某形态 |IC|≥0.3）

### 7.6 迭代管道（verdict 之后）

```
A. 接续来的(suggestion_id 非空) → realize 归档
   icir_delta = B.icir - A.icir → outcome 自动推导 improved/declined/neutral
   演进链 A→B 落定, 血缘边写入

B. 开新建议(iterable 判定)
   pass 或 dead_end 有重试价值(|icir|≥0.05) → iteration_open
   dead_end 无救 → 不开, dead_end lesson 自动避雷
```

注意 realize 的 icir_delta 对**符号翻转类实验**会给出误导性 declined（如 +11.85 → -12.13 记为 declined，但 res_IC 才是目标指标且已翻正）——这是当前管道的已知粗糙点，target 指标选择在翻转实验里需要人工判断。

---

## 八、Step 5/6 · 收尾与汇总

### 算子注册位置

不在收尾步——S3 产出 contract 且 4 Gate 过时**立即注册** operators 表（source='cog'）。**不受 ICIR 影响**：ICIR 不达标只否定该次因子实现（可能是基底/参数选错），不否定测量方法本身。

### support_score 连续化汇总

```
hypothesis_get {idea_id} → support_score(贝叶斯平滑, 0-1 连续) + evaluated_factor_count
```

**不判绝对成立/否决**——假设级保留不确定性，报告连续支持度 + pass/fail 分布 + key 教训。这是认识论上的克制：N 个因子的失败不能逻辑上推翻假设，只能降低支持度。

### reseed 接力

本轮有 reseed 因子（tags 含 reseed / reseed_from 非空）→ persist 后写 `next_research_object`，下一轮直接接。

---

## 九、横切机制

### 衔接硬规则（反断流）

5 个 Step 边界各规定"必须立即做的第一个 tool call"，禁止纯文字回合。需要汇报中间状态时，文字与下一 tool call 放**同一回合**。唯一例外：`status == "paused"`（如认知协议连续 3 次无产出）。

### 错误处理表

| 情况 | 行为 |
|---|---|
| MCP 连续失败 3 次 | run_save {status: paused}，报告，停止 |
| 子代理超时/崩溃 | 标 agent_crashed，继续其它 |
| assess 失败 | verdict=fail + "eval_metrics 缺失"，继续 |
| 断点续传发现 .h 已存在但非 done | agent 先删 .h 从 write 重开 |

### 绝对禁止

- ❌ kill 任何 MCP server 进程（stdio server 不自动重连 → 全部工具不可用 → 死循环）
- ❌ 主会话直接 Bash 调废弃的 factor-cli.mjs / 直接 Write .h / 直接跑 write/submit/check
- ❌ run-factor-agent 改 core/ 源码（执行者不是开发者）
- ❌ assumption agent 看 evidence（视图泄漏）

### 数据资产全景

| 存储 | 角色 | 谁写 |
|---|---|---|
| run state.json | 单轮执行状态 | run_save（原子 patch, 禁整体覆盖 factors） |
| factors 表 | 因子库（formula/metrics/verdict/lineage） | persist_factor |
| lessons 表 | 成功模式 + dead_end 避雷 | persist_factor 自动 |
| ideas 表 | 研究假设（含 argument_chain/support_score） | persist_idea / persist_argument_chain |
| operators 表 | 可复用测量方法资产 | register_operator（4 Gate 过） |
| iteration suggestions | 跨轮迭代线索 | iteration_open/realize/reopen |
| research_state（derived_tables） | 每因子的认知尝试记录（R1 选对象依据） | --record-attempt |

---

## 十、一轮的完整生命周期（时序视角）

```
T0   run_init → run_id
T1   选对象（open 建议优先）→ saturation 检查
T2   cog-protocol:
     profile → assumptions(10条) → 【概念编译 agent】(角色分配+四档可观测性)
     → evidence v2(contract优先/分裂检测/一致性) → adjudicator(只审有货案子)
     → [可能 STOP 换对象, 最多 2-3 轮] → challenge
     → hypotheses(3+H0) → distinction 两层 → minimal-repair
     → [STRUCTURE → S3 发明链 4 Gate] 或 [STANDARD → repair_contract]
     → record-attempt; 词表回填(概念缓存闭环)
T3   persist_candidates（idea + N 因子 + claim suggestion）
T4   并行/串行派 N 个 run-factor-agent:
     每个: Write .h → submit(CPU+GPU 并发) → check(阻塞等 DAG)
          → [诊断分支: 修代码×3 / 修质量×3 / 重试×3] → restest → 终态落盘
T5   主会话 run_load 兜底验终态 + failed 的 suggestion reopen
T6   串行 assess 每个 check_done:
     [忠实度审稿] → prepare 入表 → 判定(双闸门+冗余) → commit
     → realize/open 迭代管道
T7   support_score 汇总 → run_save done → 报告
```

单轮 wall-clock 主要消耗在 T4 的平台 DAG（每因子约 10-20 分钟），认知协议 T2 约 10-15 分钟（cog agent 串行为主）。一轮 1-3 个因子，输出确定性由三类 budget + 兜底机制保证。

### 实证路径样本（近期四轮）

| Run | 路径 | 结果 |
|---|---|---|
| 0821-ml4box | cog OOD/INSUFFICIENT ×2 → 转建议 193 拆解 | 1 pass + 1 fail，d_imb 反向归因锁定 |
| 0821-o3cfz4 | 建议 194 两变体 | 取负版 pass（res_IC 翻正），imb 水平版撞族 fail |
| 0824-v2r2gj | **全链**：CONTRADICTS → STRUCTURE → 3 候选过 transfer → **G4 全归约** → 归约构造式直接验证 | fail（双闸门全灭），实证"regime 分裂是 confounder 残留"+ 避免伪新算子入库 |
| 0824-kr9y34 | **v2 引擎首战**：概念编译+分裂检测+UNTESTABLE 分流全链 | **pass**（res_IC +0.0102→+0.0122）；A4 分裂矛盾旧引擎会判 SUPPORTS 销案 |

**0824-kr9y34 的组件验证明细**（v2 改造 vs 历史基线）：12 假设全 TESTED（UNTESTABLE=0 vs 历史 UNCLEAR 40%）、裁判 0 OOD（vs 23%）、5 案/轮（vs ~10）、CONDITIONAL_SPLIT 命中 A4（spread=0.103，旧引擎平均成 0.0047 会销案）、CONTRADICTS 精确率 3/5=60%（vs 22%，单轮样本）。

---

## 十一、已知粗糙点（诚实清单）

1. **realize 的 icir_delta 对符号翻转实验误导**（详见 7.6）——target 指标在特殊实验里需人工判断
2. **suggestion claim 独占**导致多变体共享建议时归档链不完整（记 suggestion_ref 弱关联绕过）
3. **tradability/stationarity 依赖平台 ic_only 模式**，多数 run 缺这两维（key_weaknesses 常规标注"未评估"）
4. ~~evidence 程序层的列匹配机械，UNCLEAR 率高~~ → v2 已修（概念编译+分裂检测+UNTESTABLE 分流，0824-kr9y34 实战验证）；遗留：单轮样本，需多轮固化统计；盲区登记（UNTESTABLE 清单）尚无独立存储表
5. 假设级 argument_chain 覆盖率低（多数 idea 是散文），忠实度审稿经常跳过——论证链生产（persist_argument_chain）是当前薄弱环节
6. **派生维度空间不生长**：盲区高频需求 → 新 derive 函数这条反哺线仍是手动的（词表回填已闭环，89 列本身的扩充没有）

---

## 总结

这套框架的本质：**用程序化的分诊和预算控制把"研究品味"固化成可重复的流水线，用视图隔离和归约审查保住每个判断的纯度，用迭代管道和 lesson 让任何一轮的产出（正/负）都变成下一轮的输入。**

- 认知协议管"问对问题"
- G4 归约管"不重复发明"
- repair_contract 管"推理不悬空"
- assess 双闸门管"实证说话"
- 迭代管道管"线索不丢"
