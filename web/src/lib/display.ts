import type { Group } from './types'

export const GROUP_LABEL: Record<Group, string> = {
  uninitialized: '未初始化',
  pending: '待研究',
  running: '进行中',
  admitted: '已入库',
  closed: '已结束',
}

export const STATE_LABEL: Record<string, string> = {
  uninitialized: '等待初始化',
  pending: '待抽取假设',
  awaiting_hypothesis: '生成假设中',
  awaiting_factor: '等待因子编译',
  awaiting_evaluation: '等待实证评估',
  awaiting_confirmation: '等待独立确认',
  awaiting_admission: '待审核入库',
  awaiting_fusion: '待融合实验',
  awaiting_split: '待假设拆分',
  terminal_admitted: '独立入库',
  terminal_fused: '融合入库',
  terminal_exhausted: '研究结束',
  terminal_split: '已拆分',
}

export const EVENT_LABEL: Record<string, string> = {
  seed: '章节入队', hypothesis: '假设生成', factor_compiled: '因子构造',
  evaluation: '因子评估', fusion: '冗余融合', admitted: '因子入库',
  split: '假设拆分', split_child: '子研究创建', infeasible: '不可实现',
}

export function formatMetric(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toFixed(digits)
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

export function truncate(text: string, max = 90): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}
