import { useMemo, useState } from "react";
import type { Factor } from "../../types";
import { STATUS_COLORS } from "../../charts/colors";

interface Props {
  factors: Factor[];
  selected: string | null;
  onSelect: (xname: string) => void;
}

const W = 720, H = 355, M = { l: 48, r: 14, t: 14, b: 30 };

interface P { x: number; y: number; color: string; glow: boolean; name: string;
             ic: number | null; r2: number | null; res: number | null }

export function Scatter({ factors, selected, onSelect }: Props) {
  const pts = useMemo<P[]>(() => factors
    .filter(f => f.latest_r2_x != null && f.latest_icir != null)
    .map(f => ({
      x: f.latest_r2_x as number, y: Math.abs(f.latest_icir as number),
      color: STATUS_COLORS[f.status] ?? "#5d7089", glow: f.gate_pass, name: f.xname,
      ic: f.latest_ic, r2: f.latest_r2_x, res: f.latest_res_ic,
    })), [factors]);
  const [hover, setHover] = useState<number | null>(null);

  if (!pts.length) return (
    <figure className="chart-box">
      <figcaption>冗余度 × 预测强度</figcaption>
      <p className="empty">无数据</p>
    </figure>
  );

  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  const xMax = Math.max(...xs) * 1.1 || 1, yMax = Math.max(...ys) * 1.1 || 1;
  const med = (a: number[]) => a.slice().sort((m, n) => m - n)[Math.floor(a.length / 2)];
  const sx = (v: number) => M.l + (v / xMax) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - (v / yMax) * (H - M.t - M.b);
  const ticks = (max: number) => [0.25, 0.5, 0.75, 1].map(t => max * t);
  const hovered = hover !== null ? pts[hover] : null;

  return (
    <figure className="chart-box scatter">
      <figcaption>冗余度 × 预测强度</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`}
           onPointerMove={e => {
             const box = e.currentTarget.getBoundingClientRect();
             const mx = (e.clientX - box.left) / box.width * W;
             const my = (e.clientY - box.top) / box.height * H;
             let best: number | null = null, bd = 12;
             for (let i = 0; i < pts.length; i++) {
               const p = pts[i];
               const d = Math.hypot(sx(p.x) - mx, sy(p.y) - my);
               if (d < bd) { bd = d; best = i; }
             }
             setHover(best);
           }}
           onPointerLeave={() => setHover(null)}>
        {ticks(yMax).map(t => (
          <g key={`y${t}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} className="grid" />
            <text x={M.l - 6} y={sy(t) + 4} className="tick" textAnchor="end">{t.toFixed(1)}</text>
          </g>
        ))}
        {ticks(xMax).map(t => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={M.t} y2={H - M.b} className="grid" />
            <text x={sx(t)} y={H - M.b + 16} className="tick" textAnchor="middle">{t.toFixed(2)}</text>
          </g>
        ))}
        <line x1={sx(med(xs))} x2={sx(med(xs))} y1={M.t} y2={H - M.b} className="median" />
        <line x1={M.l} x2={W - M.r} y1={sy(med(ys))} y2={sy(med(ys))} className="median" />
        <text x={W - M.r} y={H - 6} className="tick" textAnchor="end">R² →</text>
        <text x={M.l - 36} y={M.t + 4} className="tick">|ICIR| ↑</text>
        {hovered && (
          <line x1={M.l} x2={W - M.r} y1={sy(hovered.y)} y2={sy(hovered.y)} className="crosshair" />
        )}
        {hovered && (
          <line x1={sx(hovered.x)} x2={sx(hovered.x)} y1={M.t} y2={H - M.b} className="crosshair" />
        )}
        {pts.map((p, i) => (
          <g key={p.name} className="dot-wrap"
             style={{ transform: `translate(${sx(p.x).toFixed(1)}px, ${sy(p.y).toFixed(1)}px)` }}
             onClick={() => onSelect(p.name)}>
            <circle r={p.name === selected ? 6 : 4} fill={p.color}
                    className={`dot${p.glow ? " glow" : ""}${hover === i ? " hot" : ""}`} />
            {(hover === i || p.name === selected) && (
              <text y={-10} className="dot-label" textAnchor="middle">{p.name.slice(0, 28)}</text>
            )}
          </g>
        ))}
      </svg>
      {hovered && (
        <div className="hover-card">
          <b>{hovered.name}</b>
          <span>IC {hovered.ic?.toFixed(3) ?? "—"}</span>
          <span>|ICIR| {hovered.y.toFixed(2)}</span>
          <span>R² {hovered.r2?.toFixed(2) ?? "—"}</span>
          <span>残差IC {hovered.res?.toFixed(3) ?? "—"}</span>
        </div>
      )}
    </figure>
  );
}
