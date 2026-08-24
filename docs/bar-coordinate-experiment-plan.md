# Bar 坐标转换实验计划

> 状态：实验设计 v1，2026-08-19  
> 输入思想来源：AFML 2.3 Standard Bars / Information-Driven Bars  
> 目标：把 bar construction 的“采样坐标转换”引入当前 AG 高频盘口因子循环，而不是简单新增一组聚合公式。

## 1. 本质判断

Bar 的关键不是 OHLC 聚合，而是**选择用什么变量定义一段市场过程的结束**。一个 bar 是一个 stopping rule，也是一次坐标转换：

| 原文方法 | 结束条件 | 隐含坐标 | 解决的问题 |
|---|---|---|---|
| Time bar | 固定时间 | 物理时钟 | 便于管理，但高活动期欠采样、低活动期过采样 |
| Tick bar | 固定成交笔数 | 事件次数 | 对齐信息到达速度，但受订单拆分影响 |
| Volume bar | 固定成交量 | 交易数量 | 消除 tick fragmentation，更接近等交易强度单元 |
| Dollar bar | 固定成交额 | 资金/名义金额 | 价格漂移、股本或合约价值变化下更稳定 |
| Imbalance bar | 净买入/卖出失衡超过预期 | 信息惊讶度 | 对齐知情交易和不平衡流 |
| Runs bar | 单边毛流量超过预期 | 执行切片/sweeping | 捕捉不因买卖相抵而消失的单边坚持 |

这也是 random time change / subordination 思想：价格在物理时间上不均匀，但可以用一个 directing process 重新参数化，让每个观测单元的信息量近似可比。坐标转换的副产品同样重要：两个坐标系之间的局部换算率，例如 `dVolume/dBookEvent`、`dNotional/dBookEvent`、`dBookEvent/dt`，本身就是市场 regime 的可观测量。

当前系统已经有一个天然的非时间坐标：`W=500` 的 ring window。它按盘口 snapshot 事件数计数，不是按物理时间。因此实验重点不是引入“事件化”，而是把现有单一 book-event 坐标扩展为：

1. **交易量坐标**：累计成交量达到阈值；
2. **资金坐标**：累计成交额或成交额代理达到阈值；
3. **信息惊讶坐标**：净 signed flow 超过动态预期；
4. **单边 run 坐标**：买侧或卖侧毛流量超过动态预期；
5. **持仓兴趣坐标**：累计 `|ΔOI|` 达到阈值，这是期货场景的自然扩展。

## 2. 与现有场景的结合方式

当前研究链路的特点：

- 数据是 AG 主力与 `@1` 的高频盘口快照，约 117 天，每天约 3.5 万到 4 万行；
- `.xy` 缓存有 bid/ask 五档价格与量、`RawOI`、`RawTotalVolume`，以及 `@1/5/10/60/300` 秒未来收益；
- 现有因子以 `onEndBook()` 的 snapshot 输出为主，很多状态环窗按 book event 计数；
- 平台因子回调中有精确 `Feed::Trade`：`quantity()`、`side()`、`lastTradePrice()`、`openInterest()`、`turnover()`。

这意味着系统已经是混合坐标系：X 的 ring 状态在 book-event 轴上，Y 仍是 `@1/@5/...` 物理时间收益。PnL 最终在物理时间实现，Y 不能贸然替换；但两个坐标轴之间的换算率必须显式建模。当前 `W=500` 把一次 500 手成交的更新和一次 1 手成交的更新都视为同样一步，AFML 对 time bar 的批评在这里只是下移到了事件钟层面。

所以 bar 思想应该落在四层，而不是只替换数据粒度：

### 2.1 作为诊断采样器

离线把同一段行情重放到不同坐标上，比较 statistical properties：

- 每日 bar 数是否稳定；
- bar duration 是否消除开盘/午间/夜盘的活动差；
- bar return 的 lag-1 自相关、峰度、方差是否改善；
- 不同 session / activity regime 的方差是否更接近。

这一层回答“坐标是否真的更同质”，不直接追求 IC。

### 2.2 作为因子内部时钟

保留平台输出节奏：`calculateX()` 仍在每个 book cycle 输出；因子内部维护 bar 状态。到 bar close 时更新状态，bar 内输出当前进度、上一 bar 特征或 forward-fill 值。

