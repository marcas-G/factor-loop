export interface Tag { name: string; description: string | null }

export interface Factor {
  xname: string;
  class_name: string | null;
  file_path: string | null;
  formula_text: string | null;
  params: string | null;
  status: string;
  verdict: string | null;
  latest_ic: number | null;
  latest_icir: number | null;
  latest_sharpe: number | null;
  latest_rank_ic: number | null;
  latest_r2_x: number | null;
  latest_res_ic: number | null;
  created_ts: string | null;
  last_updated_ts: string | null;
  deprecated_at: string | null;
  quality_score: number | null;
  quality_grade: string | null;
  intuition: string | null;
  anchor_text: string | null;
  origin_type: string | null;
  cohort_tag: string | null;
  operator_chain: string | null;
  evaluation_status: string | null;
  tags: Tag[];
  resic_ic_ratio: number | null;
  gate_pass: boolean;
  failed_gates: string[];
  s_ic: number | null; s_icir: number | null; s_res_ic: number | null; s_r2: number | null;
  agg_score: number | null;
}

export interface Eval {
  id: number; factor_xname: string; idea_id: number | null; ts: string | null;
  symbol: string | null; freq: string | null;
  ic_mean: number | null; icir: number | null; sharpe: number | null; rank_ic: number | null;
  eval_metrics: string | null; eval_mode: string | null; significant: number | null; raw_path: string | null;
}

export interface Iteration {
  id: number; from_xname: string; to_xname: string; idea_id: number | null;
  change_note: string | null; reason: string | null;
  outcome: string | null; icir_delta: number | null; ts: string | null; status: string | null;
}

export interface LineageEdge {
  parent_xname: string; child_xname: string; relation_type: string | null;
  outcome: string | null; confidence: number | null; op_id: number | null; operator_name: string | null;
}

export interface LineageBranch {
  root_xname: string; root_status: string | null; member_count: number;
  max_depth: number; evaluated_count: number | null; dead_end_count: number | null;
}

export interface Lesson {
  id: number; type: string; scope: string; text: string;
  evidence: string | null; idea_id: number | null; factor_xname: string | null;
  created_ts: string | null; deprecated_at: string | null;
}

export interface Snapshot {
  factors: Factor[];
  evaluations: Eval[];
  iterations: Iteration[];
  lineage_edges: LineageEdge[];
  lineage_branches: LineageBranch[];
  lessons: Lesson[];
  meta: { dbPath: string; dbModifiedAt: string; generatedAt: string };
}
