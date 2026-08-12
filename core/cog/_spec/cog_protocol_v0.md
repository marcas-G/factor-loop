# Cognitive Protocol v0 Spec

## 核心定义

> **新算子不是从现象产生,而是从错误等价关系产生。**

`Representation(x₁)=Representation(x₂)` 不是问题(表示永远有压缩)。
问题是:**系统默认 `Y(x₁)≈Y(x₂)`,但现实 `Y(x₁)≠Y(x₂)`** —— 当前表示诱导的等价关系,在某个具体任务下不成立。

完整链:
```
现有表示 → 隐含等价(Equivalence Witness)→ 等价失效(任务条件)
       → 竞争解释 → 新可观测区分(Open Question)→ [后置]判重/可行性/抽象
```

## 认知层级严格隔离

| 阶段 | 回答 | 禁令 |
|---|---|---|
| **Assumption** | 表示认为谁相同? | 只产 Equivalence Witness,`behavioral_difference=UNKNOWN`,禁行为词 |
| **Challenge** | 现实为什么怀疑该相同? | 独立 observation,两档证据,`challenge_status` 强制 `CHALLENGE_HYPOTHESIS` |
| **Hypothesis** | 若失效为真,有哪些竞争解释? | ≥3 可区分 + H0,`what_it_predicts_uniquely` 必填 |
| **OperatorQ** | 若 H 为真需要测什么? | `candidate_hidden_structure`+`UNTESTED_HYPOTHESIS`,纯测量问题,不看数据/registry |

后置(创造之后才判):Investigation Intent / Registry Check / Data Feasibility / Factor-disguise(blind verdict)。
原则:**Question first → Feasibility second**。允许 `GOOD_OPERATOR_QUESTION + DATA_UNSUPPORTED`。

## 成熟度分层

```
v0 = Representation Challenge Generation   (产"值得调查的"表示错误假设)
v1 = Representation Challenge Investigation(找 Behavioral Counterexample,证/否)
v2 = Operator Question → Operator Invention(SUPPORTED_HYPOTHESIS 才发明算子)
```

v0 **不证明表示真的错了**(那要 v1),只证明能产出有结构、有现实冲突、可证伪的 Challenge。

## 验收(人工逐条审 4 问 + 核心判据)

- Q1 Assumption 是否说出"**为什么**把 A/B 当相同"(非"忽略历史")
- Q2 Challenge 是否用**独立 observation**(非历史解释)
- Q3 H1/H2/H3 是否**同矛盾不同预测**(非同义词)
- Q4 最终是**新观察问题**还是新因子描述

**核心人工判据(高于平均分)**:删掉 Operator Question,仅看 Assumption→Challenge→Hypothesis,是否已产生此前未意识到的研究问题?YES 才真成功。

退化信号:"忽略历史→缺路径→测持续性"(旧 brainstorm 换四层包装)→ 判失败,回头改 prompt,不进 v1。