这能把现有强因子改造成：

```text
原：book-event 窗口内 rank / episode age
新：volume / notional / imbalance / run / OI 坐标下的 rank / episode age / progress
```

尤其适合迭代 `ImbAnchoredPhaseGate` 一类因子：它的信息本来就在“事件重置后的相位”。现在相位重置由 `d_imb` 分位数触发，可以替换或增强为成交量、资金、signed imbalance、gross run、`|ΔOI|` 触发。

### 2.3 作为特征语义

bar close 时输出四类因果可见的状态量：

1. **触发强度**：`actual_accum / expected_threshold`；
2. **bar duration**：达到阈值用了多久；
3. **bar phase**：bar 刚结束、bar 内进度、距上一 close 的时间；
4. **bar 内结构**：净失衡、单边毛流量、`ΔOI`、开始/结束盘口状态、价格位移。

这些不是普通平滑，而是把“市场已经走到过程的哪一步”变成可学习坐标。

### 2.4 作为坐标 Jacobian

不做 bar 聚合也能利用 bar 思想：直接输出不同时钟之间的换算率。

- `dVolume / dBookEvent`：每单位事件承载多少交易；
- `dNotional / dBookEvent`：每单位事件承载多少资金；
- `dBookEvent / dt`：事件推进速度；
- `rank(dVolume/dBookEvent) - rank(dBookEvent/dt)`：信息量推进快、事件数推进慢的错位状态。

这组量不看盘口内容，只看坐标系尺度，是“视角转换”最纯的检验。

## 3. 可检验假设

### H1 活动坐标假设

成交量、成交额、OI 能量坐标比物理时间和 book-event 坐标更能消除市场活动强度差异。  
可证伪表现：bar return 的 session 方差 CV、lag-1 自相关、峰度下降；每日 bar 数 / bar duration 更稳定。

### H2 信息惊讶假设

净 signed flow 超过预期的时刻比固定 volume bar close 更接近知情交易到达。  
可证伪表现：在匹配当前 imbalance、activity、OI energy 后，imbalance bar 事件期的条件 IC 高于普通 volume bar。

### H3 单边 run 假设

大资金常拆单、sweep、iceberg。净失衡会因两侧对冲而消失，但单边毛流量不会。  
可证伪表现：gross run bar 对 `@5/10/60` 秒收益的条件 IC 或 ICIR 衰减优于 net imbalance bar。

### H4 持仓兴趣坐标假设

期货中 OI 变化携带开仓/平仓信息。`Σ|ΔOI|` 达到阈值时，同一盘口状态的含义可能与低持仓变化时不同。  
可证伪表现：OI-energy bar phase 能调制现有 imbalance / depth entropy 的条件 IC，且优于同参数 OI ring。

### H5 相位迁移假设

现有 `ImbAnchoredPhaseGate` 的有效信息在“事件后的耗散相位”。把重置事件从 `d_imb` 极值换成 activity / signed imbalance / run / OI 阈值，应能改善短端与持续性。  
可证伪表现：`@1/5/10` 秒 daily ICIR 提升，且 `@60` 秒不快速衰减。

### H6 资金坐标假设

资金或成交额坐标比成交量坐标更稳定。离线缓存没有精确 turnover，只能先用 `Δvolume × mid` 做成交额代理；平台阶段用 `turnover()` 或 `quantity × lastTradePrice()` 精确复核。

## 4. 实验设计

### Phase 0 之前的预注册协议

**样本与切分**

- Raw cache 共 117 个交易日：`20240102` ~ `20240628`。
- 开发集为前 81 个交易日：`20240102` ~ `20240508`。
- 留出集为后 36 个交易日：`20240509` ~ `20240628`。
- bar 族、目标 bars/day、EWMA half-life、触发倍数、主 horizon 只能在开发集选择。
- 留出集只做最终复核；若基于留出集返工，第二轮必须单独标记，不能与预注册结果合并。

**因果与清洗规则**

