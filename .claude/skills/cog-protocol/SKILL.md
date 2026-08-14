---
name: cog-protocol
description: 认知协议 — 统一链路(因子表示审查 → 新算子发明)。Research Object=Factor。选 Factor → assumption(世界模型 F(A)=F(B)) → evidence(matched 程序层) → adjudicator(CONTRADICTS) → minimal-repair v3(N1+N2 关闭 N3, 含 identifiability) → Operator Invention(4 Gate) → operator contract → 衔接 factor loop。8 个 cog agent。触发:/cog-protocol、或被 research-loop Step1 调用。
---

# Cog-Protocol — 因子表示审查 → 算子发明(统一链路)

给一个 Factor, 审查它自己做出的表示承诺是否被它自己的行为证据推翻; 若需新测量对象, 发明可复用 Operator, 产出 contract 交 factor loop 验证。

**认知协议只做语义审查+发明**: 不判 IC(归 assess), 不写库(归 persist)。

## 输入

- 无参默认: 自动选 Research Object(dead_end / phenomenon / 用户给 xname)
- `/cog-protocol xname=ImbalanceBase`

## ⚠️ 衔接硬规则

每 Step 完成**必须立即在同一回合**发起下一 Step 的第一个 tool call。禁止纯文字回合断流。

## S1 · 选 Research Object + 构造 Factor Profile

```
Bash: python3 core/cog/factor_profile.py <xname>
```
→ factor_profile(identity + construction_view + evidence_view + provenance)

(`inputs.py --seed/--n` 是批量选 N 个 dead_end 的入口,选单因子用 `factor_profile.py <xname>`。)

**视图隔离(硬)**: `construction_view` 只给 assumption-extractor; `evidence_view` 只给 adjudicator。orchestrator(你)负责分派, 不混合。

---

## S2 · 调查链(assumption → evidence → adjudicator → hypothesis → distinction → depth)

### S2.1 Assumption(派 agent)
```
Task({ subagent_type: "cog-assumption-extractor",
  prompt: "construction_view:\n" + <construction_view>
        + "\n必读: .claude/agents/cog/TRADING_WORLD_MODEL.md"
})
```
→ assumptions[](拆前置假设 + 认知盲区, 遍历输入/参与者/结构三维度, 不锚定公式单一方向)

**主会话 schema 自检**: 检查每条 assumption 是否有 F(A)=F(B) 形式 + held_equal/collapsed 具体无泛化 + behavioral=UNKNOWN + 无行为词(IC/收益/alpha)。不通过 → 回 assumption-extractor 补。

**⚠️ 写 assumptions 到文件(衔接 S2.2 的前置)**: schema 自检通过后, 主会话把 agent 返回的 assumptions 数组写成一个 JSON 文件:
```
Bash: cat > /tmp/assumptions.json << 'EOF'
<assumptions 数组的 JSON, 直接贴 agent 返回的数组>
EOF
```
这是 S2.2 的 `--assumptions-file` 输入。别跳过这步直接调 evidence_investigate(它会报"需 --assumption 或 --assumptions-file")。

### S2.2 Evidence Investigation(程序层,1 次 CLI 调用)

```
Bash: /home/lgao/quant-venv/bin/python core/cog/evidence_investigate.py \
      --assumptions-file /tmp/assumptions.json --xname <xname> 2>/dev/null
```

⚠️ **`2>/dev/null` 必加**: 脚本的进度日志(`[evidence] 加载...`)走 stderr, JSON 走 stdout。不加 `2>/dev/null` 会让日志混进 JSON,导致 json.load 失败。

**输出 JSON schema(固定, 别猜字段名)**:

```json
{
  "xname": "<因子名>",
  "y_col": "<Y 列名>",
  "n_samples": 4183984,
  "n_assumptions": 8,
  "summary": {"CONTRADICTS": N, "SUPPORTS": N, "UNCLEAR": N},
  "results": [                         ← 每条假设一条, 数组名就叫 results(不是 assumptions)
    {
      "assumption_id": "A4",
      "assumption": "<假设原文前120字>",
      "matched_held_col": "imb",        ← 程序匹配到的 held_equal 列
      "matched_collapsed_col": "d_imb", ← 程序匹配到的 collapsed 列
      "programmatic_verdict": "CONTRADICTS | SUPPORTS | UNCLEAR",
      "reason": "<判定理由(含 IC 数字)>",
      "n": 836797,
      "avg_ic_collapsed": 0.1785,       ← 控制 held 后 collapsed 的偏 IC
      "avg_ic_held": 0.03,              ← held 列本身的 IC(对照)
      "per_bin": [{"bin":0, "n":..., "ic_collapsed":..., "ic_held":...}, ...]
    }
  ],
  "guidance": "<一句话: 哪些派 adjudicator>"
}
```

