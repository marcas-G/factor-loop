# 因子假设方法论（hypothesis-framework）

> 本文件 = **真相**。它是 reviewer / graph-reasoner / hypothesize / assess 四个执行体的共同方法论基底;各 skill/agent 是它的执行投影。
> 凡本文件与单个 skill/agent 的局部描述冲突,以本文件为准(局部描述应回写对齐)。
>
> 一句话:因子假设是对「现象依赖某机制」的**可证伪必然性断言**;产生与验证认知相反,故用对抗式审稿隔离;数据驱动默认 conditional,底线是**赚钱闭环 + 可证伪 trace**。

---

## 0. 认识论:必然性断言 + 对抗式验证

### 0.1 假设是什么(必然性,不是描述)

浅假设给现象贴一个说得通的解释(可替代);深假设断言现象**依赖**某机制——**抽掉它,现象就崩塌**。深浅的分野全在"必然性"。

- **组合机**(旧 brainstorm 范式):预先造好零件库(`PROFIT_SOURCES × DIMENSIONS`)→ pick → 拼装 → 测 IC。零件库里没有的东西 pick 再多也 pick 不出来;产出"恰好相关",不是"必然如此"。
- **生成机**(本框架):从一个**约束耦合矛盾**出发 → 施加约束 → **求约束下的必然解**。解不是被选的,是被**逼出来**的。

必然性只能来自约束的**非平凡耦合**(两约束联合逼出各自都逼不出的结论)。核心动作是**找到约束之间的耦合**,不是堆砌维度——这就是"算子硬拼"为何浅(坐标组合但无机制耦合)。

### 0.2 必然性四级(necessity_grade)

| grade | 含义 | S2 超加性 | S4 唯一性 |
|---|---|---|---|
| **necessary** | 抽掉机制现象必崩(数学封闭) | 真超加性 | 真非平凡唯一(四来源之一) |
| **identification** | 可识别但机制不唯一 | 硬核 | 退化为可识别标量(Roll 式) |
| **conditional** | 弱关联,有可证伪 trace | 有 | 弱/缺 |
| **draft** | 待补(结构残缺) | — | — |

**关键辩证**:
- **必然 ≠ 经典**。顶刊/诺奖/高引 ≠ 必然。ACD(Engle-Russell,Econometrica)是 GARCH→duration 的**类比**,类比是或然推理,挡 necessary 门外。判据独立于案例声誉。
- grade 衡量"必然性强度",不是"研究价值"。或然研究有价值,但不混入必然框架稀释标准。

### 0.3 2026-07 共识:conditional 为默认(质量底线调整)

**纯数据驱动发现(矛盾/反例归纳)几乎都或然**,强求 necessary 会卡死产量(两次实跑 resolve+generalize 皆 bounded)。故:

- **质量底线 = ①赚钱闭环闭合 + 可证伪 trace(falsifiable_trace 必填)**,不是超加性必然。
- **necessary 降为 stretch goal**——靠理论内部张力(演绎)达成,非数据归纳。数据驱动默认 `conditional`。
- **转变**:之前"或然 → bounded 空手";现在"**或然但有闭环 + 可证伪 trace → conditional 入图**"。只有 ①闭环都凑不出 / 无可证伪 trace / 数据不足,才 bounded 或空手。

> IC + 样本外当最终裁判(assess 阶段),不靠 reviewer 的必然性。图的血缘/反例约束防重复。

### 0.4 产生 vs 验证:认知相反 → 对抗式审稿 + session 隔离

产生(找支持)和验证(找反驳)是**认知相反**的动作。同一 context 做两件事会系统性偏向确认(确认偏置经共享上下文泄漏)。

落地:
- **对抗式审稿**:reviewer 职责是**尽力反驳**论证链,不是确认它。必然性是证伪性判据,只有"尽力证伪"才匹配它的本性。
- **session 隔离**:reviewer 只收论证链 artifact(JSON),不看作者推理过程。隔离后面对的是被提交的成品(像独立投稿),被迫独立判断。

---

## 1. 形式化骨架:argument_chain(S1-S4)

每个 DERIVED 层假设必须填 `argument_chain`(reviewer 模式一逐项攻;assess 忠实度审稿对照)。结构:

