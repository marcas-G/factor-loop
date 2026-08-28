import type { Eval, Factor } from "../types";

interface Props {
  factors: Factor[];
  evaluations: Eval[];
  onFilterGate?: () => void;
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) =>
    `${((i / (values.length - 1)) * 100).toFixed(2)},${(24 - ((v - min) / span) * 22 - 1).toFixed(2)}`);
  const zeroY = 24 - ((0 - min) / span) * 22 - 1;
  return (
    <svg className="spark" viewBox="0 0 100 24" preserveAspectRatio="none">
      {min < 0 && max > 0 && <line x1="0" x2="100" y1={zeroY.toFixed(2)} y2={zeroY.toFixed(2)} />}
      <polyline points={pts.join(" ")} />
    </svg>
  );
}

export function MetricCards({ factors, evaluations, onFilterGate }: Props) {
  const evaluated = factors.filter(f => f.status === "evaluated");
  const passed = factors.filter(f => f.gate_pass);
  const median = (xs: number[]) =>
    xs.length ? xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)] : null;
  const ics = factors.map(f => f.latest_ic).filter((v): v is number => v !== null);
  const icirs = factors.map(f => f.latest_icir).filter((v): v is number => v !== null);
  const recentIc = [...evaluations]
    .sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
    .slice(-20).map(e => e.ic_mean).filter((v): v is number => v !== null);

  const cards: Array<{ label: string; value: number | null;
                       fmt?: (v: number) => string; onClick?: () => void;
                       spark?: boolean }> = [
    { label: "因子总数", value: factors.length, spark: true },
    { label: "已评估", value: evaluated.length },
    { label: "闸门通过", value: passed.length, onClick: onFilterGate },
    { label: "中位 |IC|", value: median(ics.map(Math.abs)), fmt: (v) => v.toFixed(3) },
    { label: "中位 ICIR", value: median(icirs), fmt: (v) => v.toFixed(2) },
    { label: "闸门未过", value: factors.length - passed.length },
  ];
  return (
    <div className="metrics">
      {cards.map(c => (
        <div key={c.label}
             className={`metric-card${c.onClick ? " clickable" : ""}`}
             onClick={c.onClick}>
          <span className="metric-label">{c.label}</span>
          <span className="metric-value">
            {c.value === null ? "—" : c.fmt ? c.fmt(c.value) : c.value}
          </span>
          {c.spark && <Sparkline values={recentIc} />}
        </div>
      ))}
    </div>
  );
}
