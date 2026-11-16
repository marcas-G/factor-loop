import type { DashboardData, ObjectDetailData } from './types'

async function request<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, {
    signal,
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!res.ok) {
    throw new Error(res.status === 503
      ? '研究数据不可用，请检查 SQLite 路径或 API 服务。'
      : `无法加载数据（HTTP ${res.status}）`)
  }
  return res.json() as Promise<T>
}

export const dashboardQuery = (signal?: AbortSignal) =>
  request<DashboardData>('/api/dashboard', signal)

export const objectQuery = (id: string, signal?: AbortSignal) =>
  request<ObjectDetailData>(`/api/objects/${encodeURIComponent(id)}`, signal)