```
background_axioms[]          Σ 背景公理集(引用图中 axiom code 或 ideas id)
superadditive_coupling{      S2 超加性耦合 ★核心
  A, B, C,
  entailment_proof,          A∧B⊢C 的推导
  superadditivity_proof,     A⊬C 且 B⊬C
  minimality                 C 是 A∧B 的最小非平凡蕴含
}
constraint                   S3 固化约束(A∧B 的可解形式)
uniqueness_proof{            S4 唯一性
  type,                      extremum|contraction|zero_dof|equivalence|minimal_sufficient
  reasoning                  真论证(不是"显然唯一")
}
competing_explanations[]{    S6b 竞争解释(≥2 个,Duhem-Quine 防漏)
  rival, distinguishing_observation, exclusion_test
}
falsifiable_trace            S6a 解→X 的演绎预言(抽掉 X 现象应崩)
```

HYPOTHESIS 层(orthogonal_branch / explore 新角度种子)可只填 `text` + 简化 chain(background_axioms + constraint),grade=`conditional`/`draft`。

### S1 · 背景公理集 Σ

显式陈述接受的背景共识。每条必须是**可被独立攻击的经验命题**,不能是定义(定义不可证伪,不能当公理)。Σ 错了由范式异常检测器兜底(§3.4)。引用图中**已有** axiom code(如 `roll_bounce`)或 ideas id,不引用不存在节点。

### S2 · 超加性耦合(核心动作)★

从约束耦合矛盾找 A、B、C 满足**三条件**:

```
① A ∧ B ⊢ C        联合蕴含
② A ⊬ C 且 B ⊬ C    超加性:任一单独推不出  ← 伪耦合检验最常在此穿帮
③ C 是 A∧B 的最小非平凡蕴含  (非 C=A∧B 平凡重述)
```

**为什么是关系性判据(不做类型清单)**:耦合不能做成 `{矛盾型,夹逼型,缺口型,...}` 清单——那是组合思维复发,每碰新形态就加类型,永远枚举不完。三条件只判定"联合时是否产生超加性蕴含",任何形式的耦合(矛盾/夹逼/缺口/多目标)都是它的投影,自动涵盖。

找不到超加性耦合 = 没有必然性根基 = 产不出深假设,换一个。

### S3 · 固化约束

把 A∧B 写成可解约束。**不预设**形态(conjunctive / multi_objective / domain_conditional)——约束形态是耦合结构的投影,不是事先选的类型。

### S4 · 唯一性证明(五 type ← 四来源)

| 必然性来源 | type | 典范 |
|---|---|---|
| **逻辑必然**(优化目标+约束解出唯一策略) | `extremum`(严格凹/凸→唯一极值)/ `contraction`(压缩映射→唯一不动点) | Kyle 利润严格凹→唯一最优交易量 |
| **对称/守恒必然**(某量守恒或无套利,否则不自洽) | 约束层体现 | Gatheral 无价格操纵→冲击衰减凸非增 |
| **因果必然**(信息存在则必在某可观测量留痕) | `minimal_sufficient`(最小充分量,去任一分量则失效) | OFI 订单流不平衡必然含信息 |
| **结构必然**(统计量符号/形态由底层结构唯一决定) | `equivalence`(可测↔不可测解析等式)/ `zero_dof`(解流形 0 维+Hessian 非奇异) | Roll 负自协方差↔价差 |

**`identification` 是弱类型**(可识别标量,非机制唯一)——用于 equivalence 被反例击穿(如 MA(1) 同构:二阶矩不识别分布)等"S2 硬但 S4 退化"的诚实降级。

**拒绝伪唯一性**:必须给对应 type 的**真论证**(extremum 证严格凹的二阶条件;equivalence 给非平凡 iff 非移项)。"显然唯一"是断言不是论证——reasoning 去掉后结论若仍成立,说明 reasoning 是装饰,S4 没贡献超越 S2 的信息。

### S6 · 竞争解释 + 可证伪痕迹(底线项,conditional 也要)

- **competing_explanations**:≥2 个竞争解释 + 各自区分观测。防 VPIN 式遗漏(VPIN 漏了波动率这个显然竞争解释,毒性预测力被证伪)。列时问:"还有没有显然的替代机制被我漏了?"
- **falsifiable_trace**:解→X 的演绎预言。**抽掉机制 X,现象形态应崩塌**;抽掉后现象还在 = X 不是必然原因,假设假。

---

## 2. 三道质量门槛(下层,承接旧 framework,仍是底线)

> 这三道是**质量底线**,与 §1 的 S1-S4 形式化判据叠加。§0.3 的 conditional 放宽**不放宽这三道**——它们是 conditional 能否入图的硬门槛。

### ① 闭环闭合(第一道,可持续性根基)

零和市场里能持续赚钱的行为,必须有清晰的利润来源——**赚谁的钱、什么性质的钱**。说不清利润来源的手法,签名不会持续,预测力必然衰减。这解释了大量 imbalance/spoof 类因子短期 IC 好看、很快失效——它们没有闭环根基。

