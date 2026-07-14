# 归纳引擎交接方案(新 session 执行手册)

> 本文档自包含。新 session 先 Read 本文档,再按"§5 执行顺序"操作。
> 工作目录:`/home/lgao/work/factor-autoloop`。真实库:`factors.db`(项目根)。

---

## 1. 系统架构与现状

### 1.1 两大引擎并列,共享 factor_db

```
[归纳引擎(本会话新建)]                [演绎引擎(现有 research-loop)]
扫描→模式卡→审计→归档→feed            hypothesis→brainstorm→run-factor→evaluate
   ↓ pattern_feed                         ↑
   └─衔接①─→ hypothesis-generator ─→ idea ┘
                                   因子→模型→残差 ─衔接②回灌─→ 归纳重搜
```

### 1.2 已建部件(都在)

| 层 | 部件 | 文件/表 | 状态 |
|---|---|---|---|
| **因子层覆盖地图** | coverage_map VIEW + coverage_gaps 工具 | `factor_db/schema.sql` + `pipeline-mcp/lib/factor-db.mjs` coverageMap/coverageGaps | ✅ 真实库 90 格 |
| **残差 Miner(IC 空间)** | factor_ic_daily 表 + residual_ic_strength | `factor_db/residual_ic_strength.py` + `factor_ic_daily` 表 | ✅ freq=spec bug 已修(基底按 symbol+horizon) |
| **归纳地基** | pattern_cards / pattern_dims / pattern_coverage | `schema.sql` + `lib` migratePatternCards | ✅ 43 盘口域化词表预填 |
| **归纳扫描** | 6 detector | `factor_db/detect_patterns.py` | ✅ upper_tail/sign_flip/cross_horizon/monotonic/threshold_break/lower_tail |
| **归纳审计** | raw→audited/deprecated | `factor_db/audit_patterns.py` | ✅ n_days→confidence,组合卡 n_samples 不否决 |
| **归纳归档** | audited→archived+priority | `factor_db/promote_patterns.py` | ✅ |
| **衔接①(归纳→演绎)** | pattern_feed / link_pattern_idea 工具 + hypothesis-generator 分支 | `tools/factor-db.mjs` + `.claude/skills/hypothesis-generator/SKILL.md` | ✅ 代码闭,❌ 未触发 |
| **纵向骨架** | 任务生成器 + 一键发动机 | `factor_db/gen_tasks.py` | ✅ 报告层(覆盖空白+变异+feed) |

### 1.3 真实库当前数据(factors.db)

```
factors: 175(68 evaluated + 107 dead_end)
factor_ic_vec_meta: 1880 场景(187 因子)
factor_ic_daily: 142030 行 / 121 因子(46 缓存损坏没填,121 够残差基底)
pattern_cards: 62(25 archived,6 S 结构)/ pattern_coverage 62 格
```

### 1.4 关键约束(必读)

1. **库对齐**:`pipeline-mcp/lib/factor-db.mjs` 的 `CWD = 项目根`(已修,node/Python 共用 `factors.db`)。不要改回 pipeline-mcp。
2. **缓存**:`refresh_factor_ic_vectors.py` 的 `CACHE_DIR = /home/lgao/tmp/factor-vec-cache`,`CACHE_MAX=20`(LRU,超限删最旧)。`/tmp` 会丢,别用。
3. **freq=spec**:`factor_ic_vec_meta.freq` / `factor_ic_daily.freq` 存的是**因子 spec**(每因子独特),不是时间频率。覆盖地图/残差基底**按 symbol+y_horizon,不要按 freq**。
4. **data-lens out 是摘要**:`/home/lgao/work/quant/data-lens-mcp/out/` 的 conditional/crosscontract/memory/dynamics 是 lens 提炼的摘要(signals 是字段名,hurst 是单值),**不是细矩阵**。`ic_matrix.csv` 是唯一细矩阵(46 字段 × 5 horizon IC)。扩 C/T 维要重跑 lens(慢,n_files 大,会超时)。
5. **张力点已清**:全仓库无"张力点/tension-finder",改成"约束耦合矛盾/反常"。hypothesis-generator 用"约束耦合矛盾"。
6. **lens_predictive 默认 n_files=5**(5 天预览),审计 MIN_DAYS=20 配合为 confidence=preview(不否决)。

---

## 2. 缺口1:衔接①实际触发(归纳→演绎)

### 目标
hypothesis-generator 解释 archived 模式卡 → 产 idea → link_pattern_idea 回写(archived→explained)。

