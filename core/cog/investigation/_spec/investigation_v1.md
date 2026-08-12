# Investigation v1 Spec — 冻结判据(2026-08-07 用户审结 Case A 后定案)

## 目标

把 Representation Challenge 转成可被数据实验支持/反驳: 
`Challenge → Test Contract → Probe → Evidence → Verdict`

v1 硬禁令: 不发明算子 / 不优化 alpha / 每 case ≤2 probe(防 adaptive mining)。

## 证据强度: 三级晋升规则(B/C 复用,非 Case A 特判)

| Level | 名称 | 门槛 |
|---|---|---|
| L1 | `CHALLENGE_SUPPORTED` | coarse conditional separation + OOS direction stability |
| L2 | `REPRESENTATION_FAILURE_SUPPORTED_ONCE` | L1 + continuous insufficiency PASS + narrow-caliper distributional counterexample PASS + day/block robustness PASS |
| L3 | `DISTINCTION_GENERALIZED` | L2 + 第二个独立 op6 binding 或第二个 symbol/regime 同结论 |

**只有 L2 才写入 Supported Distinction Registry;L1 只存 STRONG_CANDIDATE。**

## 三个识别问题的硬性要求(probe 必须满足)

1. **桶内残余混杂**(product 分位桶 ≠ product 近似):粗分位桶内 S 高低组的 P 均值差可高达 0.4(实证)。
   必须用**绝对窄带**(如 P∈[0.15,0.25] 宽 0.1)或连续控制,不能只用分位桶。
2. **高频样本 IID 放大**(z=72 在 417 万 500ms 样本下无解释价值):同日相关 + horizon 重叠。
   **必须报 day-level / block-clustered uncertainty**:117 daily effects / median / positive-day ratio / day t / block bootstrap CI(10 天块)。
3. **model 泄漏**:断点/超参必须在 train 内定;test 块只评价。滚动时间块 cross-fit,固定模型不搜索。

## A1 — Continuous conditional sufficiency(判定 L2 第 2 项)

- M0: Y = f(P)(允许非线性:20 分位桶哑变量)
- M1: Y = f(P, S)(桶哑变量 + 桶内 S 线性;P,S 确定 G,decomposition 只需一个额外自由度)
- 滚动时间块 OOS:训练=块1..k,测试=块k+1;断点在 train 上定(防泄漏);test 只评价
- Δ_OOS = MSE0 − MSE1 > 0 且跨块稳定(全 fold 正)→ `Y 不⟂ S|P` → product-only 不充分
- 语义: signal 自身预测力不是需要消除的混杂——控制 P 后 S 有稳定增量,本身就是 product 不充分的证据。

## A2 — Narrow-caliper matched distributional counterexample(判定 L2 第 2 项)

- 绝对窄带内(如 P∈[0.15,0.25]),同 P 下 S 高 ⟺ G 低 = decomposition 不同
- 比较两组 Y 的行为**分布**(E[Y] 差 + hit 差),不是单样本
- day-level:逐天窄带内 S 高低组 Y 差 → 117 daily effects → median / pos-day ratio / day t / block bootstrap CI
- **Behavioral Counterexample 定义(修正)**: d_R(A,B) < ε_R(表示近似相同) 且 d(P(Y|A), P(Y|B)) > δ(行为分布稳定不同)。
  **distributional counterexample,不是单样本反例**——realized Y 是随机的,不要求两个具体时点未来不同。

## Reviewer 两轴(修正后)

```yaml
challenge_verdict: SUPPORTED | REFUTED | INCONCLUSIVE | DATA_UNIDENTIFIABLE
representation_failure:
  status: NOT_CONFIRMED | PENDING_MATCHED_CONFIRMATION | SUPPORTED
  reason: []
```

- `NOT_CONFIRMED` 的理由是"coarse conditioning / clustered uncertainty 未建",**不是**"没找到逐样本反例"(那是过严)。
- `SUPPORTED` 只允许 L2 三项(continuous sufficiency + narrow-caliper distributional + day/block)全 PASS。

## H 机制层 vs Challenge 层分离

- Challenge 层: P 是否充分?→ 可判
- Mechanism 层: S 重要还是 G 重要?→ 同 P 下 S 与 G 反相关,当前实验不可区分
- 允许 `Challenge SUPPORTED + H1/H2 INCONCLUSIVE`,不矛盾。

## probe 规范

- 探针暴露**被 challenge 针对的真实内部坐标**(rank 前 raw),不重选"语义独立弱预测"pair
- 探针是测量具非发明:只暴露坐标,不发明结构;submit 不 persist 不进库
- 结论 scope 降到 instance-level: `{operator_pattern, instance, signal, gate, generalization: INSTANCE_ONLY}`
  只有第二个异质 op6 binding 重复出现才升 family-level。