**利润来源 L1-L5**(归纳性、非穷尽、不互斥;遇表外单列,别硬塞):

| L | 谁赚 | 赚谁 | 闭环约束(何时断裂) | 500ms |
|---|---|---|---|---|
| **L1 别人的机械反应** | hunter/点火者 | 止损/强平/追涨者 | 机械反应存在 ∧ 收益>推价成本 | ✓ |
| **L2 流动性补偿** | 做市商 | 价差+返佣 | 价差收益>逆向选择损失 | ✓ |
| **L3 信息优势** | 知情者 | 信息滞后者 | 信息优势>获取成本 ∧ 未泄露 | ✓ |
| **L4 速度优势** | 高频 | 慢方 | 速度差存在 | ✗ 失效 |
| **L5 风险溢价** | 持仓者 | 风险补偿 | 承担风险有补偿 | △ 几近为零 |

**闭合判据(硬门槛)**:闭环必须落到 L1-L5 某个利润来源——"**赚谁的什么钱**"必须能回答。停在"XX 方意图 / XX 方代理 / XX 方行为"的,判**闭环未闭合**,拒收。

| 闭合 ✓ | 未闭合 ✗ |
|---|---|
| 赚被迫强平者的钱(L1) | 挂单方意图看多(意图,没说赚谁) |
| 做市商赚价差、防御毒性(L2) | 做市商防御方向(行为,没说赚什么) |
| 知情者赚信息滞后者(L3) | 知情者建仓(行为,信息源头没说) |

**执行型手法**(iceberg/TWAP/被动吸纳)本身不赚钱,服务于更大的 L3 闭环——**必须追溯到背后的利润来源**,否则闭环不全。

### ② 因果链完整(第二道,七节 + 微观 E)

填满七节,缺一即判不完整:

```
① 行动者   谁(赚方)
② 动机     赚谁的什么钱(L1-L5)+ 闭环约束          ← 接 ①门槛
③ 触发     什么条件下他会行动                 ← 含上下文 C(历史/状态量)
④ 行动     他做什么(下单/撤单/移档/…)
⑤ 痕迹 E   t-1→t 可分解的微观事件:具体叙述"这 500ms 里谁对哪档
          做了什么",用分量(add_i/cancel_i/各档 price·size Δ)组合;
          禁用聚合净量(Δsize/Δmid 单独)充当 E——净量掩盖分解
          (净+10 可能是 加15撤5 或 加12撤10,含义不同)   ← 假设对象
⑥ 反推     E ∧ C → 预测对象(方向/分布/状态/路径)
⑦ 失效     闭环约束何时断裂
```

**判据(精度)**:E 要能像"bid0 加15撤5、ask0 加3撤12"这样**具体叙述**——落到分量。只能说"size 变了""mid 动了"这种聚合描述的,判精度不够(那是窗口策略/特征工程,不是 tick 级事件假设)。

> §0.3 放宽后:微观 E **尽力**构造,缺则诚实标注(在 reasoning_summary / argument_chain),不阻断 conditional 入图。但聚合净量**不能**当微观 E 充数。

### ③ 复杂度可控(第三道)

坐标数 n 是过拟合代理:1 原子 / 2-3 复合 / ≥4或跨域 结构。

- n≥2 必须有可复述的闭环+机制逻辑(因果链 ②③),不能算子硬拼。
- DSP/构造量类因子天然 n 偏高,门槛更严。

---

## 3. 假设产生:hypothesize 图驱动

### 3.1 主路径 · hypothesize 图驱动 5 操作

在分层知识图(AXIOM→DERIVED→HYPOTHESIS,EVIDENCE/REFUTATION)上做**结构化扩展**产生假设。新提案 = 图的结构化扩展,不是扫网格枚举;无穷来自推理链延伸。

| 操作 | 触发条件 | 产物 |
|---|---|---|
| **resolve_contradiction** | 未解 CONTRADICTS 边(observe 实测 vs axiom 理论预期) | 解释矛盾的 DERIVED 假设 |
| **generalize_from_refutation** | 3+ REFUTES 指向同一目标(dead_end 聚簇) | 共同失败模式逼出的必要条件 DERIVED |
| **fill_chain_gap** | 某 DERIVED 的 argument_chain 有空节 | 补 axiom / 中间推导 / 竞争解释 |
| **orthogonal_branch** | 某 HYPOTHESIS 有 3+ INSTANTIATES 无 ORTHOGONAL_TO | 正交维度上的子假设(HYPOTHESIS,conditional) |
| **explore_uncovered_angle** | 1-4 无触发点 或 聚簇都在 saturated 角度 | 跳到 unexplored/thin 角度的种子假设(自驱换角度,不靠人喂) |

