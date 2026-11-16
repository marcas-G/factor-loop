import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowDownToLine, ArrowRight, BookOpenText, ChevronDown,
  ChevronLeft, ChevronRight, CircleHelp, Command, Database,
  FlaskConical, GitBranch, Layers3, ListFilter, Menu, RefreshCw,
  Search, ShieldCheck, Sparkles, X,
} from 'lucide-react'
import { dashboardQuery } from './lib/api'
import { formatMetric, formatTime, truncate } from './lib/display'
import type { Chapter, DashboardData, Group, ResearchObject } from './lib/types'
import ActivitySection from './components/ActivitySection'
import Pipeline from './components/Pipeline'
import ResearchDetail from './components/ResearchDetail'
import Sidebar from './components/Sidebar'
import StatusPill from './components/StatusPill'

const FILTERS: { value: Group | 'all'; label: string }[] = [
  { value: 'all', label: '全部章节' },
  { value: 'running', label: '进行中' },
  { value: 'pending', label: '待研究' },
  { value: 'admitted', label: '已入库' },
  { value: 'closed', label: '已结束' },
]

const PAGE_SIZE = 7

function objectForChapter(objects: ResearchObject[], chapter: number) {
  return objects.find(o => o.chapter === chapter && o.parentId === null)
}

function SectionTitle({ index, title, english, meta }: {
  index: string; title: string; english: string; meta?: string
}) {
  return <div className="section-heading">
    <div className="section-heading-text"><span className="section-heading-index">{index}</span>
      <div><span className="eyebrow">{english}</span><h2>{title}</h2></div></div>
    {meta && <span className="section-heading-meta">{meta}</span>}
  </div>
}

function KpiCards({ data }: { data: DashboardData }) {
  const stats = [
    { icon: BookOpenText, value: data.summary.chapters, label: '语料章节', sub: '《道德经》 · 王弼本', type: 'amber', extra: '01 / 81' },
    { icon: Layers3, value: data.summary.totalObjects, label: '研究对象', sub: '含拆分产生的子对象', type: 'normal', extra: 'RESEARCH' },
    { icon: FlaskConical, value: data.summary.running, label: '正在研究', sub: '需要推进的实验节点', type: 'mint', extra: 'ACTIVE' },
    { icon: ShieldCheck, value: data.summary.admitted, label: '确认入库', sub: '独立因子与融合成果', type: 'normal', extra: 'VERIFIED' },
  ]
  return <div className="kpi-grid">
    {stats.map(stat => { const Icon = stat.icon
      return <div key={stat.label} className={`kpi-card kpi-${stat.type}`}>
        <div className="kpi-top"><div className="kpi-icon"><Icon size={18}/></div><span>{stat.extra}</span></div>
        <div className="kpi-value">{stat.value.toLocaleString('zh-CN')}<span>{stat.label}</span></div>
        <div className="kpi-sub">{stat.sub}</div>
      </div>
    })}
  </div>
}

function ChapterRow({ chapter, obj, selected, onSelect }: {
  chapter: Chapter; obj?: ResearchObject; selected: boolean; onSelect: () => void
}) {
  return <button type="button" className={`chapter-row ${selected ? 'chapter-selected' : ''}`} onClick={onSelect}>
    <span className="chapter-number">{`${chapter.chapter}`.padStart(2, '0')}</span>
    <span className="chapter-main"><strong>{chapter.title} <i>· {chapter.part}</i></strong>
      <small>{truncate(obj?.hypothesis || chapter.text, 62)}</small></span>
    <span className="chapter-data">{obj?.metricValue !== null && obj?.metricValue !== undefined
      ? <><strong>{formatMetric(obj.metricValue)}</strong><small>{obj.metricName || 'ICIR'}</small></>
      : <span className="chapter-dash">—</span>}</span>
    <StatusPill group={chapter.group} />
    <ChevronRight className="chapter-arrow" size={16}/>
  </button>
}