- 所有事件先按 `receive_time` 排序，再按交易日分组。
- `RawTotalVolume` / `RawOI` 只做日内一阶差分；每天第一行差分为 0。
- 负成交量差分、成交量下降、OI 跨日重置和异常跳变清零，不用未来值回填。
- 同一 `receive_time` 的多条记录保持文件原顺序。
- 动态阈值和 EWMA 只能由当前时点之前已经完成的 bar 估计。
- bar 累计器在交易日边界重置；平台因子从当日冷启动开始。
- notional proxy 统一定义为 `PriceMid × max(ΔRawTotalVolume, 0)`。当前 raw cache 无合约乘数，因此不能称为严格 dollar / legal notional；拿到乘数后只做单位缩放。

### Phase 0：离线 bar lab

**数据**  

- 117 天 AG 主力与 `@1`，日期 `20240102` ~ `20240628`；
- 以主力为主，`@1` 做符号一致性与因果对齐检查；
- 分布诊断先在开发集完成；留出集只套用开发集选出的唯一配置；
- 阈值只用当日之前数据滚动估计。

**离线可用代理**

```text
d_volume = RawTotalVolume 的日内一阶差分，负值与异常跳变清零
b_t      = sign(Δmid)，Δmid=0 时延续上一方向
signed_volume = b_t * d_volume
notional_proxy = d_volume * mid
d_oi     = RawOI 的日内一阶差分，跨日重置并清洗极端值
```

注意：离线只有 500ms 快照累计量，没有逐笔 trade side。离线结论只能叫 proxy bar；精确 tick / volume / dollar imbalance bar 必须在平台 `receive(const Feed::Trade&)` 中复核。

**基础 bar 族**

1. `T30/T300/T1800`：30 秒、5 分钟、30 分钟 time bar 作为物理时钟基线；
2. `B1000/B5000`：固定 book snapshot 数，作为现有 `W` 坐标基线；
3. `Vq20/Vq50/Vq100/Vq200`：每日目标 20/50/100/200 根 volume bar，阈值只用历史日校准；
4. `NPq20/NPq50/NPq100`：notional proxy bar；
5. `OIQ20/OIQ50/OIQ100`：累计 `|d_oi|` bar；
6. `VIB`：volume imbalance bar，`Σ b_t d_volume` 超过 EWMA 预期；
7. `NPIMB`：notional proxy imbalance bar；
8. `VRB`：volume run bar，`max(Σ buy_volume, Σ sell_volume)` 超过单侧 EWMA 预期；
9. `INTENT_RB`：用现有 large add / cancel proxy 构造意图流 run bar，仅作探索，不进入首批因子。

**诊断输出**

每族 bar 输出：

- bars/day：median、IQR、day-level CV、训练/测试漂移；
- duration：session 分布、active/quiet regime 分布；
- return：mean、std、lag-1 autocorrelation、kurtosis、Jarque-Bera；
- variance homogeneity：session return 方差 CV；
- threshold stability：动态阈值和实际触发量的比值分布；
- auction / reset outlier：首尾 15 分钟与日内主体的对比。
- clock Jacobian：`dVolume/dBookEvent`、`dNotional/dBookEvent`、`dBookEvent/dt` 的分 session 分布、EWMA 稳定性与极端分位持续性。

**通过门槛**

- median bars/day 不低于 20；
- 95% bar duration 小于 30 分钟；
- volume / notional / OI 坐标在 day-level bars/day CV 或 session variance CV 上，比 time bar 和 book bar 至少改善 20%；
- 不允许用当日未来分位数校准阈值。

### Phase 1：条件信息实验

在 Phase 0 的 bar close 样本上评估：

```text
bar return
net signed volume
gross buy volume / gross sell volume
net / gross imbalance ratio
duration rank
threshold surprise
start/end top-book imbalance
start/end deep-book imbalance
d_oi
bar age
```

目标为 `@1/@5/@10/@60/@300` 秒 AG 主力收益。

**评估方式**

1. 只在 bar close timestamp 上算 event-close IC，避免 forward-fill 后的重叠样本夸大显著性；
2. 再评估 dense forward-fill IC，因为平台因子输出是每个 book cycle；
3. 按现有 daily IC / ICIR / hit rate 口径聚合；
4. 每个假设做 matched conditional IC：
   - 匹配时间 session、当前 `imb`、`d_imb`、activity、`|d_oi|`；
   - 比较不同 bar 坐标在同一状态桶内的条件 IC；
5. 主力与 `@1` 必须报告同号率，不能只报主力最佳 horizon。

**候选排名规则**

先看坐标有效性与条件 IC，再看绝对 ICIR。一个候选只有在满足：