### 现状(2026-07-14 触发已验证)
✅ **机制触发已解决**:新 session 跑 `/hypothesis-generator` 链路完整跑通——pattern_feed(拉 bsi sign_flip 模式卡)→ hypothesis-generator(多轮 lens 深挖 + 构造论证链)→ reviewer-agent(对抗审稿)。
❌ **没产 idea**:reviewer 判 fail(achievable=fixable,最高 conditional)。bsi vs OFI 是**或然经验**(被动单预测力>主动单),不是必然约束耦合矛盾。三反驳:① 竞争解释遗漏(做市商库存对冲/公开信息方向挂单,与弱 Σ2 相容)② 后此谬误("必然超过 OFI"是经验伪装演绎)③ IC 口径不一致(bsi Spearman vs OFI 可能 Pearson)。严筛正确挡住或常,persist/link 未执行。

### 步骤
1. 新 session(干净 context,能跑完整 lens+S1-S4+reviewer)
2. 跑 `/hypothesis-generator`(无参数;衔接①分支自动先 `pattern_feed` 拉 archived 模式卡)
3. 当前 feed 队列 top:`bsi_ask_size`(spearman −0.26)/`bsi_bid_size`(+0.26)的 sign_flip——bid/ask 符号耦合,待解释机制
4. hypothesis-generator:深挖 bsi 机制(lens_orderflow/lens_condition)→ 构造约束耦合矛盾 → S1-S4 → reviewer → `persist_argument_chain` 产 idea → `link_pattern_idea {pattern_card_id, idea_id}` 回写

### 验证
```bash
python -c "
import sqlite3
c=sqlite3.connect('factors.db')
print('pattern_cards 状态:', c.execute('SELECT status,COUNT(*) FROM pattern_cards GROUP BY status').fetchall())
print('explained:', c.execute(\"SELECT COUNT(*) FROM pattern_cards WHERE status='explained'\").fetchone()[0])
print('ideas 带论证链:', c.execute('SELECT COUNT(*) FROM ideas WHERE argument_chain IS NOT NULL').fetchone()[0])
"
```
期望:出现 `explained` 状态(idea_id 非空),ideas 新增带 argument_chain。

### 注意
- 衔接①独立于 factor_ic_daily(不依赖残差数据)。
- 如果 hypothesis-generator 没自动 link_pattern_idea,手动补:`link_pattern_idea {pattern_card_id, idea_id}`。

### 产 idea 的真瓶颈(触发后暴露)
机制通了,但 detector 产的反常过不了 reviewer。**归纳 detector 从 ic_matrix 产的反常(upper_tail/sign_flip),本质是"预测力强/符号耦合"的统计发现,多为或然经验**,难构造"理论 vs 数据矛盾"的必然反常。reviewer 要必然约束耦合(公理性:经验 vs 理论不相容),IC 型反常是解释性(没形式化成矛盾)。
→ **要产 idea,detector 需升级到"理论违反型"反常**:
  - 收益自相关 vs Roll MA(1) 签名(`pipeline-py/observe/observe_autocorrelation.py` 已有)
  - 冲击衰减凸性 vs Gatheral 无操纵(需 lens_orderflow 的 impact_curve)
  - Hurst vs 理论预期(`out/memory.json` 已有,如 ofi H=0.49 vs 收益 H=0.52 的矛盾)
  这些是"公理性反常"(经验违反理论),能过 reviewer。ic_matrix 的 upper_tail/sign_flip 是"解释性反常",过不了。
→ **新方向**:加"理论违反型 detector"(扫理论预期 vs 实测矛盾),产公理性反常模式卡(S 可加 `residual_anomaly` 或新结构),再触发衔接①。这是缺口1从"触发"转向"产必然反常"的关键。

---

## 3. 缺口2:衔接②残差重搜 + 回灌(演绎→归纳)

### 目标
因子→模型 ŷ→残差 ϵ=y−ŷ→归纳在 ϵ 上重搜(发现库未解释的结构)。蓝图"源源不断第一源动力"。

### 现状
- factor_ic_daily 数据 ✅(14.2 万行/121 因子)
- residual_ic_strength ✅(IC 残差,因子级新颖性,evaluate 用)— **这是 IC 空间残差,不是 Y 空间**
- ❌ Y 空间残差回灌:没有"因子→模型→收益残差"管线,没有残差 detector

### 要做(4 步)

