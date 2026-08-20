# Platform Capabilities — 评估平台的硬能力边界

> **用途**: 认知协议(minimal-repair 产 repair_contract) + write-factor + assess 的共享参考。
> 决定"修复方向/因子设计能否被平台验证"。超出边界 = 无法验证 = 不要直接产出。
>
> **比世界模型更硬**: 世界模型描述市场机制(可探索),本文档描述平台能力(不可超出的硬边界)。

## 因子评估平台(default_test)

### Y 目标(平台固定, 不可改)

```
Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@{horizon}
```
- **定义**: 价格中点在未来 horizon 秒的 **signed 变化**(方向收益)
- **horizon**: 固定 5 档: @1, @5, @10, @60, @300 秒
- **品种**: 跟 X 的品种走(X=AG 则 Y=AG)

### 平台**不支持**的(修复方向不能产出这些)

- ❌ **|Y| 幅度目标**(绝对收益/波动率/事件幅度)——平台只算 signed 方向收益的 IC
- ❌ **自定义 horizon**(只有固定 5 档)
- ❌ **自定义 Y 定义**(只有 PriceMid)
- ❌ **跨品种 Y**(X=AG 时 Y=AG,不能用 X=AG Y=CU 的 cross-feed 做 Y)

### X 目标(因子输出, 可自由设计)

- 可用字段: bid/ask size[0-4], bid/ask price[0], OI, total_volume(14 原始探针)
- 可用运算: FeedIndicator 框架全部能力(算术/条件/ring buffer/percentile rank/...)
- 约束: 输出必须是 scalar(setXValue(0, ...)),冷启动期输出 0

### 因子评估产出(csv_ic)

| 文件 | 内容 |
|---|---|
| csv_ic_summary.csv | 每 horizon 的 pooled rank IC / ICIR / hit_rate / zero_rate |
| csv_ic_ts.csv | 逐日 rank IC 时序(117 天 × 5 horizon) |
| csv_ic_xcorr.md | 因子间相关性矩阵(同一次 submit 的所有 X↔Y 对) |

## 冗余分析平台(restest / restest_1)

### restest(固定版)

- Feeds 固定: SHFE-AG, SHFE-AG@1, SHFE-AU, SHFE-AU@1
- 正交化对象: AG/AU 72 因子库(qyshen/0727pass_v3)
- α 固定: 0.1
- 产出: R²_X / res_IC / dLOOCV_pct(每 x_col × horizon 一行)

### restest_1(可配置版)

- α 可填(推荐 0.05~0.2)
- 库可选: AG_AU / RU_NR_BR / SN_SN1_CU_ZN_AG_AL_AU / BC_BC1_CU_ZN_CU1_AL_AU_AG / ag_restest_v02
- 日期可选: 一年(20240701~20250630) / 半年(20250101~20250630)
- **Transform sweep**(可选): raw + 14 变换批量残差(delta/acceleration/impulse/ema/macd/kama/zscore/pct/slope/snr/tanh/cross_zero/tick_pressure)
- **Random projection**(可选): 双 pass GELU 随机投影 NN 预筛(测新因子对 NN 天花板的增量)

### restest 产出判据

| 指标 | 含义 | 判据 |
|---|---|---|
| dLOOCV_pct | 对线性模型的净增益% | >1% 显著增量; <0 过拟合; ≈0 无贡献 |
| R²_X | 库能解释新因子多少方差 | >0.8 高冗余(X 空间重复) |
| res_IC | 去掉库冗余后的增量 IC | 绝对值大=独立信号 |

## 对认知协议的约束(minimal-repair 必须遵守)

**repair_contract 的修复方向必须落在 X 侧**(因子输出设计),不能要求改 Y:

| 修复类型 | 平台能验证? | 说明 |
|---|---|---|
| 改因子公式(X 侧) | ✅ 能 | submit → csv_ic 评估 |
| 换门控/变换(X 侧) | ✅ 能 | Transform sweep 可批量验证 |
| 换基底字段(X 侧) | ✅ 能 | 只要字段在 14 探针范围 |
| **换 Y 目标(|Y| 幅度)** | ❌ **不能** | 平台只有 signed 方向收益 |
| **换 horizon** | ❌ 不能 | 固定 5 档 |
| **换品种** | ✅ 能 | Feeds 改品种即可 |

**认知协议碰到"信号对方向无信息但对幅度有信息"的情况**:
1. 沉淀 lesson: "X 是波动率/幅度信号,非方向信号"
2. 产出方向因子时要**重新设计**——把幅度信息编码成方向信号(如:幅度大→方向反转概率高→输出方向)
3. 不要硬产出 |Y| 目标因子(平台无法验证, submit 必然 fail, 产生误导性 dead_end lesson)