- 后 30% 时间样本不翻号；
- `@1` 主 horizon 不系统性反号；
- event-close 与 dense 两个口径不矛盾；
- 相对现有 carrier 有明确增益；

才进入因子实现。

**严格坐标对照**

在进入新特征之前，先做一组“公式不变、只换时钟”的实验。除推进条件和输出采样节奏外，基线的 gain、rank、gate、冷启动规则全部不变：

| 基线 | 当前 ICIR | 坐标变换 |
|---|---:|---|
| `ImbAnchoredPhaseGate_W500_K0p98_Tf15` | 4.78 | ring 只在 Phase 0 主时钟阈值到达时推进 |
| `DepthEntropyResidualEntry_W500L1E4` | 5.90 | ring 只在 Phase 0 主时钟阈值到达时推进 |
| `DepthEntropyBucketEntryAdd_W500E4A2` | 9.25 | ring 只在 Phase 0 主时钟阈值到达时推进 |
| `LogBookImbalanceRaw` | 5.30 | 公式不变，只在 bar 边界刷新输出，非边界沿用上一值 |

每个基线只做一个主时钟版本，不做参数搜索；与基线使用同一区间、同一 Y 列、同一平台流程。这样能隔离坐标变换本身的贡献，而不是把新 bar 特征和公式改动混在一起。

### Phase 2：平台因子消融

第一批控制在 8 到 12 个因子，不放开参数网格。

**共同实现原则**

- `receive(const Feed::Trade&)` 中累计精确 trade side、quantity、lastTradePrice、turnover、OI；
- `onEndBook()` 只维护 bar 状态和输出，不读取 `feed().trade()` 做价格信号；
- EWMA 只由已完成的历史 bar 估计；
- 日/session 边界重置；
- dense 输出使用当前进度或上一 bar close 值，避免未来聚合；
- zero_rate 必须满足平台检查，必要时输出 progress 而不是稀疏事件值。

**最小消融矩阵**

| carrier | 现有坐标 | volume 坐标 | notional 坐标 | imbalance 坐标 | run 坐标 | OI 坐标 |
|---|---|---|---|---|---|---|
| top-book imbalance | `W500 rank` | bar start/end diff | bar start/end diff | close surprise | close run ratio | bar dOI gate |
| anchored phase | `d_imb` reset | volume threshold reset | notional reset | signed imbalance reset | gross run reset | `Σ|dOI|` reset |
| depth entropy | `W500 rank` | volume phase gate | notional phase gate | imbalance phase gate | run phase gate | OI phase gate |
| OI energy | OI event | volume bar dOI | notional bar dOI | signed dOI | gross dOI | OI progress |

优先从已经表现出信息的 carrier 开始：

1. `ImbAnchoredPhaseGate`：把 phase reset 分别替换为 volume / notional / signed imbalance / gross run / OI 阈值；
2. `DepthEntropyResidualEntry`：把 residual entry 放到 bar phase 坐标下；
3. `ImbalanceBase`：输出 bar 内净失衡与 gross run 比；
4. OI 能量族：只在 volume / notional bar 内保留 `ΔOI`，减少低活动期噪声。

**参数**

每族只保留两个档：

- 目标 bars/day：50、100；
- EWMA half-life：200、500；
- imbalance / run 触发倍数：1.0、1.5。

如果第一批没有明确赢家，不继续扩参数，先沉淀 operator lesson。

### Phase 3：平台复核与知识入库

对 Phase 2 赢家执行完整链路：

1. `platform_submit_factor`；
2. `platform_check_factor`，并确认 dense 输出、daily IC、horizon 衰减；
3. `platform_restest_factor`，记录 `R2_X`、`res_IC`；
4. `factor_ic_refresh`，进入本地行为空间；
5. 与现有强因子做 IC behavior correlation 和 residual IC strength；
6. 通过者注册 operator，失败者写 lesson。

建议注册的抽象 operator：

- `ActivityClockResampler`：值流 / 事件流 -> activity bar 状态；
- `InformationThresholdReset`：值流 -> 动态失衡阈值重置相位；
- `GrossRunClock`：事件方向流 -> 单边毛流量时钟；
- `BarProgressCoordinate`：值流 -> 当前 bar 进度 / 相位；
- `PositioningClock`：OI 变化流 -> 期货持仓兴趣时钟。