**判据(从 results 数组逐条读, 别从 summary 猜)**:
- `programmatic_verdict == "SUPPORTS"` → 假设成立(控制 held 后 collapsed IC<0.005), **不派 adjudicator**
- `programmatic_verdict == "CONTRADICTS"` → 假设被反驳(collapsed IC>0.02), **派 adjudicator 做语义确认**
- `programmatic_verdict == "UNCLEAR"` → 模糊(列匹配不到/样本不足/IC 边界), **派 adjudicator 判定**

**主会话动作**: 从 `results` 里筛出 `programmatic_verdict ∈ {CONTRADICTS, UNCLEAR}` 的假设, 只对它们派 adjudicator。SUPPORTS 的直接跳过。

### S2.3 Adjudicator(派 agent,只派 CONTRADICTS + UNCLEAR)
```
Task({ subagent_type: "cog-equivalence-adjudicator",
  prompt: "assumption:\n" + <contradicts_assumption>
        + "\nevidence_card:\n" + <对应 evidence 结果>
})
```
→ 四档: CONTRADICTS / CONSISTENT / INSUFFICIENT / OOD
**CONTRADICTS → 继续; 其余 → 本 Factor STOP, 回 S1 换对象**

### S2.4 Hypothesis(派 agent)
```
Task({ subagent_type: "cog-hypothesis-generator",
  prompt: "challenge:\n" + <challenge> + "\nassumption:\n" + <assumption>
})
```
→ hypotheses[](≥3+H0, 各 what_it_predicts_uniquely)

**主会话 schema 自检**: ≥3 竞争解释 + H0 + 每条有 what_it_predicts_uniquely(防"可能A可能B")。不通过 → 回 hypothesis-generator 补。

### S2.5 Evidence-Constrained Distinction(主会话, 不派 agent)
选最可区分 hypothesis 对(H1 vs H2; 不足则 H1 vs H0)。主会话拆两层:
- **Layer 1 supported_distinction**(evidence-bound): evidence 最小能推出的区别(如"同 F 下不同 phase 的 Y 不同")。只含 evidence 直接支持。
- **Layer 2 hypothesis_explanation**(UNTESTED): H 的机制解释(如"压力来源不同")。Minimal-repair 不审这层。

### S2.6 Minimal Repair v3 + Identifiability(派 1 agent)
```
Task({ subagent_type: "cog-minimal-repair-critic",
  prompt: "supported_distinction(Layer1):\n" + <Layer1>
        + "\n原因子 construction_view:\n" + <construction_view>
        + "\n必读: .claude/agents/cog/TRADING_WORLD_MODEL.md §4/§6/§7/§11"
        + "\n必读: .claude/agents/cog/PLATFORM_CAPABILITIES.md(平台能力边界)"
        + "\nidentifiability: 判 STRUCTURE 后, 同时判 required_object 能否从当前数据域构造(查 OBS001 order identity 等永久边界)"
})
```
→ 两层判定合一:
  - **depth**: STRUCTURE_NOT_REDUCIBLE(N1+N2 不够) / RAW / STATIC_SUFFICIENT
  - **identifiability**(STRUCTURE 才判): DIRECT/DERIVABLE(当前数据可构造) / PROXY_ONLY / UNIDENTIFIABLE(OBS001 等)
→ STRUCTURE + DERIVABLE → **confirmed Operator Gap → S3**
→ STANDARD_STATIC/RAW → **FACTOR_ITERATION**(产出 repair_contract, 见下)
→ UNIDENTIFIABLE → archive(STOP)

**⚠️ FACTOR_ITERATION 产出 repair_contract(结构化修复 spec, 非散文)**: minimal-repair-critic 在 verdict ∈ {RAW, STANDARD_STATIC} 时必填 `repair_contract`(preserved_signals / new_signals / forbidden_drops / gating_logic / output_composition)。主会话校验 repair_contract 完整后, 把它原样传给 write-factor——**write-factor 只能"翻译"这个 contract, 不能自由发挥**。

---

## S3 · Operator Invention 链(4 Gate, confirmed Gap 才跑)

### S3.0 Gap Card + Factor Stripping(主会话)
拼 Gap Card(source_factor / supported_distinction / carrier / closure_failure / observables / identifiability), 剥因子名/alpha/IC/交易故事, 留语义角色。

### S3.1 Abstraction(派 agent)
```
Task({ subagent_type: "cog-operator-abstraction",
  prompt: "Stripped Gap View:\n" + <stripped>
})
```
→ carrier_ontology + generic_measurement_question

### S3.2 Inventor(派 agent)
```
Task({ subagent_type: "cog-operator-inventor",
  prompt: "carrier:\n" + <carrier> + "\nmeasurement_question:\n" + <question>
})
```
→ ≤3 正交候选

### S3.3 G1/G2 Transfer + G3 Contract(派 1 agent)
```
Task({ subagent_type: "cog-transfer-critic",
  prompt: "carrier + candidates + 要求: 四道 gate(context independence / heterogeneous binding / round trip / factor disguise) + contract 10 字段完整性"
})
```
→ surviving + contract(transfer-critic 含语义质量审查 = G3 contract-gate 职责并入)
→ INCOMPLETE contract → 主会话按 fix_hint 修, 不淘汰 candidate

