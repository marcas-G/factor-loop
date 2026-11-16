import { useState } from 'react'
import {
  Activity, ArrowUpRight, BookOpenText, ChartNoAxesCombined, FlaskConical,
  Github, LayoutDashboard, Layers3, PanelLeftClose, PanelLeftOpen, ShieldCheck,
} from 'lucide-react'

const NAV = [
  { label: '研究总览', icon: LayoutDashboard, target: 'overview' },
  { label: '研究对象', icon: Layers3, target: 'research' },
  { label: '语料与假设', icon: BookOpenText, target: 'research-detail' },
  { label: '实验记录', icon: Activity, target: 'activity' },
]

function goTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export default function Sidebar({ collapsed, onToggle }: {
  collapsed: boolean; onToggle: () => void
}) {
  const [active, setActive] = useState('overview')
  return <aside className={`sidebar ${collapsed ? 'sidebar-collapsed' : ''}`}>
    <div className="brand-row">
      <div className="brand-mark" aria-hidden="true"><span>F</span><span className="brand-dot" /></div>
      {!collapsed && <div className="brand-wordmark"><strong>FACTOR <span>AUTOLOOP</span></strong><small>RESEARCH INTELLIGENCE</small></div>}
      <button className="icon-button side-collapse" onClick={onToggle}
        aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}>
        {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
      </button>
    </div>

    <div className="side-space" />
    {!collapsed && <div className="side-caption">WORKSPACE / 工作空间</div>}
    <nav className="main-nav" aria-label="工作台导航">
      {NAV.map((item) => {
        const Icon = item.icon
        return <button key={item.target} className={`nav-item ${active === item.target ? 'nav-active' : ''}`}
          title={item.label} onClick={() => { setActive(item.target); goTo(item.target) }}>
          <Icon size={18} strokeWidth={1.85} />
          {!collapsed && <span>{item.label}</span>}
          {!collapsed && active === item.target && <span className="nav-active-line" />}
        </button>
      })}
    </nav>

    {!collapsed && <>
      <div className="side-separator" />
      <div className="side-caption">RESEARCH ENGINE / 研究引擎</div>
      <div className="engine-list">
        <div><FlaskConical size={16} /><span>假设生成引擎</span><i className="engine-ready" /></div>
        <div><ChartNoAxesCombined size={16} /><span>因子执行与评估</span><i className="engine-ready" /></div>
        <div><ShieldCheck size={16} /><span>证据审核门禁</span><i className="engine-ready" /></div>
      </div>
    </>}

    <div className="sidebar-bottom">
      {!collapsed && <div className="corpus-side-card">
        <div className="mini-book-icon"><BookOpenText size={18} /></div>
        <span className="corpus-side-overline">当前语料库 / CORPUS</span>
        <strong>道德经 <span>· 王弼本</span></strong>
        <p>81 个章节，逐章生成并检验研究假设。</p>
        <button className="sidebar-detail-link" onClick={() => goTo('research')}>
          浏览全部章节 <ArrowUpRight size={14} />
        </button>
      </div>}
      <a className="github-link" target="_blank" rel="noopener noreferrer"
        href="https://github.com/marcas-G/factor-loop" title="打开 GitHub 仓库">
        <Github size={17}/>{!collapsed && <> GitHub 仓库 <ArrowUpRight size={14}/></>}
      </a>
    </div>
  </aside>
}