这些 operator 的核心不是 bar 名称，而是“输入流、累积测度、期望估计、stopping rule、bar close 特征”的 contract。

### Phase 4：坐标 Jacobian 与评估度量衡

**Jacobian 因子组**

只测时钟换算率，不读盘口方向：

1. `volume_per_event_rank`；
2. `notional_per_event_rank`；
3. `event_speed_rank`；
4. `activity_event_mismatch = rank(dVolume/dEvent) - rank(dEvent/dt)`；
5. `oi_per_volume_rank`，用于区分开平仓兴趣和纯交易活跃度。

这组因子如果有效，说明采样坐标失真本身携带状态信息；如果无效，也仍然能校准 Phase 0 的坐标选择。

**评估度量衡实验**

不改变因子，只改变日 IC 的样本权重或重采样口径：

1. 原始：每个 book snapshot weight=1；
2. volume weighting：按 `dVolume` 加权；
3. notional-proxy weighting：按 `dNotional` 加权；
4. bar-close sampling：只在 bar close timestamp 进入日 IC；
5. 时钟 binning：把同一物理日切成等 volume / 等资金 / 等 OI 能量单元，再聚合。

比较同一因子的 daily IC 方差、ICIR、horizon 排序和跨日排序稳定性。若某类时钟加权让库内因子排序系统性更稳，可作为后续 `weight` 列与评估口径的设计依据；但这属于诊断，不直接替代最终 PnL。

## 5. 判定门槛

### G1 坐标有效性

至少一个活动坐标满足：

- day-level bars/day CV 比时间 bar 下降至少 20%，或
- session return variance CV 下降至少 20%，或
- lag-1 autocorrelation / kurtosis 显著下降。

如果统计性质没有改善，bar 方向停止，不进入 IC 调参。

### G2 条件预测增益

候选坐标在主力主 horizon 满足：

- event-close daily ICIR 相对 carrier 提升 `>= 30%`，或条件 IC 提升 `>= 0.02`；
- 后 30% 样本同号；
- `@1` 不出现系统性反号；
- h60 衰减不明显差于 carrier。

### G3 平台质量

沿用当前评估闸门：

- `|rank_ic| >= 0.01`；
- `|daily ICIR| >= 0.3`；
- zero_rate 不触发输出缺失；
- `R2_X < 0.8`；
- `R2_X <= 0.8` 或本地 residual IC strength 明确提升；
- 训练/测试、变换族、可交易性缺失时在 assess 中显式记录，不假装通过。

### G4 跨场景稳定性

同一机制要求：

- AG 主力与 `@1` 不反号，或反号能用跨月价差机制解释并单独建模；
- 若扩展 AU/CU，不能只挑最好品种；
- 换月 / session 边界无阈值继承泄漏。

## 6. 交付物

1. `core/tools/bar_lab.py` 或等价实验脚本：
   - 加载 raw probes；
   - 构造 time / book / volume / notional proxy / OI / imbalance / run bars；
   - 输出 statistical diagnostics 和 bar close 特征；
2. `docs/bar-lab-report.md`：
   - 各坐标统计性质；
   - 条件 IC 表；
   - 各核心假设的初步裁决；
3. 8-12 个平台因子与消融记录；
4. 通过者的 operator contract、IC 向量、restest 结果和 lesson；
5. 最终结论：bar 坐标是作为状态时钟、特征语义，还是仅作为诊断工具进入因子库。

## 7. 风险与防偏差

- **离线 side 是代理**：`sign(Δmid)` 不等于逐笔主动买卖方向；离线 VIB/VRB 只做筛选，平台精确 trade side 必须复核。
- **notional proxy 不是 dollar bar**：`Δvolume × mid` 只能叫 notional proxy；精确 dollar/notional bar 依赖 `turnover()` 或 `lastTradePrice × quantity`。
- **重叠样本**：bar close 后 forward-fill 会造成 overlapping returns；event-close 与 dense 两个口径必须分开。
- **稀疏输出**：只在 bar close 输出容易触发 zero gate；dense 版本应输出 progress、phase 或上一 bar close 状态。
- **动态阈值泄漏**：EWMA 阈值只允许由过去完成 bar 估计；日初冷启动单独处理。
- **多重测试**：先预注册 bar 族和两个参数档；诊断阶段不做赢家选择；最终只带少数候选进平台。
- **活动量与知情交易混杂**：volume bar 变好可能只代表活动状态更同质，必须用 matched conditional IC 区分 activity coordinate 与 information coordinate。
- **OI 重置/跳变**：跨日重置、换月和异常 `ΔOI` 必须清洗，不能跨 session 继承。

