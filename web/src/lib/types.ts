export type Group = 'uninitialized' | 'pending' | 'running' | 'admitted' | 'closed'

export interface Chapter {
  chapter: number
  title: string
  part: string
  sourceId: string
  text: string
  sourceFile: string
  sourceStatus: string
  status: string
  group: Group
  objects: number
}

export interface ResearchObject {
  id: string
  chapter: number
  parentId: string | null
  depth: number
  status: string
  group: Group
  revision: number
  updatedAt: string | null
  sourceQuote: string
  hypothesis: string
  sourcePrinciple: string
  marketAnalogy: string
  observablePrediction: string
  requiredData: string[]
  factorName: string
  factorFormula: string
  factorIntuition: string
  metricName: string
  metricValue: number | null
  predictivePassed: boolean | null
  r2: number | null
  resIc: number | null
  independence: string
  nearestFactors: string[]
  executionRef: string
  dataSplit: string
  fusionSucceeded: boolean | null
  admitted: boolean
}

export interface ResearchEvent {
  object_id: string
  kind: string
  recorded_at: string
}

export interface Summary {
  chapters: number
  completedChapters: number
  totalObjects: number
  admitted: number
  running: number
  pending: number
  closed: number
  events: number
  nextObjectId: string | null
  states: Record<string, number>
}

export interface DashboardData {
  version: number
  corpusId: string
  timestamp: string
  initialized: boolean
  mode: 'live_readonly' | 'corpus_preview'
  summary: Summary
  chapters: Chapter[]
  objects: ResearchObject[]
  recentEvents: ResearchEvent[]
}

export interface ObjectDetailData {
  object: ResearchObject
  source: Chapter
  lineage: ResearchObject[]
  events: ResearchEvent[]
}
