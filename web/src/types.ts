export type ResearchStatus = 'unseeded' | 'pending' | 'awaiting_hypothesis' | 'awaiting_factor' |
  'awaiting_evaluation' | 'awaiting_confirmation' | 'awaiting_admission' | 'awaiting_fusion' |
  'awaiting_split' | 'terminal_admitted' | 'terminal_fused' | 'terminal_exhausted' | 'terminal_split'

export interface Overview {
  corpus_title: string
  chapter_count: number
  attempted_chapters: number
  research_objects: number
  completed_objects: number
  admitted_factors: number
  fused_factors: number
  active_objects: number
  status_counts: Record<string, number>
  data_mode: 'live' | 'corpus_only'
  source: string
}

export interface ChapterSummary {
  chapter: number
  title: string
  part: string
  unit_id: string
  content_sha256: string
  status: ResearchStatus
  root_id: string
  total_nodes: number
  completed_nodes: number
}

export interface SourceUnit {
  unit_id: string
  chapter: number
  part: string
  title: string
  text: string
  corpus_id: string
  content_sha256: string
  source_file: string
  source_status?: string
}

export interface Hypothesis {
  source_quote?: string
  source_principle?: string
  market_analogy?: string
  hypothesis?: string
  observable_prediction?: string
  alternative_explanation?: string
  required_data?: string[]
  causal_limit?: string
  failure_diagnosis?: string
}

export interface FactorCandidate {
  name: string
  formula?: string
  intuition?: string
  hypothesis?: string
  categories?: string[]
  required_data?: string[]
  tags?: string[]
}

export interface Evaluation {
  executor_run_id?: string
  execution_ref?: string
  data_split?: string
  predictive?: { passed?: boolean; metric_name?: string; metric_value?: number; evidence_ref?: string }
  independence?: { decision?: 'independent' | 'redundant' | 'inconclusive'; r2_x?: number | null; res_ic?: number | null; nearest_factors?: string[] }
  audit?: { rank_ic?: number; screening_pair?: string; date_range?: { start?: string; end?: string }; zero_rate?: number }
}

export interface ResearchObject {
  object_id: string
  source_id: string
  parent_id: string | null
  depth: number
  status: ResearchStatus
  revision: number
  created_at: string
  updated_at: string
  hypothesis: Hypothesis | null
  factor: FactorCandidate | null
  evaluation: Evaluation | null
  fusion: Record<string, unknown> | null
  admission: Record<string, unknown> | null
  split: Record<string, unknown> | null
}

export interface ChapterDetail { source: SourceUnit; research_objects: ResearchObject[] }
export interface EventItem { id: number; object_id: string; kind: string; recorded_at: string }
export interface ObjectDetail { research_object: ResearchObject; events: EventItem[]; links: Record<string, Record<string, unknown>[]> }
