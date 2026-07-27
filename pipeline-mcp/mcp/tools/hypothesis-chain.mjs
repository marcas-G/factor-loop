// 组 6: 必然假设生成机的论证链工具。
//
// persist_argument_chain: 写假设 + 结构化论证链（argument_chain）到 ideas 表。
//   区别于 persist_idea（纯文本 idea）——本工具携带从约束耦合逼出的完整论证。
// hypothesis_get: 读假设论证链 + 支持度（reviewer-agent 审稿 / 忠实度判定 读用）。
//
// 设计依据（严格以新框架为准）:
//   - 论证链是【假设】的属性（一假设挂多因子），放 ideas 表，不放 factors 表
//   - 假设级支持度连续不绝对判断（support_score，阶段2 才聚合，此处仅落库载体）
//   - 论证链结构对应生成流水线 S1-S6: Σ → 超加性耦合 → 约束 → 唯一性证明 → 竞争解释 → 可证伪痕迹

import * as factorDb from "../../lib/factor-db.mjs";

export const persistArgumentChainSchema = {
  name: "persist_argument_chain",
  description:
    "必然假设生成机：写一条假设 + 结构化论证链到 ideas 表。携带论证链（Σ/超加性耦合/唯一性证明/竞争解释/可证伪痕迹），区别于 persist_idea 的纯文本。论证链是假设的属性，不是因子的属性。",
  inputSchema: {
    type: "object",
    properties: {
      text: {
        type: "string",
        description: "假设陈述（30-80 字，从约束耦合逼出的必然结论，非坐标拼装的散文）",
      },
      argument_chain: {
        type: "object",
        description:
          "结构化论证链。必填字段: background_axioms[](Σ) / superadditive_coupling{A,B,C,entailment_proof,superadditivity_proof,minimality}(超加性耦合,S2) / constraint(S3) / uniqueness_proof{type∈extremum|contraction|zero_dof|equivalence|minimal_sufficient, reasoning}(S4) / competing_explanations[](S6b,每项含rival,distinguishing_observation,exclusion_test) / falsifiable_trace(S6a,解→X演绎预言)",
      },
      parent_idea_id: { type: "integer", description: "可选: 父假设 id（迭代/精化时）" },
      necessity_grade: {
        type: "string",
        enum: ["necessary", "identification", "conditional", "draft"],
        description: "必然性分级。necessary=过S2+S4真硬证; identification=S2硬但S4退化为可识别标量(Roll式 s=2√(-Cov)); conditional=S2有S4弱; draft=待补。reviewer pass 时判定,degrade 时按建议填。",
      },
      angle_code: { type: "string", description: "可选: 信息角度 code(explore 操作产时填 G1 触发角度;graph_angle_coverage 据此判该角度已被 idea 触及,不再当 fresh,避免 graph 反复往已触及角度派 explore 产同方向对偶命题)" },
    },
    required: ["text", "argument_chain"],
  },
};
export async function persistArgumentChainHandler({ text, argument_chain, parent_idea_id, necessity_grade, angle_code }) {
  const id = factorDb.addHypothesis(text, argument_chain, {
    parentIdeaId: parent_idea_id ?? null,
    necessityGrade: necessity_grade ?? null,
    angleCode: angle_code ?? null,
  });
  return { idea_id: id };
}

export const getHypothesisSchema = {
  name: "hypothesis_get",
  description:
    "读假设的论证链 + 支持度。reviewer-agent 对抗审稿、忠实度判定（因子实现是否忠于论证链）时读用。argument_chain 自动从 JSON 反序列化。",
  inputSchema: {
    type: "object",
    properties: {
      idea_id: { type: "integer", description: "ideas.id" },
    },
    required: ["idea_id"],
  },
};
export async function getHypothesisHandler({ idea_id }) {
  const row = factorDb.getHypothesis(idea_id);
  if (!row) return { ok: false, error: `idea_id 不存在: ${idea_id}` };
  let chain = null;
  if (row.argument_chain) {
    try {
      chain = JSON.parse(row.argument_chain);
    } catch {
      chain = row.argument_chain; // 反序列化失败保留原文，不阻塞审稿
    }
  }
  return {
    ok: true,
    id: row.id,
    text: row.text,
    argument_chain: chain,
    necessity_grade: row.necessity_grade,
    support_score: row.support_score,
    evaluated_factor_count: row.evaluated_factor_count,
    status: row.status,
  };
}

export const ALL_HYPOTHESIS_SCHEMAS = [persistArgumentChainSchema, getHypothesisSchema];
export const ALL_HYPOTHESIS_HANDLERS = {
  persist_argument_chain: persistArgumentChainHandler,
  hypothesis_get: getHypothesisHandler,
};
