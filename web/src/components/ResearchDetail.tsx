import { useState } from 'react'
import {
  ArrowUpRight, BookMarked, Check, CircleDot, Code2, Copy, Database,
  GitFork, Info, Layers, Link2, ListTree, Microscope, SearchCheck,
} from 'lucide-react'
import { formatMetric, formatTime, STATE_LABEL, truncate } from '../lib/display'
import type { Chapter, ResearchObject, ResearchEvent } from '../lib/types'
import StatusPill from './StatusPill'

export type DetailTab = 'overview' | 'source' | 'evidence' | 'lineage'

export default function ResearchDetail({ object, chapter, lineage, events, onSelect }: {
  object?: ResearchObject
  chapter?: Chapter
  lineage: ResearchObject[]
  events: ResearchEvent[]
  onSelect: (id: string) => void
}) {
  const [tab, setTab] = useState<DetailTab>('overview')
  const [copied, setCopied] = useState(false)
  if (!chapter || !object) {
    return <div className="empty-detail">请选择一个研究对象</div>
  }

  async function copyId() {
    if (!object) return
    try {
      await navigator.clipboard.writeText(object.id)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch { setCopied(false) }
  }

  return <div className="detail-content">
    <div className="detail-lead">
      <div className="detail-ledger-row">
        <span className="eyebrow">RESEARCH OBJECT / 研究对象</span>
        <StatusPill group={object.group} status={object.status} detailed />
      </div>
      <div className="detail-heading-row">
        <div><h3>{chapter.title}<span> / {chapter.part}</span></h3>
          <div className="id-line">{object.id}
            <button className="copy-button" onClick={copyId} aria-label="复制研究对象 ID" title="复制 ID">
              {copied ? <Check size={13}/> : <Copy size={13}/>}
            </button>
          </div>
        </div>
        <div className="depth-marker"><span>拆分层级</span><b>{object.depth}<small> / 2</small></b></div>
      </div>
      <div className="detail-source-preview">
        <span className="quote-mark">“</span>
        <p>{object.sourceQuote || truncate(chapter.text, 104)}</p>
        <span className="quote-attribution">《道德经》· {chapter.title}</span>
      </div>
    </div>

    <div className="detail-tabs" role="tablist" aria-label="研究详情">
      {([
        ['overview', '研究假设'], ['source', '原文章节'], ['evidence', '实验证据'], ['lineage', '拆分树'],
      ] as [DetailTab, string][]).map(([id, label]) =>
        <button key={id} type="button" role="tab" aria-selected={tab === id}
          className={tab === id ? 'detail-tab active' : 'detail-tab'} onClick={() => setTab(id)}>
          {label}
        </button>)}
    </div>

    {tab === 'overview' && <div className="detail-tab-content">
      <div className="section-index"><span>01</span> 研究主张 <span className="section-index-en">HYPOTHESIS</span></div>
      {object.hypothesis ? <>
        <p className="hypothesis-text">{object.hypothesis}</p>
        {object.marketAnalogy && <div className="context-line"><GitFork size={15}/><span><b>跨领域映射</b>{object.marketAnalogy}</span></div>}
        {object.observablePrediction && <div className="context-line"><SearchCheck size={15}/><span><b>可观测预测</b>{object.observablePrediction}</span></div>}
      </> : <div className="detail-placeholder">
        <Microscope size={24} />
        <strong>尚未生成研究假设</strong>
        <p>章节已就绪；启动研究循环后，模型将尝试从原文提取可检验的市场机制。</p>
      </div>}

      <div className="thin-divider" />
      <div className="section-index"><span>02</span> 因子规范 <span className="section-index-en">FACTOR SPECIFICATION</span></div>
      {object.factorName ? <div className="factor-mini">
        <div className="factor-name"><Code2 size={15} />{object.factorName}</div>
        <p>{object.factorIntuition || '暂无因子说明'}</p>
        {object.factorFormula && <div className="formula-box"><code>{object.factorFormula}</code></div>}
      </div> : <div className="inline-muted"><Code2 size={16} />暂无已提交的因子规范</div>}
      <div className="thin-divider" />
      <div className="section-index"><span>03</span> 研究状态 <span className="section-index-en">EXECUTION STATUS</span></div>
      <div className="micro-state-list">
        <div><CircleDot size={14} /><span>当前阶段</span><strong>{STATE_LABEL[object.status] || object.status}</strong></div>
        <div><Layers size={14} /><span>研究版本</span><strong>r{object.revision || '—'}</strong></div>
        <div><Database size={14} /><span>实际执行记录</span><strong>{object.executionRef ? '已关联' : '尚无'}</strong></div>
      </div>
    </div>}

    {tab === 'source' && <div className="detail-tab-content">
      <div className="section-index"><span>ORIGINAL TEXT</span><span className="section-index-en">王弼本</span></div>
      <p className="original-text">{chapter.text}</p>
      <div className="source-facts">
        <div><BookMarked size={15} /><span>来源</span><strong>《道德经》· {chapter.part}</strong></div>
        <div><Link2 size={15} /><span>原文索引</span><strong>{chapter.sourceId}</strong></div>
        <div><Info size={15} /><span>原文状态</span><strong>{chapter.sourceStatus === 'draft' ? '来源标记为 draft' : chapter.sourceStatus}</strong></div>
      </div>
      <a className="plain-external-link" href="https://github.com/marcas-G/factor-loop/tree/main/corpora/daodejing"
        target="_blank" rel="noopener noreferrer">查看语料来源与版本说明 <ArrowUpRight size={14}/></a>
    </div>}

    {tab === 'evidence' && <div className="detail-tab-content">
      <div className="section-index"><span>MEASUREMENTS</span><span className="section-index-en">实际执行记录</span></div>
      <div className="evidence-grid">
        <div><small>{object.metricName || 'ICIR / 预测强度'}</small><strong>{formatMetric(object.metricValue)}</strong></div>
        <div><small>R² / 信息重叠</small><strong>{formatMetric(object.r2)}</strong></div>
        <div><small>ResIC / 残差信息</small><strong>{formatMetric(object.resIc)}</strong></div>
      </div>
      {object.executionRef ? <>
        <div className="evidence-entry"><SearchCheck size={15}/><div><strong>执行凭据</strong><code>{object.executionRef}</code></div></div>
        <div className="evidence-entry"><Database size={15}/><div><strong>独立性判断</strong><span>{object.independence || '暂无结论'} · {object.dataSplit || '未注明阶段'}</span></div></div>
      </> : <div className="detail-placeholder evidence-placeholder">
        <Microscope size={24}/><strong>尚无真实评估结果</strong>
        <p>这里仅展示从研究台账读取的执行凭据与指标，不生成模拟 IC、R² 或收益曲线。</p>
      </div>}
      <div className="section-index timeline-title"><span>EVENT LOG</span><span className="section-index-en">最近的研究事件</span></div>
      {events.length ? <div className="timeline-list">
        {events.map((item, i) => <div className="timeline-item" key={`${item.recorded_at}-${i}`}>
          <span className="timeline-dot"/><strong>{item.kind}</strong><small>{formatTime(item.recorded_at)}</small>
        </div>)}
      </div> : <div className="inline-muted">当前研究对象尚无事件记录</div>}
    </div>}

    {tab === 'lineage' && <div className="detail-tab-content">
      <div className="section-index"><span>HYPOTHESIS TREE</span><span className="section-index-en">最大拆分深度 2</span></div>
      {lineage.length > 0 ? <div className="lineage-list">
        {lineage.map((node) => <button key={node.id} type="button" onClick={() => onSelect(node.id)}
          className={`lineage-node ${node.id === object.id ? 'lineage-selected' : ''}`}
          style={{ marginLeft: `${Math.min(node.depth, 2) * 19}px` }}>
          <div className="lineage-node-dot"><GitFork size={13}/></div>
          <div><span>{node.id}</span><strong>{truncate(node.hypothesis || (node.depth === 0 ? '原始章节研究对象' : '等待子假设'), 78)}</strong></div>
          <StatusPill group={node.group} />
        </button>)}
      </div> : <div className="detail-placeholder"><ListTree size={24}/><strong>没有假设分支</strong><p>假设只有在真实融合失败后才会分裂，最多两层。</p></div>}
      <div className="tree-explainer"><GitFork size={15}/><span>假设拆分由实际实验失败触发，不是随机公式交叉。</span></div>
    </div>}
  </div>
}
