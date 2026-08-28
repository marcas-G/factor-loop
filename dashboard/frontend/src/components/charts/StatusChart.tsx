import type { Factor } from "../../types";
import { STATUS_COLORS, STATUS_LABELS } from "../../charts/colors";

export function StatusChart({ factors }: { factors: Factor[] }) {
  const counts = new Map<string, number>();
  for (const f of factors) counts.set(f.status, (counts.get(f.status) ?? 0) + 1);
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const total = factors.length || 1;
  return (
    <figure className="chart-box">
      <figcaption>状态分布</figcaption>
      <div className="hbar">
        {entries.map(([status, n]) => (
          <div key={status} className="hbar-seg"
               style={{ width: `${(n / total) * 100}%`,
                        background: STATUS_COLORS[status] ?? "#5d7089" }}
               title={`${STATUS_LABELS[status] ?? status}: ${n}`} />
        ))}
      </div>
      <ul className="legend">
        {entries.map(([status, n]) => (
          <li key={status}>
            <i style={{ background: STATUS_COLORS[status] ?? "#5d7089" }} />
            {STATUS_LABELS[status] ?? status} · {n}
          </li>
        ))}
      </ul>
    </figure>
  );
}
