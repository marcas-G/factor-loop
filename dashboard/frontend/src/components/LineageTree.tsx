import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import type { Factor, LineageBranch, LineageEdge } from "../types";
import { STATUS_COLORS, STATUS_LABELS } from "../charts/colors";
import {
  ancestorPath, buildTree, layoutTree,
  NODE_W, NODE_H, ROW_UNIT,
} from "../lib/lineage";

interface Props {
  factors: Factor[];
  edges: LineageEdge[];
  branches: LineageBranch[];
  branch: string;
  onBranchChange: (b: string) => void;
  selected: string | null;
  onSelect: (xname: string | null) => void;
}

/** Default collapse heuristic (recomputed per branch, root always expanded):
 *  collapse a non-root node when it has >= COLLAPSE_FANOUT direct children
 *  (the fanout-12 node) OR its subtree spans >= COLLAPSE_SUBTREE nodes.
 *  On the real data the 44-node branch is a 3/5/7 fanout spine that never
 *  trips the fanout rule alone — the subtree rule is what rolls up its
 *  35- and 24-node sub-branches, leaving ~10 visible nodes / depth <= 4. */
const COLLAPSE_FANOUT = 8;
const COLLAPSE_SUBTREE = 8;

export function LineageTree({
  factors, edges, branches, branch, onBranchChange, selected, onSelect,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [t, setT] = useState<ZoomTransform>(zoomIdentity);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [hoverPath, setHoverPath] = useState<Set<string> | null>(null);

  const parentOf = useMemo(
    () => new Map(edges.map(e => [e.child_xname, e.parent_xname])),
    [edges],
  );

  const tree = useMemo(
    () => buildTree(factors, edges, branch),
    [factors, edges, branch],
  );

  // Default collapse: recompute on branch change (and first mount) only —
  // not on data refresh, which would wipe the user's manual unfold/fold.
  // Root nodes stay expanded so the first two levels are always visible.
  const lastBranch = useRef<string | null>(null);
  useEffect(() => {
    if (lastBranch.current === branch) return;
    lastBranch.current = branch;
    const next = new Set<string>();
    for (const n of tree.byName.values()) {
      if (n.children.length === 0) continue;
      if (tree.roots.some(r => r.xname === n.xname)) continue;
      if (n.children.length >= COLLAPSE_FANOUT || n.subtreeCount >= COLLAPSE_SUBTREE) {
        next.add(n.xname);
      }
    }
    setCollapsed(next);
  }, [branch, tree]);

  const layout = useMemo(
    () => layoutTree(tree.roots, collapsed, edges),
    [tree.roots, collapsed, edges],
  );

  const fit = useCallback(() => {
    const svg = svgRef.current;
    if (!svg || !zoomRef.current || !layout.nodes.length) return;
    const cw = svg.clientWidth || 1, ch = svg.clientHeight || 1;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of layout.nodes) {
      const ypx = n.y * ROW_UNIT;
      minX = Math.min(minX, n.x - NODE_W / 2);
      maxX = Math.max(maxX, n.x + NODE_W / 2);
      minY = Math.min(minY, ypx - NODE_H / 2);
      maxY = Math.max(maxY, ypx + NODE_H / 2);
    }
    const k = Math.min(1.2, Math.min(cw / (maxX - minX + 80), ch / (maxY - minY + 40)));
    const tx = cw / 2 - k * (minX + maxX) / 2;
    const ty = ch / 2 - k * (minY + maxY) / 2;
    select(svg).call(zoomRef.current.transform, zoomIdentity.translate(tx, ty).scale(k));
  }, [layout.nodes]);

  // d3-zoom wiring
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const zb = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 3])
      .on("zoom", ev => setT(ev.transform));
    zoomRef.current = zb;
    select(svg).call(zb).on("dblclick.zoom", null);
    return () => { select(svg).on(".zoom", null); };
  }, []);

  // fit on mount and on branch / layout change
  useEffect(() => {
    const id = requestAnimationFrame(() => fit());
    return () => cancelAnimationFrame(id);
  }, [fit]);

  const toggle = (xname: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(xname)) next.delete(xname); else next.add(xname);
      return next;
    });
  };

  const runSearch = () => {
    const q = query.trim().toLowerCase();
    if (!q) return;
    const hit = factors.find(f => f.xname.toLowerCase().includes(q));
    if (!hit) return;
    const path = ancestorPath(hit.xname, parentOf);
    setCollapsed(prev => {
      const next = new Set(prev);
      for (const n of path) next.delete(n);
      return next;
    });
    onSelect(hit.xname);
    requestAnimationFrame(() => requestAnimationFrame(() => fit()));
  };

  const sortedBranches = useMemo(
    () => [...branches].sort((a, b) => b.member_count - a.member_count),
    [branches],
  );

  const hasChildren = (xname: string) =>
    (tree.byName.get(xname)?.children.length ?? 0) > 0;

  /** Ancestors of the hovered node + its direct children, so both the path
   *  up and the edges down to immediate children light up on hover. */
  const hoverSetFor = (xname: string): Set<string> => {
    const s = new Set(ancestorPath(xname, parentOf));
    for (const c of tree.byName.get(xname)?.children ?? []) s.add(c.xname);
    return s;
  };

  const edgePath = (fromX: number, fromY: number, toX: number, toY: number) => {
    const midX = (fromX + toX) / 2;
    return `M${fromX},${fromY} C${midX},${fromY} ${midX},${toY} ${toX},${toY}`;
  };

  const hlSet = hoverPath;

  return (
    <section className="chart-box lineage-box">
      <div className="lineage-head">
        <figcaption>血缘图谱</figcaption>
        <div className="lineage-controls">
          <select value={branch} onChange={e => onBranchChange(e.target.value)}>
            <option value="all">全部分支</option>
            {sortedBranches.map(b => (
              <option key={b.root_xname} value={b.root_xname}>
                {shortLabel(b.root_xname)} ({b.member_count})
              </option>
            ))}
          </select>
          <input value={query} placeholder="搜索 xname"
                 onChange={e => setQuery(e.target.value)}
                 onKeyDown={e => { if (e.key === "Enter") runSearch(); }} />
          <button onClick={runSearch}>定位</button>
          <button onClick={() => fit()}>适应视图</button>
        </div>
      </div>
      <div className="lineage-stage">
        <svg ref={svgRef} className="lineage-svg" onClick={() => onSelect(null)}>
          <g transform={`translate(${t.x},${t.y}) scale(${t.k})`}>
            {layout.edges.map((e, i) => {
              const y1 = e.from.y * ROW_UNIT, y2 = e.to.y * ROW_UNIT;
              const onPath = hlSet?.has(e.from.node.xname) && hlSet?.has(e.to.node.xname);
              return (
                <path key={i}
                      className={[
                        "ledge",
                        e.outcome === "improved" ? "up" : "",
                        e.outcome === "declined" ? "down" : "",
                        e.operator ? "op" : "",
                        onPath ? "hl" : "",
                      ].filter(Boolean).join(" ")}
                      d={edgePath(e.from.x + NODE_W / 2, y1, e.to.x - NODE_W / 2, y2)}>
                  <title>{e.operator ? `${e.operator} · ${e.outcome ?? ""}` : (e.outcome ?? "")}</title>
                </path>
              );
            })}
            {layout.nodes.map(n => {
              const ypx = n.y * ROW_UNIT;
              const name = n.node.xname;
              const inPath = hlSet?.has(name) ?? false;
              return (
                <g key={name}
                   className={[
                     "lnode",
                     selected === name ? "selected" : "",
                     inPath ? "hl" : "",
                   ].filter(Boolean).join(" ")}
                   role="button" tabIndex={0} aria-label={name}
                   transform={`translate(${n.x},${ypx})`}
                   onClick={ev => { ev.stopPropagation(); onSelect(name); }}
                   onKeyDown={ev => {
                     if (ev.key === "Enter" || ev.key === " ") {
                       ev.stopPropagation();
                       onSelect(name);
                     }
                   }}
                   onPointerEnter={() => setHoverPath(hoverSetFor(name))}
                   onPointerLeave={() => setHoverPath(null)}>
                  <title>{name}</title>
                  <rect x={-NODE_W / 2} y={-NODE_H / 2} width={NODE_W} height={NODE_H} rx={8}
                        stroke={STATUS_COLORS[n.node.status] ?? "#33425c"} />
                  <circle cx={-NODE_W / 2 + 10} cy={0} r={3}
                          fill={STATUS_COLORS[n.node.status] ?? "#33425c"} />
                  <text x={12} y={3.5}>{n.node.label}</text>
                  <text className="ln-icir" x={NODE_W / 2 - 8} y={3.5} textAnchor="end">
                    {n.node.icir === null ? "—" : `ICIR ${n.node.icir.toFixed(1)}`}
                  </text>
                  {collapsed.has(name) && n.node.subtreeCount > 1 && (
                    <g className="collapse-badge"
                       transform={`translate(${NODE_W / 2 + 4},${-NODE_H / 2 - 9})`}
                       onClick={ev => {
                         ev.stopPropagation();
                         if (hasChildren(name)) toggle(name);
                       }}>
                      <rect x={0} y={-8} width={30} height={16} rx={5} />
                      <text x={15} y={4} textAnchor="middle">+{n.node.subtreeCount - 1}</text>
                    </g>
                  )}
                  {hasChildren(name) && !collapsed.has(name) && (
                    <g className="collapse-badge collapse-open"
                       transform={`translate(${NODE_W / 2 + 4},${-NODE_H / 2 - 9})`}
                       onClick={ev => { ev.stopPropagation(); toggle(name); }}>
                      <rect x={0} y={-8} width={16} height={16} rx={5} />
                      <text x={8} y={4} textAnchor="middle">−</text>
                    </g>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
        {!layout.nodes.length && <div className="lineage-empty">该分支无节点</div>}
      </div>
      <div className="lineage-legend">
        {Object.entries(STATUS_COLORS).map(([k, c]) => (
          <span key={k}><i className="dot-swatch" style={{ background: c }} />{STATUS_LABELS[k] ?? k}</span>
        ))}
        <span><i className="sw solid" />迭代</span>
        <span><i className="sw dashed" />算子</span>
        <span><i className="sw up-line" />improved</span>
        <span><i className="sw down-line" />declined</span>
      </div>
    </section>
  );
}

function shortLabel(xname: string): string {
  return xname.length > 18 ? xname.slice(0, 17) + "…" : xname;
}