function downloadSnapshot(data: DashboardData) {
  const payload = JSON.stringify(data, null, 2)
  const blob = new Blob([payload], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `factor-autoloop-snapshot-${new Date().toISOString().slice(0, 10)}.json`
  link.click()
  URL.revokeObjectURL(url)
}

export default function App() {
  const [params, setParams] = useSearchParams()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<Group | 'all'>('all')
  const [part, setPart] = useState<'all' | '道经' | '德经'>('all')
  const [page, setPage] = useState(1)

  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ['corpus-dashboard'],
    queryFn: ({ signal }) => dashboardQuery(signal),
    refetchInterval: 30_000,
  })
  const chosenId = params.get('object') ?? 'RO-DDJ-001'
  const selectedObject = data?.objects.find(o => o.id === chosenId)
  const selectedChapter = data?.chapters.find(c => c.chapter === selectedObject?.chapter)
  const visibleLineage = data?.objects.filter(o => o.chapter === selectedObject?.chapter) ?? []
  const selectedEvents = data?.recentEvents.filter(e => e.object_id === chosenId) ?? []

  const filtered = useMemo(() => {
    if (!data) return []
    const normalized = search.toLocaleLowerCase('zh-CN').trim()
    return data.chapters.filter(c => {
      const o = objectForChapter(data.objects, c.chapter)
      return (filter === 'all' || c.group === filter)
        && (part === 'all' || c.part === part)
        && (!normalized || `${c.title} ${c.text} ${o?.hypothesis ?? ''} ${o?.factorName ?? ''} ${c.chapter}`
          .toLocaleLowerCase('zh-CN').includes(normalized))
    })
  }, [data, filter, part, search])
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const shown = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  function selectChapter(chapter: Chapter) {
    const id = objectForChapter(data?.objects ?? [], chapter.chapter)?.id || `RO-DDJ-${String(chapter.chapter).padStart(3, '0')}`
    selectObject(id)
  }
  function selectObject(id: string) {
    setParams(current => { const next = new URLSearchParams(current); next.set('object', id); return next })
    if (window.innerWidth <= 900) document.getElementById('research-detail')?.scrollIntoView({ behavior: 'smooth' })
  }
  function setFilterAndReset(next: Group | 'all') { setFilter(next); setPage(1) }
  function setPartAndReset(next: 'all' | '道经' | '德经') { setPart(next); setPage(1) }

  if (isPending) return <div className="app-loader"><div className="loader-mark">F<span>.</span></div><p>正在连接研究台账</p><div className="loading-track"><i/></div></div>
  if (error || !data) return <div className="app-loader error-loader">
    <CircleHelp size={36}/><h2>无法读取研究工作台</h2>
    <p>{error instanceof Error ? error.message : '数据加载失败'}</p>
    <code>python -m core.corpus_autoloop.web_api</code>
    <button className="primary-button" onClick={() => void refetch()}><RefreshCw size={16}/>重新连接</button>
  </div>

  const completedPct = Math.round(100 * data.summary.completedChapters / data.summary.chapters)
  const current = data.summary.nextObjectId || '暂无进行中的研究对象'

  return <div className={`app-shell ${sidebarCollapsed ? 'shell-compact' : ''}`}>
    <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(v => !v)} />
    {mobileMenuOpen && <div className="mobile-nav-overlay" onClick={() => setMobileMenuOpen(false)}>
      <div onClick={e => e.stopPropagation()}><Sidebar collapsed={false} onToggle={() => setMobileMenuOpen(false)} />
        <button className="mobile-close" onClick={() => setMobileMenuOpen(false)} aria-label="关闭菜单"><X size={20}/></button>
      </div>
    </div>}
    <div className="main-area">
      <header className="topbar">
        <div className="topbar-left"><button className="mobile-menu icon-button" aria-label="打开导航" onClick={() => setMobileMenuOpen(true)}><Menu size={21}/></button>
          <span>WORKSPACE</span><ChevronRight size={14}/><strong>语料研究工作台</strong></div>
        <div className="topbar-right">
          <div className={`connection-chip ${data.initialized ? 'connected' : ''}`}>
            <span className="connection-dot"/>{data.initialized ? '本地台账已连接' : '语料预览 · 尚未初始化'}</div>
          <button className={`icon-button refresh-button ${isFetching ? 'is-fetching' : ''}`}
            title="刷新研究台账" aria-label="刷新研究台账" onClick={() => void refetch()}><RefreshCw size={18}/></button>
          <span className="user-avatar" title="只读研究控制台" aria-label="只读研究控制台"><Database size={17}/></span>
        </div>
      </header>
      <main className="main-content">
        <section id="overview" className="hero-section">
          <div className="hero-grid" aria-hidden="true"/>
          <div className="hero-text"><div className="hero-kicker"><span className="hero-kicker-dot"/> THE CORPUS EXPERIMENT / 语料驱动研究</div>
            <h1>让知识成为<span>可验证的假设。</span></h1>
            <p>从《道德经》的每一章出发，跨领域映射市场机制。<br/>用真实实验判断独立性，让研究在证据中演化。</p>
            <div className="hero-actions">
              <button className="primary-button" onClick={() => document.getElementById('research')?.scrollIntoView({ behavior: 'smooth' })}>
                查看研究队列 <ArrowRight size={17}/></button>
              <span className="hero-mini-stat"><b>{data.summary.chapters}</b> CHAPTERS &nbsp; / &nbsp; MAX DEPTH <b>02</b></span>
            </div>
          </div>
          <div className="hero-diagram" aria-label="语料到因子的研究逻辑示意">
            <div className="orbit orbit-one"/><div className="orbit orbit-two"/>
            <div className="hero-graph-line hgl-one"/><div className="hero-graph-line hgl-two"/><div className="hero-graph-line hgl-three"/>
            <div className="hero-graph-node hero-node-top"><BookOpenText size={17}/><span>语料 CORPUS</span></div>
            <div className="hero-graph-node hero-node-mid"><Sparkles size={17}/><span>假设 HYPOTHESIS</span></div>
            <div className="hero-graph-node hero-node-bottom"><FlaskConical size={17}/><span>因子 FACTOR</span></div>
            <div className="hero-orbit-center"><GitBranch size={31} strokeWidth={1.4}/><span>FACTOR<br/>RESEARCH</span></div>
            <div className="hero-corner-tag">FROM TEXT TO SIGNAL <span>↗</span></div>
          </div>
        </section>

        <div className="notice-row">
          <div className="notice-left"><span className="small-dot"/>
            {data.initialized ? <><strong>研究台账已加载</strong><span>只读模式 · 最后同步 {formatTime(data.timestamp)}</span></>
              : <><strong>语料预览模式</strong><span>尚未发现本地 SQLite 台账。以下章节为真实原文，因子指标不会模拟生成。</span></>}
          </div>
          <a href="https://github.com/marcas-G/factor-loop/blob/main/docs/corpus-execution-adapter.md"
            target="_blank" rel="noopener noreferrer">查看运行手册 <ArrowRight size={14}/></a>
        </div>

        <KpiCards data={data}/>

        <section className="process-section">
          <div className="process-heading"><div><span className="eyebrow">AUTONOMOUS RESEARCH</span><h2>研究执行链路</h2></div>
            <span className="process-mode"><Command size={14}/> 真实结果驱动 · 最多两层假设拆分</span></div>
          <Pipeline object={selectedObject}/>
          <div className="process-footer"><span><span className="pulse-dot"/> 下一研究对象 <strong>{current}</strong></span>
            <span>已完成章节 <strong>{data.summary.completedChapters} / {data.summary.chapters}</strong></span>
            <div className="progress-rail"><div style={{ width: `${completedPct}%` }}/></div><span className="progress-percent">{completedPct}%</span></div>
        </section>

        <section id="research" className="research-section">
          <SectionTitle index="01" english="RESEARCH OBJECTS / RESEARCH QUEUE" title="研究对象与语料库" meta="01 — 81 · DAO DE JING"/>
          <div className="research-layout">
            <div className="panel chapter-panel">
              <div className="panel-head chapter-panel-head">
                <div><span className="eyebrow">CORPUS / 章节队列</span><h2>章节研究目录 <span className="counter-pill">{filtered.length}</span></h2></div>
                <button className="export-button" onClick={() => downloadSnapshot(data)} title="导出当前台账 JSON"><ArrowDownToLine size={15}/> 导出</button>
              </div>
              <div className="list-controls">
                <label className="search-field"><Search size={17}/>
                  <input value={search} aria-label="搜索章节、原文或研究假设" placeholder="搜索章节、原文、因子或研究假设..."
                    onChange={e => { setSearch(e.target.value); setPage(1) }} />
                  {search && <button onClick={() => { setSearch(''); setPage(1) }} aria-label="清空搜索"><X size={14}/></button>}
                </label>
                <div className="control-row"><div className="filter-switch" role="group" aria-label="研究状态筛选">
                  {FILTERS.map(f => <button type="button" key={f.value}
                    className={filter === f.value ? 'filter-active' : ''} onClick={() => setFilterAndReset(f.value)}>{f.label}</button>)}
                </div>
                <label className="part-select"><ListFilter size={15}/><select value={part} aria-label="道经或德经筛选"
                  onChange={e => setPartAndReset(e.target.value as 'all' | '道经' | '德经')}>
                    <option value="all">全书</option><option value="道经">道经</option><option value="德经">德经</option>
                  </select><ChevronDown size={13}/></label></div>
              </div>
              <div className="chapter-table">
                <div className="chapter-table-head"><span>章节</span><span>研究对象 / 核心假设</span><span>指标</span><span>状态</span><span/></div>
                {shown.length ? shown.map(chapter => <ChapterRow key={chapter.chapter}
                  chapter={chapter} obj={objectForChapter(data.objects, chapter.chapter)}
                  selected={chapter.chapter === selectedObject?.chapter} onSelect={() => selectChapter(chapter)}/>)
                  : <div className="no-search-results"><Search size={28}/><strong>没有匹配的章节</strong><p>尝试调整关键词或筛选条件。</p></div>}
              </div>
              <div className="chapter-table-footer"><span>显示 {filtered.length ? (page - 1) * PAGE_SIZE + 1 : 0}–{Math.min(page * PAGE_SIZE, filtered.length)} / 共 {filtered.length} 章</span>
                <div className="pagination-controls"><button aria-label="上一页" disabled={page <= 1} onClick={() => setPage(p => p - 1)}><ChevronLeft size={16}/></button>
                  <span>{page} / {pages}</span><button aria-label="下一页" disabled={page >= pages} onClick={() => setPage(p => p + 1)}><ChevronRight size={16}/></button></div></div>
            </div>
            <div id="research-detail" className="panel research-detail-panel">
              <ResearchDetail key={selectedObject?.id || 'empty'} object={selectedObject} chapter={selectedChapter}
                lineage={visibleLineage} events={selectedEvents} onSelect={selectObject}/>
            </div>
          </div>
        </section>

        <section className="activity-section">
          <SectionTitle index="02" english="EXPERIMENT TRACE / EVIDENCE" title="实验与研究日志" meta="READ-ONLY EVIDENCE"/>
          <ActivitySection events={data.recentEvents} initialized={data.initialized}/>
        </section>
        <footer className="footer"><div><span className="footer-mark">F.</span> FACTOR AUTOLOOP <span>/ CORPUS RESEARCH CONSOLE</span></div>
          <div><ShieldCheck size={15}/> 只读视图 · 不触发平台执行 <span>© 2026 Research Lab</span></div></footer>
      </main>
    </div>
  </div>
}