**a. 因子→模型 ŷ 管线**(新文件 `factor_db/residual_pipeline.py`)
- 取库 evaluated 因子的日级值(从 dailyX 或 factor_ic_daily 的 IC?——IC 是预测力不是值。要因子**原始值**矩阵,但系统没存因子值,只存 IC)。
- 简化方案:用 factor_ic_daily 的 IC 序列作"预测力代理",组合成"库预测力模型"。或下载因子 dailyX 算值矩阵(重)。
- 最小可行:ICIR 加权组合库因子的 IC → "库 IC 模型" → 残差 IC = target IC − 库模型预测的 IC。这其实是 residual_ic_strength 的延伸(从单因子新颖性到"残差 IC 序列")。
- **诚实**:真正的 Y 空间残差(收益−模型预测)需要因子原始值矩阵,系统没存。要么下载 dailyX 重算(重),要么用 IC 空间近似(已有 residual_ic_strength)。建议先做 IC 空间残差的"重搜"版(residual_ic_strength 产出的残差 IC 序列,作为新 Y 喂 detector)。

**b. 残差 detector**(改 `detect_patterns.py`)
- 新 detector `detect_residual_anomaly`:扫"特征 vs 残差 IC"的 IC(而非 vs 原始收益)。产 S=residual_anomaly 模式卡。
- 数据源:residual_pipeline 产的残差 IC 序列(每因子每天的残差)。

**c. 回灌归纳**
- 残差 IC 序列作为归纳新 Y → detector 扫 → 产 residual_anomaly 模式卡 → 衔接① → 新假设。
- 模型更新(新因子入模型)→ 重算残差 → 重新扫(残差转移,源动力)。

**d. while 触发**(和缺口3 一起)
- 因子入模型后自动触发残差重算 + 重扫。

### 验证
- `pattern_cards` 出现 `s_structure='residual_anomaly'` 模式卡。
- 残差 IC 序列 ≠ 原始 IC(模型解释的部分被减掉)。

### 代价
- IC 空间近似:中(改 residual_pipeline + detector)。
- Y 空间完整:重(要因子原始值矩阵,下载 dailyX)。

---

## 4. 缺口3:归纳纵向(变异+定向+while 自转)

### 目标
归纳引擎自己转 + 搜索树扩展,不靠人手动跑。

### 现状
- 任务生成器 `gen_tasks.py` ✅(报告覆盖空白 + 变异候选 + feed)
- 一键发动机(Bash 串 detect→audit→promote→gen_tasks)✅
- ❌ 变异产新卡、❌ detector 定向、❌ while 自转

### 要做(3 步)

**a. 变异引擎**(新文件 `factor_db/mutate_patterns.py`)
- archived 模式卡 → 邻域变体(换 horizon / 换 S 结构 / 换同族 F / 加 C 条件)
- 变体作为新 raw 模式卡入库(`mutated_from` 指向父),status=raw
- 变体验证:audit 审(变体要有 strength——但变体如"换 horizon"的 IC 在 ic_matrix 有;"加 C 条件"需新数据)
- **约束**:变体在 ic_matrix 内(换 F/H/S)的,detect 全扫可能已覆盖(幂等跳过)。真正新变体(换 T/C/Y)需新数据。变异引擎先做"记录变体关系 + 产可扫变体",不指望全产新。

**b. 定向 detector**(改 `detect_patterns.py`)
- 现在所有 detector 全扫 ic_matrix(一次产所有 F×H×S)。
- 改:detect 接受任务参数(指定 F×S×H),只扫指定。让任务生成器/变异的"扫空白"任务能定向执行。
- 简化:detect_<structure>(ic_csv, task_filter) — task_filter 指定要扫的 F/S/H。

**c. while 自转**(新文件 `factor_db/run_induction_loop.py`)
```python
while True:
    tasks = gen_tasks()           # 覆盖空白 + 变异 + feed
    if 无新任务: break
    raw = detect(tasks)           # 定向扫
    audit(raw)
    promote(audived→archived)
    mutate(archived→新 raw 变体)  # 回队列
```
- 停止条件:无新 archived(变体都 deprecated/已存在)。

### 验证
- 变异产新 raw 卡(mutated_from 非空)。
- while 循环跑多轮(不止一键)。
- pattern_coverage 格数增长(变体扩展)。

### 代价
中(3 文件:mutate_patterns 新 + detect 定向 + run_loop while)。

---

## 5. 缺口4:横向剩余(扩 S + C/T 维)

### 目标
模式空间覆盖饱满:S 12/12,C/T 维有变化。

### 现状
S 已扫 6/12(upper_tail/sign_flip/cross_horizon/monotonic/threshold_break/lower_tail)。C/T/Y/R 维常数(level/null/raw_return/self_history)。

### 要做

**a. 从 ic_matrix 能加的 S**(改 `detect_patterns.py`,轻)
- `u_shape`:|IC| 跨 horizon 先降后升
- `inv_u_shape`:先升后降
- (这两个和 cross_horizon_nonmonotonic 类似,加专门识别)

