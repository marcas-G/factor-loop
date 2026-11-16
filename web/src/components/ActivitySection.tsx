import { useMemo } from 'react'
import {
  Activity, ArrowUpRight, CalendarClock, DatabaseZap, FolderSearch,
} from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { EVENT_LABEL, formatTime } from '../lib/display'
import type { ResearchEvent } from '../lib/types'

function eventDays(events: ResearchEvent[]) {
  const dates = Array.from({ length: 7 }, (_, index) => {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    d.setDate(d.getDate() - 6 + index)
    const key = `${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, '0')}-${`${d.getDate()}`.padStart(2, '0')}`
    return { name: `${d.getMonth() + 1}/${d.getDate()}`, key, events: 0 }
  })
  for (const event of events) {
    const d = new Date(event.recorded_at)
    if (Number.isNaN(d.getTime())) continue
    const key = `${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, '0')}-${`${d.getDate()}`.padStart(2, '0')}`
    const bucket = dates.find(x => x.key === key)
    if (bucket) bucket.events++
  }
  return dates
}

export default function ActivitySection({ events, initialized }: {
  events: ResearchEvent[]
  initialized: boolean
}) {
  const data = useMemo(() => eventDays(events), [events])
  const recent = data.some(d => d.events > 0)

  return <section id="activity" className="activity-layout">
    <div className="panel activity-panel">
      <div className="panel-head">
        <div><span className="eyebrow">ACTIVITY / 实验活动</span><h2>研究活动趋势</h2></div>
        <div className="panel-head-meta"><CalendarClock size={15}/> 最近 7 天</div>
      </div>
      <div className="chart-area">
        {recent ? <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 15, right: 6, bottom: 0, left: -26 }}>
            <defs><linearGradient id="activityGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#76cbbb" stopOpacity={0.25}/>
              <stop offset="100%" stopColor="#76cbbb" stopOpacity={0}/>
            </linearGradient></defs>
            <CartesianGrid stroke="#22313b" vertical={false} strokeDasharray="3 6"/>
            <XAxis dataKey="name" tick={{ fill: '#80919b', fontSize: 11 }} tickLine={false} axisLine={false}/>
            <YAxis allowDecimals={false} tick={{ fill: '#80919b', fontSize: 11 }} tickLine={false} axisLine={false}/>
            <Tooltip contentStyle={{ borderRadius: 12, background: '#13212a', border: '1px solid #2d414d', color: '#e8eeee' }}
              labelStyle={{ color: '#e8eeee' }} formatter={(value) => [`${value ?? 0} 条`, '研究事件']}/>
            <Area type="monotone" dataKey="events" stroke="#7ad2c0" fill="url(#activityGradient)" strokeWidth={2.5} dot={false}/>
          </AreaChart>
        </ResponsiveContainer> : <div className="empty-chart">
          <div className="empty-chart-rings"><Activity size={30}/></div>
          <strong>暂无最近 7 天的研究事件</strong>
          <span>启动实际研究任务后，事件记录将自动显示在此处。</span>
          <div className="empty-baseline"><i/><i/><i/><i/><i/><i/><i/></div>
        </div>}
      </div>
    </div>
    <div className="panel event-panel">
      <div className="panel-head">
        <div><span className="eyebrow">TRACE / 研究事件</span><h2>最新研究记录</h2></div>
        <DatabaseZap size={17} className="head-accent-icon"/>
      </div>
      {events.length > 0 ? <div className="recent-event-list">
        {events.slice(0, 5).map((ev, i) => <div className="recent-event" key={`${ev.object_id}-${ev.recorded_at}-${i}`}>
          <div className="recent-event-icon"><Activity size={14}/></div>
          <div><strong>{EVENT_LABEL[ev.kind] || ev.kind}</strong><span>{ev.object_id}</span></div>
          <time>{formatTime(ev.recorded_at)}</time>
        </div>)}
      </div> : <div className="event-empty">
        <FolderSearch size={27} />
        <span>{initialized ? '暂无研究事件记录' : '等待初始化研究台账'}</span>
        <p>每一次假设生成、验证和拆分都会形成可追溯记录。</p>
      </div>}
      <a className="event-more-link" href="https://github.com/marcas-G/factor-loop/blob/main/docs/corpus-execution-adapter.md"
        target="_blank" rel="noopener noreferrer">查看运行与审计说明 <ArrowUpRight size={14}/></a>
    </div>
  </section>
}