### S3.4 G4 Reduction(派 1 agent)
```
Task({ subagent_type: "cog-reduction-critic",
  prompt: "surviving candidate + op1-11 闭包 + factor_semantic_search 查 operators 表"
})
```
→ NULL attack(现有 op+组合能否构造相同语义) + library 查重(semantic/composition/rename)
→ **NEW_OPERATOR_NEEDED + NOVEL** 才继续; 否则 REDUCIBLE → STOP

### S3.5 G5 Round-trip(主会话)
operator + 原 Factor binding → 能表达 supported_distinction? → PASS

**4 Gate 全过 = NEW OPERATOR(语义层)** → 产出 operator contract

---

## S3.6 · 记录认知产出到 research_state(必做, 闭环 R1)

认知协议对某 Factor 跑完、确定产出类型后, **立即**更新该 Factor 的 research_state(R1 下一轮选对象靠它):
```
Bash: /home/lgao/quant-venv/bin/python core/retrieval/derived_tables.py \
      --record-attempt <xname> <OUTCOME>
```
OUTCOME 按产出类型:
- S2.6 STRUCTURE + S3 4 Gate 全过 → `NEW_OPERATOR`
- S2.6 STANDARD/RAW → `FACTOR_ITERATION`
- S2.3 INSUFFICIENT → `INSUFFICIENT`
- S2.3 CONSISTENT → `CONSISTENT`
- S2.3 OOD → `OOD`
- S2.3 CONTRADICTS → `CONTRADICTS`

(算子注册若成功 register_operator, 此步之前已做; 此步只更新 research_state 计数 + exhaustion)

---

## S4 · 衔接 factor loop(不在本 skill 内实现)

把 operator contract 交 factor loop:
1. `write-factor`(contract → .h)
2. `submit`(featuretool GenerateXs) → `check`(factor_check)
3. `assess`(ICIR + 撞族 + 残差, **IC 判定和因子入库归 assess**)
4. **算子注册在 S3 产出 contract 后立即做**(register_operator, 语义 4 Gate 过即注册 operators 表 source='cog'; 不受 ICIR 影响 — 算子=资产, 因子=产品)

**⚠️ contract 翻译成因子字段时**: `categories` = 品种代码 `["AG"]`(合法 AG/AU/CU/AL/NI), 不是 angle_code/tags。填错 → `platform_submit_factor` 拦截 `config_error`。

---

## 8 个 agent 职责(清晰正交)

| agent | 输入 | 输出 | 回答的唯一问题 |
|---|---|---|---|
| **assumption-extractor** | construction_view | F(A)=F(B) 假设 | 公式把什么压成相同? |
| **equivalence-adjudicator** | assumption + evidence | CONTRADICTS? | 证据是否真反驳假设? |
| **hypothesis-generator** | challenge + assumption | ≥3 解释 + H0 | 为什么等价失效? |
| **minimal-repair-critic** | supported_distinction + 数据域 + **operators 表** | STRUCTURE? + DERIVABLE? | N1+N2 够吗? **N2 含查 operators 表(动态闭包)**。数据能构造吗? |
| **operator-abstraction** | Stripped Gap View | carrier + measurement_question | 需要什么新被测对象? |
| **operator-inventor** | carrier + question | ≤3 正交候选 | 怎么测这个对象? |
| **transfer-critic** | carrier + candidates | SURVIVE? + contract 完整 | 删故事成立? 能绑≥3? round-trip? 换皮? contract 完整? |
| **reduction-critic** | surviving + **operators 表** + 因子库 | NEW+NOVEL? | 现有 op(含 cog 新算子)+组合 能否构造相同语义? |

**主会话负责**(不派 agent): schema 自检(assumption/hypothesis) / Evidence-Constrained 两层拆分 / Gap Card + Stripping / round-trip / 衔接 factor loop

## 关键不变量

- **Research Object = Factor**
- **视图隔离**: assumption 只看 construction_view; adjudicator 才看 evidence_view
- **Truth ≠ Explanation ≠ Depth**: adjudicator(事实) / hypothesis(解释) / minimal-repair(深度+可识别)
- **minimal-repair v3 关闭 N3**: 只判 N1+N2 + identifiability; 动态统计语义判定在 G4 reduction
- **evidence 程序化**: evidence_query_compiler + probe + evidence_card
- **IC 判定归 assess**: 认知协议只做语义审查+发明

## 不要做

- ❌ assumption 看 evidence(视图泄漏)
- ❌ 用 N3 作 minimal-repair sufficiency 判据(v3 关闭)
- ❌ 把"语义过 4 Gate"当"IC 达标"(实证在 factor loop assess)
- ❌ 认知协议自己写 operators 表(归 register_operator, 4 Gate 过即注册)
- ❌ 派超过 8 个 agent(其余已程序化/主会话/合并)