## 8. 建议执行顺序

1. 第一天：离线 bar lab，先产出统计诊断和 clock Jacobian 画像，不看预测赢家；
2. 第二天：bar close 特征 + matched conditional IC，筛出不超过三个坐标；
3. 第三天：先跑“公式不变、只换时钟”的严格对照；
4. 第四天：实现 8-12 个平台因子，跑 dense IC 与 `@1` 对齐；
5. 第五天：restest、本地行为冗余、operator contract、评估度量衡实验；
6. 第六天：沉淀报告，决定是否把 bar clock 纳入 research-loop 的常规 operator 池。

全局退出条件：

- 若 volume / notional / OI 坐标在统计性质上与 book-event 坐标几乎等价，且 Jacobian 因子也无信息，则结论为“AG 的 book-event 钟已是充分 subordinator”，角度关闭并写 lesson；
- 若任一坐标在统计性质、严格对照、Jacobian 或评估度量衡中产生稳健增量，则 `sampling_clock` 角度和对应 operator 入库。

## 9. 首轮 research-loop 执行记录（2026-08-19）

Run：`2026-08-19-8sck1l`，状态 `done`。

认知协议从 `ImbAnchoredPhaseGate_W500_K0p98_Tf15` 出发，程序化证据确认：

- 控制 top-book `imb` 后，`d_volume_z` 对 `@1` 的偏 IC 为 `-0.0504`；
- 控制 `imb` 后，`bid_depth_entropy` 偏 IC 为 `0.0331`；
- 控制 `imb` 后，`d_imb` 偏 IC 为 `0.1785`。

因此事件钟把不同成交量/深档/路径状态合并的假设得到支持，注册新算子：

```text
ActivityClockResampler (operators.op_id=19)
```

首批 3 个候选全部进入平台评估，verdict 均为 `fail` / `dead_end`：

| 因子 | check | ICIR | rank_ic | restest | 结论 |
|---|---:|---:|---:|---|---|
| `ImbVolumeClockPhaseGate_W500_V5000` | `check_done` | 无 | 全零 | R2_X=1.0, dLOOCV=0 | volume-clock 路径未形成可评估信号 |
| `VolumeClockJacobianRank_W500` | `check_done` | 0.255 | 0.0027 | R2_X=0.2553, dLOOCV=0.0268% | 纯活动量方向力不足，但非冗余 |
| `VolumeClockDurationImb_W500_V5000` | `check_done` | 无 | 全零 | R2_X=1.0, dLOOCV=0 | bar duration 路径未形成可评估信号 |

入库结论：

- 三个因子均已 `persist_factor` 入库，lesson id `484/485/486`；
- idea `239` support score 0.2，evaluated factor count 3；
- `ActivityClockResampler` 是语义资产，本次失败不否定算子本身；
- 下一步先做 volume-clock 的平台数据口径核对（`totalVolume()` 增量尺度 vs `V0`），再考虑 notional / OI / imbalance 时钟。

## 10. 全零根因与第二轮/第三轮修复（2026-08-19）

第一轮 `ImbVolumeClockPhaseGate_W500_V5000` 和 `VolumeClockDurationImb_W500_V5000`
全零不是坐标理论失败，而是实现参数错误：

- 平台 `totalVolume()` 的日增量尺度远小于离线 raw cache；
- `V0=5000` 时每天只产生几十根 volume bar；
- `Win=500` 的 ring 在平台按日重置的 session 内永远填不满；
- `VolumeClockDurationImb` 还依赖 wall-clock duration，在时间戳不可用时 rank 恒定。

调试证据：

- `VolumeAccumDebug` 活跃率 99.99%，证明 `totalVolume()` 可读；
- `VolumeBarDailyCountDebug` 按负增量重置后活跃率 99.52%，证明阈值有实际触发；
- density 因子 `V0=1000/Win=150` 时 zero_rate 0.764，证明 ring 尚未日内填满。