每个操作由 graph-reasoner-agent 单步推理(S1-S4 + 三道门槛),产出 `new_nodes` + `new_edges` JSON;reviewer 独立对抗审;主会话据 verdict 落盘。三者职责分离(产生/验证/落盘)。

**无 fallback**:触发点耗尽或全角度 saturated 时,图推理产不出新假设,如实返回 `no_hypothesis`(research-loop 据 paused)——不再走 lens 反常归纳兜底。

### 3.3 BOUNDS 否定性边(axiom 证伪)

若推理结论是 **axiom 在此 regime 不完备/被证伪**——A∧B 只否定 axiom 完备性,不单向逼向任何必然机制 C(候选解释全或然);超加性证不出、唯一性证不出、三门槛断在微观 E/闭环——这是**有价值的否定性结论,不丢弃**:

- 产一条 `BOUNDS` 边:`observe_outputs → axioms`,properties 标 `{regime, reason}`
- `graph_mark_contradiction_bounded` → 该矛盾不再悬着被反复 resolve

**区分两种空手**:axiom 证伪(或然非必然)→ 产 BOUNDS(否定性入图);数据不足无法判断 → 真·空手(new_edges 也空),待数据补。

### 3.4 范式异常(哥德尔天花板)

S2/S4 反复修正(K≥3)仍过不了 reviewer,且不是 C 过宽 / type 不可达能解释的:可能撞 Σ 天花板。

- ❌ 不硬解(会在错误公理基上产伪必然性)。
- ✅ 标 paradigm anomaly,交回人,建议「更换背景公理 Σ」。

> 任何固定 Σ 上的机器受不完备定理约束——只产 Σ-可证的必然解,产不出 Σ-真但不可证的解。Kyle 当年引入"线性定价"假设本身(换 Σ),不是在旧 Σ 内求解——这种 paradigm shift 需要人。机器识别"撞顶"并诚实报告。

---

## 4. 假设验证:双轨

因子 = 假设的可测实现。验证**双轨**:经验(因子有没有效)+ 忠实度(实现有没有验证假设)。忠实度不通过 = 因子没验证假设 = fail(即使 IC 高)。

### 4.1 忠实度轨(reviewer 模式二,一票否决)

**IC 高 ≠ 验证假设**。一个因子 IC 高,可能来自假设声称的机制(真验证),也可能来自别的机制(冒充)。不审忠实度,会把"碰巧有效的无关因子"误当"假设验证"。

前提:假设有结构化 argument_chain(用 `hypothesis_get` 读)。散文 hypothesis(旧 brainstorm)→ 跳过本轨,仅经验维度。

审稿维度(对照论证链审 .h 实现):
- **核心机制捕捉**:实现是否实现了 C 声称的机制 / S4 type 对应的结构?
- **机制冒充检验**(关键攻击):预测力来源是否是论证链声称的机制?(假设微观结构,实现却靠宏观动量 → 冒充)
- **competing 排除**:实现是否实现了区分观测(排除竞争解释)?
- **核心组件去除**:抽掉对应 C 机制的核心组件,预测力应崩(真依赖);不崩 = 用了别的机制 = 冒充。

`unfaithful` → **一票否决**,verdict=fail(即使 IC 高)。

### 4.2 经验轨(assess 三维度 + 一票否决)

所有指标来自平台/本地代码聚合的评估数据(**非 LLM 自评**)。

| 维度 | 核心指标 | 判断标准 |
|---|---|---|
| **第一维 预测能力**(秩空间,弃 pearson) | 秩 IC 的 ICIR/t 值;平稳性+差分(ADF) | 均值不降+std 降+ICIR 升;平稳无需差分,非平稳且差分改善则差分 |
| **第二维 稳健性** | IC 标准差;训练-测试衰减;最大回撤+修复期;月度稳定 | 跨时段/regime 平稳;衰减小;回撤<5% |
| **第三维 可交易性**(高频必过) | 换手率;成本后 Sharpe(8bps);正交(\|pearson\|<0.7 ∧ 残差 IC 强度高);变换族预测力 | 低换手;成本后不转负;与库内正交;最强变换指导迭代 |

**一票否决**(任一命中 → fail,不进综合):
1. 样本外秩 IC 符号反转
2. 推进式回测失败(连续多月亏/后期断崖)
3. 成本翻倍夏普转负(16bps)

