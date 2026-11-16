import { ArrowRight, BookOpenText, GitBranch, GitMerge, FlaskConical, ShieldCheck } from 'lucide-react'
import type { ResearchObject } from '../lib/types'

const STAGES = [
  { icon: BookOpenText, label: '语料抽取', step: '01' },
  { icon: GitBranch, label: '假设生成', step: '02' },
  { icon: FlaskConical, label: '因子验证', step: '03' },
  { icon: ShieldCheck, label: '独立性评估', step: '04' },
  { icon: GitMerge, label: '入库 / 融合', step: '05' },
]

function phaseIndex(status: string) {
  if (status === 'uninitialized' || status === 'pending') return -1
  if (status === 'awaiting_hypothesis') return 0
  if (status === 'awaiting_factor') return 1
  if (status === 'awaiting_evaluation') return 2
  if (status === 'awaiting_confirmation' || status === 'awaiting_fusion') return 3
  return 4
}

export default function Pipeline({ object }: { object?: ResearchObject }) {
  const current = phaseIndex(object?.status ?? 'uninitialized')
  return <div className="pipeline-flow" aria-label="研究执行流程">
    {STAGES.map(({ icon: Icon, label, step }, i) =>
      <div className="pipeline-fragment" key={step}>
        <div className={`pipeline-stage ${current > i ? 'stage-complete' : current === i ? 'stage-current' : ''}`}>
          <div className="pipeline-stage-icon"><Icon size={18} strokeWidth={1.8} /></div>
          <div><small>{step} / STEP</small><span>{label}</span></div>
        </div>
        {i < STAGES.length - 1 && <ArrowRight className="pipeline-arrow" size={16} />}
      </div>
    )}
  </div>
}
