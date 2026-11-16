import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import type { DashboardData } from '../lib/types'

function fixture(initialized = false): DashboardData {
  const chapters = Array.from({ length: 81 }, (_, i) => ({
    chapter: i + 1,
    title: `第${i + 1}章`,
    part: i < 37 ? '道经' : '德经',
    sourceId: `daodejing-wangbi-${String(i + 1).padStart(3, '0')}`,
    text: i === 0 ? '道可道，非常道。此兩者，同出而異名。' : `第${i + 1}章原文`,
    sourceFile: `data/chapters/${String(i + 1).padStart(3, '0')}.json`,
    sourceStatus: 'draft',
    status: initialized && i === 0 ? 'awaiting_evaluation' : initialized ? 'pending' : 'uninitialized',
    group: initialized && i === 0 ? 'running' as const : initialized ? 'pending' as const : 'uninitialized' as const,
    objects: 1,
  }))
  return {
    version: 1, corpusId: 'daodejing-wangbi-81-v1', timestamp: '2026-11-16T10:00:00Z',
    initialized, mode: initialized ? 'live_readonly' : 'corpus_preview',
    summary: { chapters: 81, completedChapters: 0, totalObjects: initialized ? 81 : 0,
      admitted: 0, running: initialized ? 1 : 0, pending: initialized ? 80 : 0,
      closed: 0, events: 0, nextObjectId: initialized ? 'RO-DDJ-001' : null,
      states: {},
    },
    chapters,
    objects: chapters.map(c => ({
      id: `RO-DDJ-${String(c.chapter).padStart(3, '0')}`, chapter: c.chapter,
      parentId: null, depth: 0, status: c.status, group: c.group, revision: initialized ? 3 : 0,
      updatedAt: null,
      sourceQuote: '', hypothesis: initialized && c.chapter === 1 ? '成交与盘口的方向冲突是否有新信息？' : '',
      sourcePrinciple: '', marketAnalogy: '', observablePrediction: '', requiredData: [],
      factorName: '', factorFormula: '', factorIntuition: '', metricName: '', metricValue: null,
      predictivePassed: null, r2: null, resIc: null, independence: '', nearestFactors: [],
      executionRef: '', dataSplit: '', fusionSucceeded: null, admitted: false,
    })),
    recentEvents: [],
  }
}

function mount(data: DashboardData) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => data }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Research console', () => {
  it('renders all 81 authentic source chapters as preview, never fake metrics', async () => {
    mount(fixture())
    expect(await screen.findByText('让知识成为')).toBeInTheDocument()
    expect(screen.getByText('语料预览模式')).toBeInTheDocument()
    expect(screen.getByText('研究执行链路')).toBeInTheDocument()
    expect(screen.getByText('尚未生成研究假设')).toBeInTheDocument()
    expect(screen.getByText('暂无已提交的因子规范')).toBeInTheDocument()
    expect(screen.getByText(/尚未发现本地 SQLite 台账/)).toBeInTheDocument()
  })

  it('filters by source section and supports pagination', async () => {
    mount(fixture(true))
    await screen.findByText('章节研究目录')
    const all = screen.getByRole('combobox', { name: '道经或德经筛选' })
    fireEvent.change(all, { target: { value: '德经' } })
    expect(screen.getByText('第38章')).toBeInTheDocument()
    expect(screen.queryByText('第1章')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(screen.getByText('第45章')).toBeInTheDocument()
  })

  it('performs text search and selects actual source chapter', async () => {
    mount(fixture())
    await screen.findByText('章节研究目录')
    fireEvent.change(screen.getByRole('textbox', { name: '搜索章节、原文或研究假设' }),
      { target: { value: '第38章原文' } })
    expect(screen.getByText('第38章')).toBeInTheDocument()
    expect(screen.queryByText('第1章')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '清空搜索' }))
    expect(screen.getByText('第1章')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('道可道，非常道。此兩者，同出而異名。')).toBeInTheDocument())
  })
})
