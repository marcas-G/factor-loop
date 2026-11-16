import type { Overview, ChapterSummary, ChapterDetail, ObjectDetail, EventItem } from './types'

export class ApiFailure extends Error {
  constructor(message: string, public status: number) { super(message) }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new ApiFailure(response.status === 503 ? '研究数据库暂时不可读取' : `API 请求失败（${response.status}）`, response.status)
  return response.json() as Promise<T>
}

export const api = {
  overview: () => get<Overview>('/overview'),
  chapters: () => get<{ chapters: ChapterSummary[] }>('/chapters'),
  chapter: (n: number) => get<ChapterDetail>(`/chapters/${n}`),
  object: (id: string) => get<ObjectDetail>(`/research-objects/${encodeURIComponent(id)}`),
  activity: () => get<{ events: EventItem[] }>('/activity?limit=12'),
  health: () => get<{ ok: boolean; mode: string; database_exists: boolean }>('/health'),
}
