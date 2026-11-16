import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  Activity, ArrowDownRight, ArrowLeft, ArrowRight, ArrowUpRight, BookOpen,
  ChevronDown, ChevronRight, CircleCheck, Clock3, Code2, Compass,
  ExternalLink, FileText, Filter, GitBranch, Info, Layers3, LayoutDashboard,
  Menu, Microscope, Network, RefreshCw, Search, ShieldCheck, Sparkles,
  AlertCircle, Inbox, ListTree, SlidersHorizontal,
} from 'lucide-react'
import { api } from './api'
import type { ChapterSummary, ChapterDetail, EventItem, ResearchObject, ResearchStatus } from './types'

type Section = 'overview' | 'corpus' | 'experiments'
type FilterKey = 'all' | 'active' | 'done' | 'pending'

const stages = [
  { key: 'corpus', title: '语料抽取', english: 'SOURCE', icon: BookOpen },
  { key: 'hypothesis', title: '假设转译', english: 'HYPOTHESIS', icon: Sparkles },
  { key: 'factor', title: '因子实现', english: 'FACTOR', icon: Code2 },
  { key: 'evaluation', title: '实证评价', english: 'EVALUATION', icon: Activity },
  { key: 'decision', title: '独立性决策', english: 'DECISION', icon: GitBranch },
]

const stageByStatus: Record<ResearchStatus, number> = {
  unseeded: 0, pending: 0, awaiting_hypothesis: 0, awaiting_factor: 1,
  awaiting_evaluation: 2, awaiting_confirmation: 3, awaiting_admission: 4,
  awaiting_fusion: 4, awaiting_split: 4, terminal_admitted: 5,
  terminal_fused: 5, terminal_exhausted: 5, terminal_split: 5,
}

const statusLabels: Record<ResearchStatus, string> = {
  unseeded: '尚未初始化', pending: '等待研究', awaiting_hypothesis: '准备生成假设',
  awaiting_factor: '待实现因子', awaiting_evaluation: '等待实测',
  awaiting_confirmation: '独立验证中', awaiting_admission: '待正式入库',
  awaiting_fusion: '融合研究中', awaiting_split: '等待拆分',
  terminal_admitted: '独立入库', terminal_fused: '融合入库',
  terminal_exhausted: '研究终止', terminal_split: '已分裂',
}

function statusTone(status: ResearchStatus) {
  if (status === 'terminal_admitted' || status === 'terminal_fused') return 'success'
  if (status === 'terminal_exhausted') return 'muted'
  if (status === 'awaiting_fusion' || status === 'awaiting_split') return 'purple'
  if (status === 'unseeded' || status === 'pending') return 'idle'
  return 'active'
}