**b. 需新数据源的 S**(重,需 data-lens 细矩阵)
- `cond_amplify`:条件增强(同特征在条件 C 下 IC 更强)→ 需 lens_condition 条件 IC 矩阵
- `post_event_path`:事件后路径 → 需 lens_event_clustering
- `regime_transition`:状态转移 → 需 lens_state_topology
- `residual_anomaly`:残差异常 → 衔接②(缺口2)
- 这些 lens 的 out 是摘要,要细矩阵得重跑 lens(慢)

**c. C/T 维**(重)
- C(条件):pattern_cards.c_condition 现 null,要填(vol_regime/session/...)。需 lens_condition 条件 IC。
- T(变换):现 level,要 delta/quantile/...。需算变换后 IC(delta IC 要重算)。
- 数据源瓶颈:data-lens out 摘要不够,重跑 lens 慢。

### 验证
- S 12/12(pattern_coverage 12 种 s_structure)。
- C/T 维有非 null/level 值。

### 代价
- u_shape/inv_u_shape:轻(加 detector)。
- cond_amplify/post_event_path/regime_transition + C/T 维:重(需 data-lens 细矩阵,重跑 lens 慢)。

---

## 6. 新 session 执行顺序

按"易→难 + 依赖"排:

1. **衔接①产 idea**(缺口1)— 触发已验证(机制通,2026-07-14),但反常或然过不了 reviewer。下一步:加"理论违反型 detector"(Roll 自相关/Gatheral 冲击/Hurst 矛盾),产公理性反常模式卡,再触发 `/hypothesis-generator`。
2. **横向 u_shape/inv_u_shape**(缺口4a)— 轻加 2 detector,S 6→8。从 ic_matrix,不需新数据。
3. **纵向变异+定向+while**(缺口3)— 中,3 文件。让引擎自转。
4. **衔接②回灌**(缺口2)— 中(IC 近似)/重(Y 空间)。残差重搜。最有价值(源动力)。
5. **横向剩余 + C/T 维**(缺口4b/c)— 重,需 data-lens 细矩阵。最后做。

### 触发新 session 的 prompt(复制粘贴)

```
Read /home/lgao/work/factor-autoloop/INDUCTION_HANDOFF.md。
按 §6 顺序执行缺口1(衔接①触发):跑 /hypothesis-generator,
它会先 pattern_feed 拉 archived 模式卡(bsi sign_flip),
解释机制→S1-S4→reviewer→persist_argument_chain 产 idea→link_pattern_idea 回写。
完成后用 §2 的验证命令确认 explained 状态。
```

(后续缺口换 prompt 里的"缺口1"为"缺口3"等,参照对应章节)

---

## 7. 关键文件清单

```
factor_db/
  schema.sql                    # 表 DDL(pattern_cards/dims/coverage/factor_ic_daily/coverage_map VIEW)
  refresh_factor_ic_vectors.py  # IC 向量+日级IC 刷新(CACHE_DIR=/home/lgao/tmp,LRU 20)
  residual_ic_strength.py       # 残差 IC 强度(基底按 symbol+horizon,已修 freq bug)
  detect_patterns.py            # 6 detector(upper_tail/sign_flip/cross_horizon/monotonic/threshold_break/lower_tail)
  audit_patterns.py             # 审计(raw→audited/deprecated,confidence)
  promote_patterns.py           # promote(audived→archived+priority)+ feed_queue
  gen_tasks.py                  # 任务生成器(覆盖空白+变异+feed)
  db.py                         # Python DB 访问层(DB_PATH=项目根/factors.db)
pipeline-mcp/lib/factor-db.mjs  # node DB 客户端(CWD=项目根,18 MCP 工具)
pipeline-mcp/mcp/tools/factor-db.mjs  # MCP 工具 schema/handler
.claude/skills/
  hypothesis-generator/SKILL.md  # 衔接①分支(优先 pattern_feed)
  research-loop/SKILL.md         # 演绎编排
  evaluate/SKILL.md              # 因子评估(含 residual_ic_strength 正交)
.claude/agents/reviewer-agent.md  # 对抗审稿
```

### MCP 工具(quant-mcp,18 个)
- 因子循环:persist_factor/check_factor/submit_factor/run_*/open_iteration/realize_iteration/reopen_iteration/list_open_iterations
- 查询:factor_list/detail/search/semantic_search/ic_correlate/ic_refresh
- 覆盖(因子层):coverage_map/coverage_gaps
- 残差:residual_ic_strength
- 模式卡(衔接①):pattern_feed/link_pattern_idea
```