修复后的第三轮 run `2026-08-19-7via1l`：

| 因子 | 非零率 | 主力最佳 | restest | verdict |
|---|---:|---:|---|---|
| `ImbVolumeClockPhaseGate_W100_V500` | 54.6% | @5 rank_ic=0.0925, ICIR=2.391 | R2_X=0.186, dLOOCV=0.0067% | fail（@1 子 feed 反号） |
| `VolumeClockDensityImb_W100_V500` | 55.0% | @1 rank_ic=-0.0012, ICIR=-0.213 | R2_X=0.071, dLOOCV=0.018% | fail（预测力闸门不过） |

入库：lesson id `488/489`，idea `242` support score 0.25。
结论：volume-clock 坐标本身在主力短端有方向力，但跨 feed 符号不一致；density
代理无方向力。已开迭代建议 `183/184`。

## 11. 第四至第七批坐标消融（2026-08-19）

继续执行 signed-flow / run / OI / adaptive / FreshPlus 五组对照，全部走完
submit → check → restest → assess：

| run | 因子 | 主力最佳 | @1 子 feed | restest | 结论 |
|---|---|---:|---:|---|---|
| `ikbtnh` | `ImbSignedFlowClockPhaseGate_W100_I250` | @5 ICIR=2.75 | -0.34 | R2=0.17, dLOOCV=0.010% | fail：子 feed 反号 |
| `ikbtnh` | `ImbRunClockPhaseGate_W100_R250` | @5 ICIR=2.97 | -0.46 | R2=0.21, dLOOCV=0.010% | fail：子 feed 反号 |
| `ikbtnh` | `ImbOiClockPhaseGate_W100_O200` | @5 ICIR=2.58 | -0.31 | R2=0.18, dLOOCV=0.007% | fail：子 feed 反号 |
| `wcirav` | `ImbAdaptiveRunClockPhaseGate_W100_N200` | @5 ICIR=1.84 | -0.58 | R2=0.11, dLOOCV=0.009% | fail：稀疏+反号 |
| `5d3z2v` | `ImbAdaptiveRunClockPhaseGate_W50_N50` | @5 ICIR=3.51 | -0.48 | R2=0.21, dLOOCV=0.010% | fail：非稀疏仍反号 |
| `5d3z2v` | `ImbAdaptiveVolumeClockPhaseGate_W50_N50` | @5 ICIR=2.99 | -0.51 | R2=0.19, dLOOCV=0.012% | fail：非稀疏仍反号 |
| `5d3z2v` | `ImbAdaptiveSignedFlowClockPhaseGate_W50_N50` | @5 ICIR=2.61 | -0.48 | R2=0.18, dLOOCV=0.011% | fail：非稀疏仍反号 |
| `rx46j9` | `ImbAdaptiveVolumeClockPhaseGateFreshPlus_W50_N50` | @1 ICIR=4.60 | -1.18 | R2=0.71, dLOOCV=0.017% | fail：子 feed 反号、高冗余 |
| `rx46j9` | `ImbAdaptiveRunClockPhaseGateFreshPlus_W50_N50` | @1 ICIR=4.79 | -1.30 | R2=0.82, dLOOCV=0.022% | fail：子 feed 反号、冗余 |

关键结论：

1. 基线 `ImbAnchoredPhaseGate` 的 @1 子 feed 接近中性（@5 ICIR=0.13），
   而所有 activity-clock 版在子 feed 上都出现真实反号；稀疏修复后反号仍存在。
2. `FreshCoef=+1` 把主力短端 ICIR 推到 4.6~4.8，但子 feed 反号更强，
   说明这不是相位门控极性，而是合约级真实差异。
3. FreshPlus run 版 `R2_X=0.82`，即强主力信号大部分被旧相位因子解释，
   activity clock 没有带来组合增量。
4. 因此 `ActivityClockResampler` 保留为语义算子（op_id=19），
   但“把现有相位 gate 换成 activity clock”这一因子族整体判死。

当前 lesson id 覆盖 `484~500`。后续若继续，建议跳过相位族克隆，转向：

- notional / OI 的 bar-path 新特征，而非同公式换时钟；
- Phase 4 评估坐标实验（日 IC 按 volume/notional 重加权）；
- 或对 @1 子 feed 单独建模合约级相位反号，并给出 basis/calendar 机制解释。