function cn(...items: (string | false | null | undefined)[]) { return items.filter(Boolean).join(' ') }
function pad(n: number) { return String(n).padStart(2, '0') }
function safeNumber(n: number | null | undefined, digits = 3) { return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(digits) : '—' }
function time(ts: string) {
  const date = new Date(ts)
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

function StatusPill({ status }: { status: ResearchStatus }) {
  return <span className={cn('status-pill', `tone-${statusTone(status)}`)}><i className="status-dot" />{statusLabels[status] || status}</span>
}

function MetricCard({ icon: Icon, label, value, hint, color = 'blue' }: {
  icon: typeof Activity, label: string, value: string | number, hint: string, color?: string,
}) {
  return <div className="metric-card">
    <div className="metric-top"><span>{label}</span><span className={cn('metric-icon', `icon-${color}`)}><Icon size={18} strokeWidth={1.8} /></span></div>
    <div className="metric-value">{value}</div>
    <div className="metric-hint">{hint}</div>
  </div>
}

function EmptyNotice({ title, detail, icon: Icon = Inbox }: { title: string, detail: string, icon?: typeof Inbox }) {
  return <div className="empty-notice"><div className="empty-icon"><Icon size={23} strokeWidth={1.6} /></div><strong>{title}</strong><p>{detail}</p></div>
}

function Sidebar({ section, onSection, expanded, close }: {
  section: Section, onSection: (value: Section) => void, expanded: boolean, close: () => void,
}) {
  const nav = [
    { id: 'overview' as const, text: '研究总览', icon: LayoutDashboard },
    { id: 'corpus' as const, text: '语料库', icon: BookOpen },
    { id: 'experiments' as const, text: '实验与证据', icon: Microscope },
  ]
  return <>
    <div className={cn('sidebar-overlay', expanded && 'show')} onClick={close} />
    <aside className={cn('sidebar', expanded && 'sidebar-open')}>
      <div className="brand"><div className="brand-mark"><Network size={22} strokeWidth={2.15} /></div><div className="brand-name"><strong>FACTOR<span> / </span>AUTOLOOP</strong><small>RESEARCH WORKSPACE</small></div></div>
      <div className="sidebar-group-label">WORKSPACE</div>
      <nav className="primary-nav">
        {nav.map(({ id, text, icon: Icon }) => <button key={id} className={cn('nav-item', section === id && 'nav-active')} onClick={() => { onSection(id); close() }}><Icon size={18} strokeWidth={1.9} /><span>{text}</span>{section === id && <span className="nav-arrow"><ChevronRight size={15} /></span>}</button>)}
      </nav>
      <div className="sidebar-group-label second-label">RESEARCH ENGINE</div>
      <div className="side-engine"><div className="engine-header"><span className="engine-glyph"><Compass size={15} /></span>Corpus-guided Loop</div><div className="engine-line"><span className="engine-line-dot" />《道德经》· 81 章</div><div className="engine-line"><span className="engine-line-dot cyan" />最大拆分深度 2</div></div>
      <div className="sidebar-bottom">
        <div className="sidebar-divider" />
        <div className="env-card"><span className="env-light" /><span><strong>只读观测模式</strong><small>不触发模型或量化任务</small></span><ShieldCheck size={17} /></div>
        <a className="sidebar-docs" href="https://github.com/marcas-G/factor-loop/blob/main/docs/corpus-execution-adapter.md" target="_blank" rel="noreferrer"><FileText size={16} />使用文档<ExternalLink size={14} /></a>
        <div className="sidebar-version">FACTOR RESEARCH SYSTEM <span>v1.0</span></div>
      </div>
    </aside>
  </>
}

function ResearchTree({ objects, activeId, onSelect }: { objects: ResearchObject[], activeId?: string, onSelect: (id: string) => void }) {
  if (!objects.length) return <EmptyNotice icon={GitBranch} title="尚无研究节点" detail="这一章节还未被初始化为研究对象。运行 seed 后将创建根节点。" />
  const byDepth = [...objects].sort((a, b) => a.depth - b.depth || a.object_id.localeCompare(b.object_id))
  return <div className="research-tree">
    {byDepth.map((obj) => <button key={obj.object_id} className={cn('tree-item', `tree-depth-${obj.depth}`, activeId === obj.object_id && 'tree-selected')} onClick={() => onSelect(obj.object_id)}>
      <span className={cn('tree-node-icon', `tree-node-${statusTone(obj.status)}`)}>{obj.depth === 0 ? <Compass size={15} /> : <GitBranch size={14} />}</span>
      <span className="tree-info"><strong>{obj.depth === 0 ? '初始研究假设' : `第 ${obj.depth} 层拆分假设`}</strong><small>{obj.object_id} · {statusLabels[obj.status]}</small></span><ChevronRight size={15} className="tree-chevron" />
    </button>)}
  </div>
}

function NodeDetail({ obj, source, onOpenEvidence }: { obj: ResearchObject | undefined, source: ChapterDetail['source'], onOpenEvidence: () => void }) {
  if (!obj) return <div className="node-empty"><span className="node-label">RESEARCH OBJECT / PENDING</span><h3>尚未生成研究对象</h3><p>当前章节原文已就绪。通过 CLI 初始化队列后，模型才会基于原文章节提出研究假设。</p><div className="inline-command">python -m core.corpus_autoloop.cli seed</div></div>
  return <div className="node-content">
    <div className="node-header"><span className="node-label">RESEARCH OBJECT / {obj.object_id}</span><StatusPill status={obj.status} /></div>
    <h3>{obj.hypothesis?.hypothesis || '等待跨领域假设生成'}</h3>
    {obj.hypothesis ? <>
      <div className="mapping-grid"><div className="mapping-block"><div className="mapping-title"><BookOpen size={13} />原文线索</div><p>{obj.hypothesis.source_quote || source.title}</p></div><div className="mapping-arrow"><ArrowRight size={16} /></div><div className="mapping-block"><div className="mapping-title"><Sparkles size={13} />市场映射</div><p>{obj.hypothesis.market_analogy || '尚无映射描述'}</p></div></div>
      {obj.hypothesis.observable_prediction && <div className="prediction"><div className="prediction-header"><Activity size={15} />可验证预测</div><p>{obj.hypothesis.observable_prediction}</p></div>}
    </> : <div className="hypothesis-placeholder"><Sparkles size={18} /><span>系统尚未对这一章生成金融市场假设。研究内容将在真实执行后出现。</span></div>}
    {obj.factor && <div className="candidate-bar"><Code2 size={17} /><div><span>FACTOR CANDIDATE</span><strong>{obj.factor.name}</strong></div><button onClick={onOpenEvidence}>查看实验 <ArrowUpRight size={14} /></button></div>}
  </div>
}

function EvidencePanel({ obj }: { obj: ResearchObject | undefined }) {
  const ev = obj?.evaluation
  return <div className="evidence-panel">
    <div className="panel-heading"><div><span className="eyebrow">EXPERIMENT / EVIDENCE</span><h3>因子实证记录</h3></div><span className={cn('small-tag', ev ? 'small-tag-live' : '')}>{ev ? '实测记录' : '无实测数据'}</span></div>
    {!ev ? <EmptyNotice icon={Microscope} title="暂无实验结果" detail="尚未收到真实 quant-mcp 执行报告。所有指标保持空白，不使用模拟 IC 或回测数据。" /> : <>
      <div className="evidence-stats"><div><span>ICIR</span><strong>{safeNumber(ev.predictive?.metric_value)}</strong><small>{ev.predictive?.metric_name || '—'}</small></div><div><span>R² (冗余度)</span><strong>{safeNumber(ev.independence?.r2_x)}</strong><small>已有因子解释比例</small></div><div><span>ResIC</span><strong>{safeNumber(ev.independence?.res_ic, 4)}</strong><small>残差预测信息</small></div></div>
      <div className="evidence-record"><div><span>执行记录</span><strong className="mono">{ev.executor_run_id || '—'}</strong></div><div><span>数据分割</span><strong>{ev.data_split === 'holdout_confirmation' ? '独立确认期' : ev.data_split === 'screening' ? '筛选期' : '—'}</strong></div><div><span>独立性决策</span><strong>{ev.independence?.decision === 'independent' ? '独立' : ev.independence?.decision === 'redundant' ? '冗余' : '证据不足'}</strong></div></div>
      <p className="evidence-footnote"><Info size={13} />数据直接来自研究状态库，展示不代表统计显著性或因果结论。</p>
    </>}
  </div>
}

function ActivityList({ items, loading }: { items: EventItem[], loading: boolean }) {
  const names: Record<string, string> = {
    seed: '研究对象已创建', hypothesis: '跨域假设已生成', factor_compiled: '候选因子已定义',
    evaluation: '实证评价已记录', admitted: '因子已独立入库', fusion: '因子融合已评估',
    split: '假设已拆分', split_child: '子研究对象已创建', infeasible: '研究路径已终止',
  }
  return <div className="activity-list">{loading ? <div className="list-loading">正在同步执行记录…</div> : !items.length ? <EmptyNotice title="暂无运行活动" detail="初始化研究队列或开始执行后，事件日志会按时间显示在这里。" icon={Clock3} /> : items.slice(0, 7).map((item, index) => <div className="activity-row" key={item.id}><div className={cn('activity-mark', index === 0 && 'activity-mark-latest')}><span /></div><div className="activity-main"><strong>{names[item.kind] || item.kind}</strong><span>{item.object_id}</span></div><time>{time(item.recorded_at)}</time></div>)}</div>
}

function ChapterList({ chapters, selected, onSelect, query, filter, onFilter, onQuery }: {
  chapters: ChapterSummary[], selected: number, onSelect: (n: number) => void,
  query: string, filter: FilterKey, onFilter: (value: FilterKey) => void, onQuery: (value: string) => void,
}) {
  const filtered = useMemo(() => chapters.filter((item) => {
    const name = `第${item.chapter}章 ${item.chapter} ${item.part} ${item.root_id}`
    const keyword = name.toLowerCase().includes(query.trim().toLowerCase())
    return keyword && (filter === 'all' ||
      (filter === 'pending' && ['pending', 'unseeded'].includes(item.status)) ||
      (filter === 'active' && !['pending', 'unseeded'].includes(item.status) && !item.status.startsWith('terminal_')) ||
      (filter === 'done' && item.status.startsWith('terminal_')))
  }), [chapters, query, filter])
  return <section className="chapter-browser panel" id="chapter-browser">
    <div className="list-panel-head"><div><span className="eyebrow">CORPUS LIBRARY</span><h3>章节研究队列 <span>{chapters.length} CHAPTERS</span></h3></div><Filter size={17} /></div>
    <div className="list-search"><Search size={16} /><input aria-label="搜索章节" value={query} onChange={(e) => onQuery(e.target.value)} placeholder="搜索章节、研究编号..." /></div>
    <div className="filter-row">{([{ id: 'all', text: '全部' }, { id: 'active', text: '进行中' }, { id: 'done', text: '已完成' }, { id: 'pending', text: '待研究' }] as const).map(({ id, text }) => <button key={id} className={cn('filter-chip', filter === id && 'chip-active')} onClick={() => onFilter(id)}>{text}</button>)}</div>
    <div className="chapter-scroll">
      {filtered.length ? filtered.map((ch) => <button key={ch.chapter} className={cn('chapter-row', selected === ch.chapter && 'chapter-selected')} onClick={() => onSelect(ch.chapter)}><span className="chapter-number">{pad(ch.chapter)}</span><span className="chapter-text"><strong>第 {ch.chapter} 章</strong><small>{ch.part} · {ch.total_nodes ? `${ch.total_nodes} 个研究节点` : '尚未研究'}</small></span><span className={cn('chapter-status-light', `light-${statusTone(ch.status)}`)} /><ChevronRight size={15} /></button>) : <div className="no-matches">没有匹配的章节</div>}
    </div>
    <div className="chapter-footer"><BookOpen size={14} />王弼本 · 完整 81 章，按章节抽取</div>
  </section>
}

function App() {
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const chapterNumber = Math.min(81, Math.max(1, Number(params.get('chapter')) || 1))
  const [section, setSection] = useState<Section>('overview')
  const [filter, setFilter] = useState<FilterKey>('all')
  const [query, setQuery] = useState('')
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [showOriginal, setShowOriginal] = useState(true)

  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview })
  const chaptersQuery = useQuery({ queryKey: ['chapters'], queryFn: api.chapters })
  const detailQuery = useQuery({ queryKey: ['chapter', chapterNumber], queryFn: () => api.chapter(chapterNumber) })
  const activity = useQuery({ queryKey: ['activity'], queryFn: api.activity })
  const details = detailQuery.data
  const chapterList = chaptersQuery.data?.chapters || []
  const nodes = details?.research_objects || []
  const currentNode = nodes.find((item) => item.object_id === selectedObjectId) || nodes.find((item) => item.parent_id === null) || nodes[0]
  const activeObjId = currentNode?.object_id
  const objectQuery = useQuery({ queryKey: ['object', activeObjId], queryFn: () => api.object(activeObjId!), enabled: !!activeObjId })
  const summary = overview.data
  const isDisconnected = overview.isError || chaptersQuery.isError || detailQuery.isError

  const selectChapter = (number: number) => { setParams({ chapter: String(number) }); setSelectedObjectId(null); setSection('corpus') }
  const refresh = () => void client.invalidateQueries()
  const moveChapter = (direction: number) => selectChapter(Math.max(1, Math.min(81, chapterNumber + direction)))
  const scrollToEvidence = () => document.getElementById('evidence-section')?.scrollIntoView({ behavior: 'smooth', block: 'center' })

  return <div className="app-shell">
    <Sidebar section={section} onSection={setSection} expanded={mobileOpen} close={() => setMobileOpen(false)} />
    <main className="main-area">
      <header className="topbar"><div className="topbar-start"><button className="mobile-trigger" aria-label="打开菜单" onClick={() => setMobileOpen(true)}><Menu size={20} /></button><span className="breadcrumb-muted">Workspace</span><ChevronRight size={14} /><span className="breadcrumb-bold">{section === 'overview' ? '研究总览' : section === 'corpus' ? '语料库' : '实验与证据'}</span></div><div className="topbar-right"><span className={cn('connection', isDisconnected && 'connection-off')}><span />{isDisconnected ? 'API 未连接' : '研究状态已同步'}</span><button className={cn('icon-button', overview.isFetching && 'rotating')} onClick={refresh} aria-label="刷新研究状态" title="刷新研究状态"><RefreshCw size={17} /></button><span className="topbar-avatar">FA</span></div></header>
      <div className="page-content">
        {isDisconnected && <div className="alert-banner"><AlertCircle size={18} /><span>无法访问本地研究 API。请启动 <code>python -m uvicorn core.corpus_autoloop.dashboard_api:app --host 127.0.0.1 --port 8765</code>。当前没有使用模拟运行数据。</span><button onClick={refresh}>重试</button></div>}
        <div className="page-heading"><div><div className="heading-kicker"><span className="small-line" /> RESEARCH INTELLIGENCE PLATFORM</div><h1>{section === 'experiments' ? '实验与证据' : section === 'corpus' ? '语料研究空间' : '研究控制台'}<span className="heading-period">.</span></h1><p>从外部知识出发，验证可独立贡献预测信息的因子假设。</p></div><div className="page-actions"><span className="read-only-label"><ShieldCheck size={15} />READ ONLY</span><button className="btn-outline" onClick={() => setSection('corpus')}><BookOpen size={16} />浏览语料库</button></div></div>

        <div className="hero"><div className="hero-copy"><div className="hero-topline"><span className="hero-pulse" /> ACTIVE RESEARCH CORPUS <span className="hero-divider" /> 001 / FOUNDATION</div><h2>从《道德经》<br /><em>发现新的因子假设。</em></h2><p>81 章独立研究起点 · 跨领域知识迁移 · 实测独立性筛选<br />融合优先，失败驱动拆分，最多深入两层。</p><div className="hero-actions"><button onClick={() => { setSection('corpus'); document.getElementById('chapter-browser')?.scrollIntoView({ behavior: 'smooth' }) }} className="hero-primary">探索研究队列 <ArrowUpRight size={16} /></button><span>语料驱动 / CORPUS-GUIDED</span></div></div><div className="hero-art" aria-hidden="true"><div className="orb orb-one" /><div className="orb orb-two" /><div className="orb orb-three" /><div className="orb-center"><span>道</span><i>01 — 81</i></div><div className="orb-tag tag-a">SOURCE</div><div className="orb-tag tag-b">HYPOTHESIS</div><div className="orb-tag tag-c">DISCOVERY</div></div></div>

        <div className="metrics-grid"><MetricCard icon={BookOpen} label="语料章节" value={summary?.chapter_count ?? '—'} hint="《道德经》王弼本 · 全章" color="blue" /><MetricCard icon={Layers3} label="研究对象" value={summary?.research_objects ?? '—'} hint={`${summary?.active_objects ?? 0} 个正在推进`} color="violet" /><MetricCard icon={CircleCheck} label="独立入库" value={summary?.admitted_factors ?? '—'} hint="已通过验证与入库" color="green" /><MetricCard icon={GitBranch} label="融合入库" value={summary?.fused_factors ?? '—'} hint="冗余因子融合结果" color="amber" /></div>

        <section className="pipeline-section"><div className="section-header"><div><div className="eyebrow">RESEARCH PIPELINE</div><h2>研究生命周期 <span className="light-subtitle">/ 从思想到证据</span></h2></div><span className="section-meta"><Compass size={15} /> MAX DEPTH 02</span></div><div className="pipeline-steps">{stages.map((st, index) => { const Icon = st.icon; const progress = currentNode ? stageByStatus[currentNode.status] : 0; return <div className={cn('pipeline-step', progress > index && 'pipeline-done', progress === index && currentNode && 'pipeline-current')} key={st.key}><div className="pipeline-icon"><Icon size={19} strokeWidth={1.75} /></div><div className="pipeline-copy"><small>0{index + 1} / {st.english}</small><strong>{st.title}</strong></div>{index !== stages.length - 1 && <ChevronRight size={17} className="pipeline-arrow" />}</div> })}</div></section>

        <div className="section-header workspace-title"><div><div className="eyebrow">KNOWLEDGE TO RESEARCH</div><h2>研究工作台 <span className="light-subtitle">/ 当前聚焦章节</span></h2></div><div className="chapter-switch"><button onClick={() => moveChapter(-1)} disabled={chapterNumber <= 1} aria-label="上一章"><ArrowLeft size={17} /></button><span>{pad(chapterNumber)} <i>/</i> 81</span><button onClick={() => moveChapter(1)} disabled={chapterNumber >= 81} aria-label="下一章"><ArrowRight size={17} /></button></div></div>

        <div className="workspace-grid">
          <ChapterList chapters={chapterList} selected={chapterNumber} onSelect={selectChapter} query={query} filter={filter} onFilter={setFilter} onQuery={setQuery} />
          <div className="work-center">
            <section className="source-panel panel"><div className="panel-heading"><div><div className="eyebrow">PRIMARY SOURCE / ORIGINAL TEXT</div><h3>第 {chapterNumber} 章 <span className="chapter-label">{chapterNumber <= 37 ? '道经' : '德经'}</span></h3></div><button className="collapse-button" onClick={() => setShowOriginal((v) => !v)}><span>{showOriginal ? '收起原文' : '展开原文'}</span><ChevronDown className={cn(!showOriginal && 'chevron-flipped')} size={16} /></button></div>{showOriginal && <div className="original-text">{detailQuery.isLoading ? '正在加载原文…' : details?.source.text || '暂无原文数据'}</div>}<div className="source-bottom"><span><ShieldCheck size={14} /> 版本：王弼本 · 原文章节</span><span className="mono">SHA256 {details?.source.content_sha256?.slice(0, 9) || '—'}</span></div></section>
            <section className="research-panel panel"><div className="panel-heading"><div><div className="eyebrow">RESEARCH / OBJECT DETAIL</div><h3>研究假设与转译</h3></div><span className="depth-indicator"><ListTree size={14} /> 深度 {currentNode?.depth ?? 0} / 2</span></div><NodeDetail obj={currentNode} source={details?.source || { title: '', text: '', chapter: chapterNumber, part: '', unit_id: '', corpus_id: '', content_sha256: '', source_file: '' }} onOpenEvidence={scrollToEvidence} /></section>
          </div>
          <div className="work-right"><section className="tree-panel panel"><div className="panel-heading"><div><div className="eyebrow">HYPOTHESIS EVOLUTION</div><h3>假设演进树</h3></div><span className="mini-icon"><GitBranch size={18} /></span></div><ResearchTree objects={nodes} activeId={activeObjId} onSelect={setSelectedObjectId} /><div className="tree-bottom"><span>拆分上限</span><strong>2 <small>LEVELS</small></strong></div></section><section className="workflow-rule panel"><div className="rule-icon"><SlidersHorizontal size={18} /></div><div><strong>决策逻辑</strong><p>独立入库 · 冗余融合 · 失败拆分</p><small>所有决策由实际证据驱动</small></div></section></div>
        </div>

        <div className="lower-grid"><section id="evidence-section" className="panel experiment-section"><EvidencePanel obj={currentNode} /></section><section className="panel activity-section"><div className="panel-heading"><div><span className="eyebrow">AUDIT TRAIL / ACTIVITY</span><h3>最近研究活动</h3></div><span className="small-tag"><Clock3 size={13} />自动同步</span></div><ActivityList items={activity.data?.events || []} loading={activity.isLoading} /><div className="activity-bottom"><span><ShieldCheck size={14} />仅展示已登记的研究事件</span><span>{objectQuery.data?.events?.length || 0} 条当前节点记录</span></div></section></div>
        <footer className="footer"><span><span className="footer-mark">F/</span> FACTOR AUTOLOOP <i>·</i> CORPUS RESEARCH CONSOLE</span><span>Data source: local corpus + read-only SQLite <ArrowDownRight size={13} /></span></footer>
      </div>
    </main>
  </div>
}

export default App