**数据信任 / 无罪推定**:factor_check 未报错则数据可信。唯一可下调 IC 可信度的依据:**feed IC(screening)与 @1 因果 IC 符号相反或量级背离**(如 feed ICIR>2 但因果 ICIR<0.3),诊断为"对齐不一致"倾向 fail;无此证据不得写"结果可疑/数据不可信"类预设。

---

## 5. 实现工具箱(旧 §5,降为实现层)

因果链 ⑤「痕迹 E」落地用的工具。**不是假设的起点,是被闭环和因果链选中的实现手段**。

### 5.1 可观测边界(诚实先行)

**数据**:`BookSnapshotInfo` 盘口快照,每合约 46 列 = 5档×(price/size/add/cancel)×bid&ask + 6 全局(`open_interest` `total_volume` `turnover` `last_trade_price` `last_trade_size` `mid_price`)。

- **标签 Y**:仅 `SHFE-AG` 主力,horizon `{1,5,10,60,300}`s,Y = 未来 N 秒 mid 收益。
- **快照频率**:上期所 500ms 定频,时间分辨率 = 2Hz。
- **三缺陷**:`last_trade_size` 全 0(用 Δtotal_volume);离线无 Trade feed(方向用 imbalance/加撤流代理);`@1` 语义待确认(跨合约类先标注)。

### 5.2 构造量分层

```
L0 字段 → L1a 原语事件(字段差分) → L1b 构造观测量(统计才可见) → L2 复合(逻辑算子) → L3 结构(跨域)
```

**L1a 原语事件源**:价格(Δmid/Δbest/Δ成交价)、库存(Δsize_i/imbalance/深度结构)、加撤流⭐(add_i/cancel_i/加撤失衡)、成交(Δtotal_volume/Δturnover)、持仓(ΔOI)、时间(dt/频率 regime)。

**L1b 构造观测量**(字段里没有,需统计估计):

| 族 | 构造量 | 可假设的现象 |
|---|---|---|
| 波动率 | RV / GK | 压缩→爆发 |
| 价格冲击 | Kyle λ / Amihud | 敏感度突变=流动性枯竭 |
| 毒性 | VPIN | 毒性积聚 |
| 记忆 | Hurst / OU τ | 动量↔反转切换 |
| 聚类 | Hawkes λ/τ | 激励衰减 |
| 分布 | 偏度/峰度/熵 | 形态切换 |
| 均衡 | 协整残差/基差 | 均值回归 |
| 状态 | regime/拓扑态 | 状态切换 |
| 时频 | 小波尺度能量/谱质心/Kalman 隐含价/CCF lead-lag | 多尺度动量/信息流/价格发现噪声 |

**DSP 筛选**(fs=2Hz、强非平稳;产出须锚回利润来源,锚不住即黑箱):高=CCF lead-lag(L3)/Kalman 状态空间(L3);中=小波多尺度(L5)/coherence(L3)/低通趋势分离(L2/L5);✗=直接 FFT 系数(非平稳无意义)、⚠️=Hilbert 瞬时相位/格兰杰(易过拟合)。

### 5.3 度量 M / 窗口 W / 时钟 / 组合算子

- **度量 M**:幅度/方向/z-score/比率/分位/多档加权/对数失衡/阈值触发/高阶矩熵/密度归一。
- **窗口 W**:即时/滚动{10,50,200}/EWMA/累积净流/频率计数。
- **时钟**(500ms 定频):时间窗≈事件窗(1 快照≈500ms);**真正有区分度的是成交量窗和信息窗**,自动消除密度差异。
- **组合算子 L2**:gate / confirm / contradict / diverge / cohere / lead-lag / rebalance。
- **结构 L3 + 条件 G**:跨合约/跨 horizon/时段切换;G 条件(regime/方向切片,横切各层)。

### 5.4 密度归一(跨切片可比)

500ms 定频下 dt 近恒定,密度差异来自**切片内事件数**(成交 1000 手 vs 0 手),非 dt。归一用密度归一(按切片事件数)或成交量/信息时钟。特殊长 dt 切片(~5%,集合竞价/小节休息)是状态切换事件,单独处理。

---

## 引用关系

本文件被以下执行体引用(改动本文件需同步检查它们):
- `agents/reasoners/reviewer-agent.md` — 模式一(S2/S4 攻击)、模式二(忠实度)
- `agents/reasoners/graph-reasoner-agent.md` — 5 操作的 S1-S4 推理框架 + 三道门槛
- `skills/hypothesize/SKILL.md` — 5 操作编排 + reviewer 派遣
- `skills/assess/SKILL.md` — 双轨验证 + 三维度
