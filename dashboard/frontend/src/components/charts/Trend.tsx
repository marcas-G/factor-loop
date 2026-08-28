import { useMemo } from "react";
import type { Factor, LineageEdge } from "../../types";

interface Props { factors: Factor[]; edges: LineageEdge[] }

const W = 720, H = 260, M = { l: 44, r: 44, t: 14, b: 30 };

export function Trend({ factors, edges }: Props) {
  const series = useMemo(() => {
    const parent = new Map(edges.map(e => [e.child_xname, e.parent_xname]));
    const depth = (name: string, seen: Set<string>): number => {
      if (seen.has(name)) return 0;
      const p = parent.get(name);
      if (!p) return 0;
      seen.add(name);
      return 1 + depth(p, seen);
    };
    const byGen = new Map<number, Factor[]>();
    for (const f of factors) {
      const d = depth(f.xname, new Set());
      byGen.set(d, [...(byGen.get(d) ?? []), f]);
    }
    return [...byGen.entries()].sort((a, b) => a[0] - b[0]).map(([gen, fs]) => {
      const med = (xs: number[]) =>
        xs.length ? xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)] : null;
      return {
        gen, n: fs.length,
        ic: med(fs.map(f => f.latest_ic).filter((v): v is number => v !== null).map(Math.abs)),
        icir: med(fs.map(f => f.latest_icir).filter((v): v is number => v !== null).map(Math.abs)),
        passRate: fs.length ? fs.filter(f => f.gate_pass).length / fs.length : 0,
      };
    });
  }, [factors, edges]);

  if (!series.length) return (
    <figure className="chart-box"><figcaption>代际趋势</figcaption><p className="empty">无数据</p></figure>
  );

  const icMax = Math.max(...series.map(s => s.ic ?? 0), 0.1) * 1.15;
  const icirMax = Math.max(...series.map(s => s.icir ?? 0), 0.5) * 1.15;
  const xs = series.map((_, i) => M.l + (i + 0.5) * (W - M.l - M.r) / series.length);
  const yIc = (v: number) => H - M.b - (v / icMax) * (H - M.t - M.b);
  const yIcir = (v: number) => H - M.b - (v / icirMax) * (H - M.t - M.b);
  const bw = (W - M.l - M.r) / series.length * 0.5;

  return (
    <figure className="chart-box trend">
      <figcaption>代际趋势 · IC / ICIR 中位数与通过率</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`}>
        {[0.25, 0.5, 0.75, 1].map(t => (
          <line key={t} x1={M.l} x2={W - M.r}
                y1={H - M.b - t * (H - M.t - M.b)} y2={H - M.b - t * (H - M.t - M.b)} className="grid" />
        ))}
        {series.map((s, i) => (
          <rect key={s.gen} x={xs[i] - bw / 2} y={H - M.b - s.passRate * (H - M.t - M.b)}
                width={bw} height={s.passRate * (H - M.t - M.b)} className="pass-bar" rx={2}>
            <title>第 {s.gen} 代 · {s.n} 因子 · 通过率 {(s.passRate * 100).toFixed(0)}%</title>
          </rect>
        ))}
        {series.some(s => s.ic !== null) && (
          <polyline className="trend-ic"
            points={series.map((s, i) => s.ic === null ? null : `${xs[i]},${yIc(s.ic)}`).filter(Boolean).join(" ")} />
        )}
        {series.some(s => s.icir !== null) && (
          <polyline className="trend-icir"
            points={series.map((s, i) => s.icir === null ? null : `${xs[i]},${yIcir(s.icir)}`).filter(Boolean).join(" ")} />
        )}
        {series.map((s, i) => (
          <g key={s.gen}>
            {s.ic !== null && <circle cx={xs[i]} cy={yIc(s.ic)} r={3} className="trend-ic-dot" />}
            {s.icir !== null && <circle cx={xs[i]} cy={yIcir(s.icir)} r={3} className="trend-icir-dot" />}
            <text x={xs[i]} y={H - M.b + 16} className="tick" textAnchor="middle">G{s.gen}</text>
          </g>
        ))}
        <text x={M.l - 6} y={M.t + 4} className="tick" textAnchor="end">IC</text>
        <text x={W - M.r + 6} y={M.t + 4} className="tick">ICIR</text>
      </svg>
      <div className="legend">
        <li><i className="sw ic" />|IC| 中位</li>
        <li><i className="sw icir" />|ICIR| 中位</li>
        <li><i className="sw pass" />通过率</li>
      </div>
    </figure>
  );
}
