import { Circle, CheckCircle2, CircleDashed, Activity, CircleX } from 'lucide-react'
import { GROUP_LABEL, STATE_LABEL } from '../lib/display'
import type { Group } from '../lib/types'

const icons = {
  uninitialized: CircleDashed,
  pending: Circle,
  running: Activity,
  admitted: CheckCircle2,
  closed: CircleX,
}

export default function StatusPill({ group, status, detailed = false }: {
  group: Group; status?: string; detailed?: boolean
}) {
  const Icon = icons[group]
  const label = detailed && status ? STATE_LABEL[status] || status : GROUP_LABEL[group]
  return <span className={`status-pill status-${group}`}>
    <Icon size={12} strokeWidth={2.2} aria-hidden="true" />
    {label}
  </span>
}
