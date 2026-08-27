"use strict";
const DATA = window.FACTOR_DASHBOARD_DATA;
const byName = new Map(DATA.factors.map(f => [f.xname, f]));
const evalsByName = new Map();
const iterationsByName = new Map();
const lessonsByName = new Map();
for (const ev of DATA.evaluations) {
  if (!evalsByName.has(ev.factor_xname)) evalsByName.set(ev.factor_xname, []);
  evalsByName.get(ev.factor_xname).push(ev);
}
for (const it of DATA.iterations) {
  for (const name of new Set([it.from_xname, it.to_xname])) {
    if (!iterationsByName.has(name)) iterationsByName.set(name, []);
    iterationsByName.get(name).push(it);
  }
}
for (const lesson of DATA.lessons) {
  if (!lessonsByName.has(lesson.factor_xname)) lessonsByName.set(lesson.factor_xname, []);
  lessonsByName.get(lesson.factor_xname).push(lesson);
}
const state = {
  query: "",
  status: "all",
  tag: "all",
  sort: null,
  selected: null
};
const STATUS_LABELS = {
  evaluated: "已评估",
  dead_end: "放弃",
  draft: "草稿",
  submitted: "已提交",
  failed: "失败"
};
const STATUS_COLORS = {
  evaluated: "#34d399",
  dead_end: "#f87171",
  draft: "#22d3ee",
  submitted: "#fbbf24",
  failed: "#c084fc"
};
const VERDICT_LABELS = {
  pass: "通过",
  fail: "失败"
};
function esc(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function conclusionOf(f) {
  if (f.status === "evaluated") return "pass";
  if (f.status === "dead_end") return "fail";
  return f.verdict || "";
}
function verdictLabel(f) {
  return conclusionOf(f) ? (VERDICT_LABELS[conclusionOf(f)] || conclusionOf(f)) : "未评估";
}
function verdictBadge(f) {
  const conclusion = conclusionOf(f);
  if (conclusion === "pass" || conclusion === "fail") {
    return `<span class="badge verdict-${esc(conclusion)}">${esc(VERDICT_LABELS[conclusion] || conclusion)}</span>`;
  }
  return `<span class="badge ${esc(f.status)}">${esc(STATUS_LABELS[f.status] || f.status)}</span>`;
}
function fmt(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 10000) return n.toLocaleString("zh-CN", {maximumFractionDigits: 1});
  return n.toFixed(digits);
}
function pct(value) { return value === null || value === undefined ? "—" : fmt(value * 100, 2) + "%"; }
function cls(value) { return value > 0 ? "pos" : value < 0 ? "neg" : ""; }
function shortTime(value) {
  if (!value) return "—";
  const d = new Date(value.includes("T") ? value + (value.endsWith("Z") ? "" : "Z") : value.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return esc(value);
  return d.toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});
}
function fullTime(value) {
  if (!value) return "—";
  return esc(value);
}
function uniqueStatuses() {
  return [...new Set(DATA.factors.map(f => f.status))].sort();
}
function uniqueTags() {
  const counts = new Map();
  for (const f of DATA.factors) for (const t of f.tags || []) {
    counts.set(t.name, (counts.get(t.name) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
function searchFactor(factor) {
  if (state.status !== "all" && factor.status !== state.status) return false;
  if (state.tag !== "all" && !(factor.tags || []).some(t => t.name === state.tag)) return false;
  if (!state.query) return true;
  const q = state.query.toLowerCase();
  return [factor.xname, factor.class_name, factor.formula_text, factor.intuition,
          factor.status, factor.verdict, ...(factor.tags || []).map(t => t.name)]
    .filter(Boolean).some(v => String(v).toLowerCase().includes(q));
}
function useInlineDetails() {
  return !window.matchMedia("(max-width: 780px)").matches;
}
function toggleSelected(xname) {
  state.selected = state.selected === xname ? null : xname;
  render();
}
function compareBySort(a, b, sort) {
  const key = sort.key;
  if (["xname", "status", "last_updated_ts"].includes(key)) {
    const av = String(a[key] || "").toLowerCase();
    const bv = String(b[key] || "").toLowerCase();
    const cmp = av.localeCompare(bv);
    return (cmp || 0) * sort.dir;
  }
  if (key === "verdict") {
    const cmp = conclusionOf(a).localeCompare(conclusionOf(b));
    return (cmp || 0) * sort.dir;
  }
  const av = a[key] === null || a[key] === undefined || a[key] === "" ? null : Number(a[key]);
  const bv = b[key] === null || b[key] === undefined || b[key] === "" ? null : Number(b[key]);
  if (av === null && bv === null) return 0;
  if (av === null) return 1;
  if (bv === null) return -1;
  return (av - bv) * sort.dir;
}
function currentFactors() {
  const rows = DATA.factors.filter(searchFactor);
  if (state.sort) rows.sort((a, b) => compareBySort(a, b, state.sort) || String(a.xname).localeCompare(String(b.xname)));
  return rows;
}
function median(values) {
  const nums = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!nums.length) return null;
  const mid = Math.floor(nums.length / 2);
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
}
function sparkline(values, w = 150, h = 34) {
  const vs = values.filter(v => v !== null && v !== undefined && Number.isFinite(+v));
  if (vs.length < 2) return "";
  const min = Math.min(...vs), max = Math.max(...vs);
  const span = (max - min) || 1;
  const pts = vs.map((v, i) => [
    (i / (vs.length - 1) * (w - 6) + 3).toFixed(1),
    (h - 3 - (+v - min) / span * (h - 6)).toFixed(1)
  ]);
  const rising = +vs[vs.length - 1] >= +vs[0];
  const color = rising ? "var(--up)" : "var(--down)";
  const [lx, ly] = pts[pts.length - 1];
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
    <polyline points="${pts.map(p => p.join(",")).join(" ")}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/>
    <circle cx="${lx}" cy="${ly}" r="2.2" fill="${color}"/></svg>`;
}
function growthSeries(key) {
  const ts = DATA.factors.map(f => +parseTs(f[key]) || 0).sort((a, b) => a - b);
  return ts.map((_, i) => i + 1).slice(-12);
}
function distSeries(key) {
  return DATA.factors
    .map(f => +f[key])
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
}
function evalBucketSeries() {
  const day = 86400_000;
  const now = Date.now();
  const counts = new Array(12).fill(0);
  for (const e of DATA.evaluations || []) {
    const t = +parseTs(e.ts);
    if (!Number.isFinite(t)) continue;
    const age = Math.floor((now - t) / day);
    if (age >= 0 && age < 12) counts[11 - age]++;
  }
  return counts;
}
function weekDelta(key) {
  const week = 7 * 86400_000;
  const now = Date.now();
  let recent = 0, prior = 0;
  for (const f of DATA.factors) {
    const t = +parseTs(f[key]);
    if (!Number.isFinite(t)) continue;
    if (now - t < week) recent++;
    else if (now - t < 2 * week) prior++;
  }
  return { recent, prior };
}
function deltaBadge(d) {
  if (!d || (d.recent === 0 && d.prior === 0)) return "";
  const cls = d.recent >= d.prior ? "up" : "down";
  const arrow = d.recent >= d.prior ? "▲" : "▼";
  return `<span class="metric-delta ${cls}">${arrow} ${d.recent}</span>`;
}
function renderMetrics() {
  const fs = DATA.factors;
  const passed = fs.filter(f => f.status === "evaluated");
  const failed = fs.filter(f => f.status === "dead_end");
  const icir = fs.map(f => f.latest_icir === null ? null : Math.abs(f.latest_icir));
  const redundant = fs.filter(f => f.latest_r2_x !== null).map(f => f.latest_r2_x);
  const significant = DATA.evaluations.filter(e => e.significant);
  const cards = [
    { label: "因子总数", value: fs.length, note: `${passed.length + failed.length} 个已评估`,
      spark: sparkline(growthSeries("created_ts")), delta: deltaBadge(weekDelta("created_ts")) },
    { label: "通过", value: passed.length, note: `${failed.length} 个失败`,
      spark: sparkline(growthSeries("created_ts").map((_, i) => i)), delta: "" },
    { label: "中位 |ICIR|", value: fmt(median(icir), 2), note: `${fs.filter(f => f.latest_icir !== null).length} 个有 ICIR`,
      spark: sparkline(distSeries("latest_icir").map(Math.abs)), delta: "" },
    { label: "中位库内 R²", value: pct(median(redundant)), note: `${redundant.length} 个有冗余检测`,
      spark: sparkline(distSeries("latest_r2_x")), delta: "" },
    { label: "显著评估", value: significant.length, note: `${DATA.evaluations.length} 条评估快照`,
      spark: sparkline(evalBucketSeries()), delta: "" }
  ];
  document.getElementById("metricCards").innerHTML = cards.map(c =>
    `<div class="metric"><dt>${esc(c.label)}</dt>
     <dd class="metric-value">${esc(c.value)}${c.delta}</dd>
     ${c.spark ? `<div class="metric-spark">${c.spark}</div>` : ""}
     <small style="color:var(--ink-faint);font-size:10.5px">${esc(c.note)}</small></div>`
  ).join("");
}
function renderScatter() {
  const svg = document.getElementById("scatterChart");
  const points = DATA.factors.filter(f => f.latest_r2_x !== null && f.latest_icir !== null)
    .map(f => ({f, x: Math.max(0, Math.min(1, f.latest_r2_x)), y: Math.abs(f.latest_icir)}));
  const w = 720, h = 355, left = 54, right = 22, top = 18, bottom = 48;
  const maxY = Math.max(1, ...points.map(p => p.y));
  const niceY = maxY <= 3 ? 3 : maxY <= 6 ? 6 : Math.ceil(maxY / 2) * 2;
  const xScale = x => left + x * (w-left-right);
  const yScale = y => h-bottom - (y/niceY) * (h-top-bottom);
  let grid = "";
  for (let i=0; i<=4; i++) {
    const yv = niceY*i/4, y = yScale(yv);
    grid += `<line x1="${left}" y1="${y}" x2="${w-right}" y2="${y}" stroke="var(--border)"/><text x="${left-8}" y="${y+4}" text-anchor="end" font-size="11" fill="var(--ink-faint)" font-family="var(--mono)">${yv.toFixed(yv<10?1:0)}</text>`;
  }
  for (let i=0; i<=5; i++) {
    const xv = i/5, x = xScale(xv);
    grid += `<line x1="${x}" y1="${top}" x2="${x}" y2="${h-bottom}" stroke="var(--border)" opacity=".6"/><text x="${x}" y="${h-bottom+20}" text-anchor="middle" font-size="11" fill="var(--ink-faint)" font-family="var(--mono)">${(xv*100).toFixed(0)}%</text>`;
  }
  const medX = median(points.map(p => p.x));
  const medY = median(points.map(p => p.y));
  let refs = "";
  if (medX !== null) refs += `<line x1="${xScale(medX)}" y1="${top}" x2="${xScale(medX)}" y2="${h-bottom}" stroke="var(--warn)" stroke-width="1" stroke-dasharray="3,4" opacity=".55"/>`;
  if (medY !== null) refs += `<line x1="${left}" y1="${yScale(medY)}" x2="${w-right}" y2="${yScale(medY)}" stroke="var(--warn)" stroke-width="1" stroke-dasharray="3,4" opacity=".55"/>`;
  const circles = points.map(p => {
    const selected = p.f.xname === state.selected;
    return `<circle data-xname="${esc(p.f.xname)}" class="point" cx="${xScale(p.x)}" cy="${yScale(p.y)}" r="${selected ? 6.5 : 4.5}" fill="${STATUS_COLORS[p.f.status] || "#64748b"}" fill-opacity=".85" stroke="${selected ? "var(--accent)" : "#0a0e14"}" stroke-width="${selected ? 2 : 1}"><title>${esc(p.f.xname)}\nR² ${fmt(p.x,3)} / |ICIR| ${fmt(p.y,2)}</title></circle>`;
  }).join("");
  svg.innerHTML = `${grid}${refs}
    <line x1="${left}" y1="${h-bottom}" x2="${w-right}" y2="${h-bottom}" stroke="var(--border-hover)"/>
    <line x1="${left}" y1="${top}" x2="${left}" y2="${h-bottom}" stroke="var(--border-hover)"/>
    <text x="${(left+w-right)/2}" y="${h-9}" text-anchor="middle" font-size="12" fill="var(--ink-faint)">库内解释方差 R²</text>
    <text x="15" y="${(top+h-bottom)/2}" text-anchor="middle" font-size="12" fill="var(--ink-faint)" transform="rotate(-90 15 ${(top+h-bottom)/2})">|ICIR|</text>
    ${circles}`;
  svg.querySelectorAll("circle.point").forEach(c => c.addEventListener("click", () => {
    state.selected = c.dataset.xname; render(); }));
}
function renderStatusChart() {
  const svg = document.getElementById("statusChart");
  const counts = new Map();
  for (const f of DATA.factors) counts.set(f.status, (counts.get(f.status) || 0) + 1);
  const entries = [...counts.entries()].sort((a,b) => b[1]-a[1]);
  const total = entries.reduce((s, e) => s + e[1], 0) || 1;
  const w = 320, pad = 14, barY = 22, barH = 26;
  const legendY0 = barY + barH + 22;
  const rowH = 24;
  const h = Math.max(160, legendY0 + entries.length * rowH + 8);
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  let x = pad;
  const segs = entries.map(([status, count]) => {
    const segW = Math.max(0, (count / total) * (w - 2 * pad));
    const el = `<rect x="${x.toFixed(1)}" y="${barY}" width="${segW.toFixed(1)}" height="${barH}" fill="${STATUS_COLORS[status] || "#64748b"}" fill-opacity=".88"><title>${esc(STATUS_LABELS[status] || status)}: ${count} (${(count/total*100).toFixed(0)}%)</title></rect>`;
    x += segW;
    return el;
  }).join("");
  const legend = entries.map(([status, count], i) => {
    const ly = legendY0 + i * rowH;
    return `<circle cx="${pad+4}" cy="${ly-4}" r="4" fill="${STATUS_COLORS[status] || "#64748b"}"/>
      <text x="${pad+14}" y="${ly}" font-size="11" fill="var(--ink-dim)">${esc(STATUS_LABELS[status] || status)}</text>
      <text x="${w-pad}" y="${ly}" text-anchor="end" font-size="11" fill="var(--ink)" font-family="var(--mono)">${count}</text>`;
  }).join("");
  svg.innerHTML = `${segs}${legend}`;
}
const graphState = {
  branch: "all",
  cache: null,
  view: null,
  dragging: false,
  lastX: 0,
  lastY: 0
};
function shortFactorName(name) {
  return String(name || "").length > 20 ? String(name).slice(0, 18) + "…" : String(name || "—");
}
function buildLineageModel(branch) {
  const allNodes = DATA.factors.map(f => ({
    xname: f.xname,
    label: f.xname,
    status: f.status
  }));
  const byName = new Map(allNodes.map(n => [n.xname, n]));
  const adj = new Map();
  const rev = new Map();
  for (const e of DATA.lineage_edges || []) {
    if (!byName.has(e.parent_xname) || !byName.has(e.child_xname)) continue;
    if (!adj.has(e.parent_xname)) adj.set(e.parent_xname, []);
    adj.get(e.parent_xname).push(e.child_xname);
    rev.set(e.child_xname, e.parent_xname);
  }
  const roots = allNodes.filter(n => !rev.has(n.xname));
  const rootOf = new Map();
  for (const root of roots) {
    const queue = [root.xname];
    if (!rootOf.has(root.xname)) rootOf.set(root.xname, root.xname);
    while (queue.length) {
      const cur = queue.shift();
      for (const child of adj.get(cur) || []) {
        if (!rootOf.has(child)) {
          rootOf.set(child, root.xname);
          queue.push(child);
        }
      }
    }
  }
  for (const n of allNodes) {
    if (!rootOf.has(n.xname)) rootOf.set(n.xname, n.xname);
  }
  const nodes = allNodes.filter(n => branch === "all" || rootOf.get(n.xname) === branch);
  const nodeSet = new Set(nodes.map(n => n.xname));
  const edges = (DATA.lineage_edges || []).filter(e =>
    nodeSet.has(e.parent_xname) && nodeSet.has(e.child_xname)
  );
  return {nodes, edges, rootOf};
}
function computeLineageLayout(model) {
  const nodes = model.nodes.map(n => ({
    ...n,
    x: 0, y: 0, vx: 0, vy: 0,
    w: Math.min(172, Math.max(104, String(n.label).length * 6.1 + 18)),
    h: 34,
    root: model.rootOf.get(n.xname) || n.xname
  }));
  const byName = new Map(nodes.map(n => [n.xname, n]));
  const edges = model.edges.filter(e => byName.has(e.parent_xname) && byName.has(e.child_xname));
  const roots = [...new Set(nodes.map(n => n.root))];
  const W = 1600, H = 1000;
  const centers = new Map();
  roots.forEach((root, i) => {
    const angle = (i / Math.max(1, roots.length)) * 2 * Math.PI;
    const radius = Math.min(W, H) * 0.32;
    centers.set(root, {
      x: W / 2 + Math.cos(angle) * radius,
      y: H / 2 + Math.sin(angle) * radius * 0.7
    });
  });
  let seed = 20260820;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  nodes.forEach(n => {
    const c = centers.get(n.root) || {x: W / 2, y: H / 2};
    n.x = c.x + (rnd() - 0.5) * 420;
    n.y = c.y + (rnd() - 0.5) * 420;
  });
  const repulsion = 290000;
  const edgeSpring = 0.045;
  const rootSpring = 0.006;
  const gravity = 0.0015;
  for (let iter = 0; iter < 520; iter++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const d2 = dx * dx + dy * dy + 1;
        const d = Math.sqrt(d2);
        const force = repulsion / d2;
        const fx = (dx / d) * force, fy = (dy / d) * force;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }
    }
    for (const e of edges) {
      const a = byName.get(e.parent_xname), b = byName.get(e.child_xname);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const fx = (dx / d) * d * edgeSpring, fy = (dy / d) * d * edgeSpring;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }
    for (const n of nodes) {
      const c = centers.get(n.root) || {x: W / 2, y: H / 2};
      n.vx += (c.x - n.x) * rootSpring;
      n.vy += (c.y - n.y) * rootSpring;
      n.vx += (W / 2 - n.x) * gravity;
      n.vy += (H / 2 - n.y) * gravity;
      const maxV = 9;
      n.vx = Math.max(-maxV, Math.min(maxV, n.vx));
      n.vy = Math.max(-maxV, Math.min(maxV, n.vy));
      n.x += n.vx;
      n.y += n.vy;
      n.vx *= 0.84;
      n.vy *= 0.84;
    }
  }
  return {nodes, edges};
}
function getLineageLayout() {
  if (!graphState.cache || graphState.cache.branch !== graphState.branch) {
    graphState.cache = {
      branch: graphState.branch,
      layout: computeLineageLayout(buildLineageModel(graphState.branch))
    };
  }
  return graphState.cache.layout;
}
function fitGraphView() {
  const layout = getLineageLayout();
  if (!layout.nodes.length) return;
  const minX = Math.min(...layout.nodes.map(n => n.x - n.w / 2)) - 120;
  const minY = Math.min(...layout.nodes.map(n => n.y - n.h / 2)) - 90;
  const maxX = Math.max(...layout.nodes.map(n => n.x + n.w / 2)) + 120;
  const maxY = Math.max(...layout.nodes.map(n => n.y + n.h / 2)) + 90;
  graphState.view = {
    branch: graphState.branch,
    x: minX,
    y: minY,
    w: Math.max(960, maxX - minX),
    h: Math.max(560, maxY - minY)
  };
}
function applyGraphView(svg) {
  if (!graphState.view || graphState.view.branch !== graphState.branch) fitGraphView();
  svg.setAttribute("viewBox",
    `${graphState.view.x} ${graphState.view.y} ${graphState.view.w} ${graphState.view.h}`);
}
function lineageEdgePath(e, byId) {
  const p = byId.get(e.parent_xname), c = byId.get(e.child_xname);
  if (!p || !c) return "";
  const dx = c.x - p.x, dy = c.y - p.y;
  const d = Math.max(1, Math.hypot(dx, dy));
  const sx = p.x + (dx / d) * (p.w / 2 + 4);
  const sy = p.y + (dy / d) * (p.h / 2 + 4);
  const ex = c.x - (dx / d) * (c.w / 2 + 9);
  const ey = c.y - (dy / d) * (c.h / 2 + 9);
  const cls = (e.outcome === "improved" ? " improved" : e.outcome === "declined" ? " declined" : "")
    + (e.operator_name ? " operator-edge" : "");
  const title = e.operator_name ? `<title>算子: ${esc(e.operator_name)}</title>` : "";
  return `<line class="graph-edge${cls}" x1="${sx.toFixed(1)}" y1="${sy.toFixed(1)}" x2="${ex.toFixed(1)}" y2="${ey.toFixed(1)}">${title}</line>`;
}
function lineageNodeHtml(n) {
  const color = STATUS_COLORS[n.status] || "#64748b";
  const selected = state.selected === n.xname ? " selected" : "";
  const label = shortFactorName(n.label);
  return `<g class="graph-node${selected}" data-xname="${esc(n.xname)}" transform="translate(${n.x.toFixed(1)} ${n.y.toFixed(1)})" tabindex="0" role="button" aria-label="${esc(n.xname)}">
    <rect x="${(-n.w / 2).toFixed(1)}" y="${(-n.h / 2).toFixed(1)}" width="${n.w}" height="${n.h}" rx="6" fill="${color}18" stroke="${selected ? "#0f766e" : color}"></rect>
    <text x="0" y="-2" text-anchor="middle">${esc(label)}</text>
    <text class="node-status" x="0" y="12" text-anchor="middle">${esc(STATUS_LABELS[n.status] || n.status)}</text>
  </g>`;
}
function renderLineage() {
  const svg = document.getElementById("lineageChart");
  const empty = document.getElementById("lineageEmpty");
  const layout = getLineageLayout();
  empty.hidden = layout.nodes.length > 0;
  if (!layout.nodes.length) {
    svg.innerHTML = "";
    return;
  }
  applyGraphView(svg);
  const byId = new Map(layout.nodes.map(n => [n.xname, n]));
  svg.innerHTML = `
    <defs>
      <marker id="lineageArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="#8da0b3"></path>
      </marker>
    </defs>
    <g>${layout.edges.map(e => lineageEdgePath(e, byId)).join("")}</g>
    <g>${layout.nodes.map(lineageNodeHtml).join("")}</g>`;
  svg.querySelectorAll(".graph-node").forEach(g => {
    g.addEventListener("click", event => {
      event.stopPropagation();
      state.selected = g.dataset.xname;
      render();
    });
    g.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        state.selected = g.dataset.xname;
        render();
      }
    });
  });
  document.getElementById("lineageMeta").textContent =
    `${layout.nodes.length} 节点 · ${layout.edges.length} 边 · ${new Set(layout.nodes.map(n => n.root)).size} 分支`;
}
function fillLineageSelect() {
  const select = document.getElementById("lineageBranchFilter");
  const branches = (DATA.lineage_branches || []).slice();
  select.innerHTML = `<option value="all">全部分支 (${DATA.factors.length})</option>` +
    branches.map(b =>
      `<option value="${esc(b.root_xname)}">${esc(shortFactorName(b.root_xname))} · ${b.member_count} 因子</option>`
    ).join("");
  select.value = graphState.branch;
}
function onLineageWheel(event) {
  event.preventDefault();
  const svg = document.getElementById("lineageChart");
  const rect = svg.getBoundingClientRect();
  const px = (event.clientX - rect.left) / Math.max(1, rect.width);
  const py = (event.clientY - rect.top) / Math.max(1, rect.height);
  const factor = event.deltaY > 0 ? 1.18 : 0.85;
  const v = graphState.view;
  const nw = Math.min(14000, Math.max(420, v.w * factor));
  const nh = Math.min(12000, Math.max(360, v.h * factor));
  v.x += px * (v.w - nw);
  v.y += py * (v.h - nh);
  v.w = nw;
  v.h = nh;
  svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
}
function onLineagePointerDown(event) {
  if (event.target.closest && event.target.closest(".graph-node")) return;
  graphState.dragging = true;
  graphState.lastX = event.clientX;
  graphState.lastY = event.clientY;
  document.getElementById("lineageChart").classList.add("dragging");
  document.getElementById("lineageChart").setPointerCapture(event.pointerId);
}
function onLineagePointerMove(event) {
  if (!graphState.dragging || !graphState.view) return;
  const svg = document.getElementById("lineageChart");
  const rect = svg.getBoundingClientRect();
  graphState.view.x -= (event.clientX - graphState.lastX) * graphState.view.w / Math.max(1, rect.width);
  graphState.view.y -= (event.clientY - graphState.lastY) * graphState.view.h / Math.max(1, rect.height);
  graphState.lastX = event.clientX;
  graphState.lastY = event.clientY;
  svg.setAttribute("viewBox",
    `${graphState.view.x} ${graphState.view.y} ${graphState.view.w} ${graphState.view.h}`);
}
function onLineagePointerUp(event) {
  graphState.dragging = false;
  const svg = document.getElementById("lineageChart");
  svg.classList.remove("dragging");
  if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
}
function factorCell(f, open) {
  const tags = (f.tags || []).slice(0,3).map(t => `<span class="tag">${esc(t.name)}</span>`).join("");
  const chevron = open ? "▾" : "▸";
  return `<div class="factor-cell">
    <div class="factor-title"><button data-select="${esc(f.xname)}" type="button" title="${esc(f.xname)}"><span class="chevron" aria-hidden="true">${chevron}</span> ${esc(f.xname)}</button></div>
    <div class="factor-subtitle">${esc(f.class_name || "未分类")}</div>
    ${tags ? `<div class="tag-row">${tags}</div>` : ""}
  </div>`;
}
function sortBadge(key) {
  if (!state.sort || state.sort.key !== key) return "";
  return `<span class="sort-badge">${state.sort.dir > 0 ? "↑" : "↓"}</span>`;
}
function renderTable() {
  const rows = currentFactors();
  const inline = useInlineDetails();
  document.getElementById("resultCount").textContent = `${rows.length} / ${DATA.factors.length} 个因子`;
  document.getElementById("emptyMessage").hidden = rows.length > 0;
  document.getElementById("factorRows").innerHTML = rows.map(f => {
    const selected = f.xname === state.selected;
    const detailRow = inline && selected
      ? `<tr class="expanded-row"><td colspan="9">${inlineDetailHtml(f)}</td></tr>` : "";
    return `<tr data-xname="${esc(f.xname)}" class="${selected ? "selected" : ""}">
      <td>${factorCell(f, selected)}</td>
      <td>${verdictBadge(f)}</td>
      <td class="number ${cls(f.latest_ic)}">${fmt(f.latest_ic)}</td>
      <td class="number ${cls(f.latest_icir)}">${fmt(f.latest_icir, 2)}</td>
      <td class="number">${pct(f.latest_r2_x)}</td>
      <td class="number ${cls(f.latest_res_ic)}">${fmt(f.latest_res_ic)}</td>
      <td class="number ${cls(f.resic_ic_ratio)}">${pct(f.resic_ic_ratio)}</td>
      <td>${shortTime(f.last_updated_ts)}</td>
    </tr>${detailRow}`;
  }).join("");
  document.querySelectorAll("#factorRows tr[data-xname]").forEach(tr => tr.addEventListener("click", () => {
    toggleSelected(tr.dataset.xname);
  }));
  document.querySelectorAll("button[data-select]").forEach(btn => {
    btn.addEventListener("click", event => {
      event.stopPropagation(); toggleSelected(btn.dataset.select);
    });
  });
  document.querySelectorAll("[data-collapse]").forEach(btn => {
    btn.addEventListener("click", event => {
      event.stopPropagation(); state.selected = null; render();
    });
  });
  document.querySelectorAll(".sort-header").forEach(button => {
    button.innerHTML = `<span>${esc(button.dataset.label || button.dataset.key)}</span>${sortBadge(button.dataset.key)}`;
    button.title = "点击按此列排序；再次点击切换升降序";
  });
}
function detailMetric(label, value) {
  return `<div class="detail-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}
function detailBody(f) {
  const evals = evalsByName.get(f.xname) || [];
  const lessons = lessonsByName.get(f.xname) || [];
  const iterations = (iterationsByName.get(f.xname) || []).filter(i => i.change_note || i.reason);
  const hasIntuition = Boolean(f.intuition);
  const tagHtml = (f.tags || []).map(t => `<span class="tag" title="${esc(t.description || t.name)}">${esc(t.name)}</span>`).join("");
  const evalHtml = evals.length ? `<table class="detail-table"><thead><tr><th>时间</th><th>IC</th><th>ICIR</th><th>模式</th><th>显著</th></tr></thead><tbody>
    ${evals.slice(0,12).map(e => `<tr><td>${shortTime(e.ts)}</td><td class="${cls(e.ic_mean)}">${fmt(e.ic_mean)}</td><td class="${cls(e.icir)}">${fmt(e.icir,2)}</td><td>${esc(e.eval_mode || "—")}</td><td>${e.significant ? "是" : "否"}</td></tr>`).join("")}
    </tbody></table>` : `<p class="empty">暂无评估快照</p>`;
  const lessonHtml = lessons.length ? lessons.map(l => `
    <article class="lesson ${esc(l.type)}"><strong>${l.type === "success_pattern" ? "成功模式" : "放弃原因"}</strong><p>${esc(l.text)}</p></article>`).join("")
    : `<p class="empty">暂无实验结论</p>`;
  const iterationHtml = iterations.length ? `<table class="detail-table"><thead><tr><th>时间</th><th>迭代建议</th></tr></thead><tbody>
    ${iterations.slice(0,12).map(i => `<tr><td>${shortTime(i.ts)}</td><td>${esc(i.change_note || i.reason)}</td></tr>`).join("")}</tbody></table>`
    : `<p class="empty">暂无迭代记录</p>`;
  return `
    ${tagHtml ? `<div class="tag-row" style="margin-top:8px">${tagHtml}</div>` : ""}
    <div class="detail-grid">
      ${detailMetric("IC", fmt(f.latest_ic))}
      ${detailMetric("ICIR", fmt(f.latest_icir,2))}
      ${detailMetric("库内 R²", pct(f.latest_r2_x))}
      ${detailMetric("残差 IC", fmt(f.latest_res_ic))}
      ${detailMetric("残差IC/IC", pct(f.resic_ic_ratio))}
      ${detailMetric("Rank IC", fmt(f.latest_rank_ic))}
    </div>
    <div class="detail-section ${hasIntuition ? "" : "full"}"><h3>公式</h3><pre>${esc(f.formula_text || "未记录")}</pre></div>
    ${hasIntuition ? `<div class="detail-section"><h3>研究意图</h3><pre>${esc(f.intuition)}</pre></div>` : ""}
    <div class="detail-section"><h3>评估历史</h3>${evalHtml}</div>
    <div class="detail-section"><h3>迭代记录</h3>${iterationHtml}</div>
    <div class="detail-section full"><h3>实验结论</h3>${lessonHtml}</div>
    <div class="detail-section full"><h3>文件</h3><pre>${esc(f.file_path || "未记录")}</pre></div>`;
}
function inlineDetailHtml(f) {
  return `<div class="inline-detail">
    <div class="inline-detail-head">
      <div class="detail-title">
        <h2>${esc(f.xname)}</h2>
        <p>${esc(f.class_name || "未分类")} · ${esc(STATUS_LABELS[f.status] || f.status)} · 结论 ${esc(verdictLabel(f))} · 更新 ${fullTime(f.last_updated_ts)}</p>
      </div>
      <button class="icon-button" data-collapse="${esc(f.xname)}" type="button" title="收起详情" aria-label="收起详情">×</button>
    </div>
    ${detailBody(f)}
  </div>`;
}
function renderDetail() {
  const panel = document.getElementById("detailPanel");
  const f = state.selected ? byName.get(state.selected) : null;
  panel.classList.toggle("open", Boolean(f));
  document.body.classList.toggle("sheet-open", Boolean(f));
  panel.scrollTop = 0;
  if (!f) {
    panel.innerHTML = `<div class="placeholder"><div><strong>选择一个因子</strong><br>查看公式、评估历史、迭代建议和实验结论</div></div>`;
    return;
  }
  panel.innerHTML = `
    <div class="detail-top">
      <div class="detail-title">
        <h2>${esc(f.xname)}</h2>
        <p>${esc(f.class_name || "未分类")} · ${esc(STATUS_LABELS[f.status] || f.status)} · 结论 ${esc(verdictLabel(f))} · 更新 ${fullTime(f.last_updated_ts)}</p>
      </div>
      <button class="icon-button" id="closeDetail" type="button" title="关闭详情" aria-label="关闭详情">×</button>
    </div>
    ${detailBody(f)}`;
  document.getElementById("closeDetail").addEventListener("click", () => {
    state.selected = null; render();
  });
}
function fillSelects() {
  const status = document.getElementById("statusFilter");
  status.innerHTML = `<option value="all">全部状态</option>` + uniqueStatuses().map(s =>
    `<option value="${esc(s)}">${esc(STATUS_LABELS[s] || s)} (${DATA.factors.filter(f => f.status===s).length})</option>`).join("");
  status.value = state.status;
  const tags = document.getElementById("tagFilter");
  tags.innerHTML = `<option value="all">全部标签</option>` + uniqueTags().map(([name,count]) =>
    `<option value="${esc(name)}">${esc(name)} (${count})</option>`).join("");
  tags.value = state.tag;
}
function renderHeader() {
  document.getElementById("dbMeta").textContent =
    `${DATA.meta.dbPath} · 数据更新 ${DATA.meta.dbModifiedAt} · 快照 ${DATA.meta.generatedAt}`;
  document.getElementById("footerMeta").textContent =
    `静态快照 · 页面自包含，无需端口 · 重新执行生成命令后刷新页面即可更新`;
}
function csvCell(value) { return `"${String(value ?? "").replaceAll('"','""')}"`; }
function exportCsv() {
  const headers = ["xname","class_name","status","verdict","latest_ic","latest_icir","latest_r2_x","latest_res_ic","resic_ic_ratio","last_updated_ts"];
  const rows = currentFactors();
  const csv = [headers.join(","), ...rows.map(f => headers.map(h => csvCell(f[h])).join(","))].join("\n");
  const blob = new Blob(["\ufeff" + csv], {type: "text/csv;charset=utf-8"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `factor_dashboard_${DATA.meta.generatedAt.slice(0,10)}.csv`;
  link.click(); URL.revokeObjectURL(link.href);
}
function computeGenerations() {
  const parent = new Map();
  for (const e of DATA.lineage_edges || []) parent.set(e.child_xname, e.parent_xname);
  const memo = new Map();
  function gen(x) {
    if (!memo.has(x)) {
      memo.set(x, parent.has(x) ? gen(parent.get(x)) + 1 : 1);
    }
    return memo.get(x);
  }
  for (const f of DATA.factors) gen(f.xname);
  return gen;
}
function aggregateByGeneration() {
  const gen = computeGenerations();
  const buckets = new Map();
  for (const f of DATA.factors) {
    const g = gen(f.xname);
    if (!buckets.has(g)) buckets.set(g, []);
    buckets.get(g).push(f);
  }
  return [...buckets.keys()].sort((a, b) => a - b).map(g => {
    const fs = buckets.get(g);
    const passed = fs.filter(f => f.verdict === "pass").length;
    return {
      gen: g, n: fs.length,
      ic: median(fs.map(f => f.latest_ic)),
      icir: median(fs.map(f => f.latest_icir)),
      passRate: fs.length ? passed / fs.length : null
    };
  });
}
function renderTrend() {
  const svg = document.getElementById("trendChart");
  const legend = document.getElementById("trendLegend");
  const series = aggregateByGeneration();
  if (series.length < 2) {
    legend.innerHTML = "";
    svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" font-size="13" fill="var(--ink-faint)">代际数据不足（少于 2 代）</text>`;
    return;
  }
  const w = 720, h = 260, left = 56, right = 56, top = 20, bottom = 40;
  const icVals = [...series.map(s => s.ic), ...series.map(s => s.icir)].filter(Number.isFinite);
  const yAbs = Math.max(0.2, ...icVals.map(Math.abs));
  const yScale = v => h - bottom - ((v + yAbs) / (2 * yAbs)) * (h - top - bottom);
  const xScale = i => left + (i / (series.length - 1)) * (w - left - right);
  const rScale = v => v === null ? null : h - bottom - v * (h - top - bottom);
  let grid = "";
  for (const v of [-yAbs, -yAbs / 2, 0, yAbs / 2, yAbs]) {
    const y = yScale(v);
    grid += `<line x1="${left}" y1="${y.toFixed(1)}" x2="${w-right}" y2="${y.toFixed(1)}" stroke="var(--border)"${v === 0 ? ' stroke-width="1.2" stroke-dasharray="4,3"' : ""}/>` +
      `<text x="${left-8}" y="${(y+4).toFixed(1)}" text-anchor="end" font-size="10.5" fill="var(--ink-faint)" font-family="var(--mono)">${v.toFixed(2)}</text>`;
  }
  for (const r of [0, .5, 1]) {
    const y = rScale(r);
    if (y !== null) grid += `<text x="${w-right+8}" y="${(y+4).toFixed(1)}" font-size="10.5" fill="var(--warn)" fill-opacity=".8" font-family="var(--mono)">${(r*100).toFixed(0)}%</text>`;
  }
  series.forEach((s, i) => {
    grid += `<text x="${xScale(i).toFixed(1)}" y="${h-16}" text-anchor="middle" font-size="10.5" fill="var(--ink-faint)" font-family="var(--mono)">G${s.gen}</text>`;
  });
  function line(key, scale) {
    const pts = series.map((s, i) => ({ i, v: s[key] })).filter(p => Number.isFinite(p.v));
    if (pts.length < 2) return "";
    return pts.map((p, k) => `${k ? "L" : "M"} ${xScale(p.i).toFixed(1)} ${scale(p.v).toFixed(1)}`).join(" ");
  }
  function rateLine() {
    const pts = series.map((s, i) => ({ i, v: s.passRate })).filter(p => p.v !== null && p.v !== undefined);
    if (pts.length < 2) return "";
    return pts.map((p, k) => `${k ? "L" : "M"} ${xScale(p.i).toFixed(1)} ${rScale(p.v).toFixed(1)}`).join(" ");
  }
  function area(key, scale, color) {
    const pts = series.map((s, i) => ({ i, v: s[key] })).filter(p => Number.isFinite(p.v));
    if (pts.length < 2) return "";
    const d = pts.map((p, k) => `${k ? "L" : "M"} ${xScale(p.i).toFixed(1)} ${scale(p.v).toFixed(1)}`).join(" ") +
      ` L ${xScale(pts[pts.length-1].i).toFixed(1)} ${yScale(0).toFixed(1)} L ${xScale(pts[0].i).toFixed(1)} ${yScale(0).toFixed(1)} Z`;
    return `<path d="${d}" fill="${color}" fill-opacity=".12" stroke="none"/>`;
  }
  const dots = (key, scale, color) => series.map((s, i) => Number.isFinite(s[key])
    ? `<circle cx="${xScale(i).toFixed(1)}" cy="${scale(s[key]).toFixed(1)}" r="3" fill="${color}"><title>第 ${s.gen} 代 · ${s.n} 因子\nIC ${s.ic === null ? "—" : s.ic.toFixed(3)} / ICIR ${s.icir === null ? "—" : s.icir.toFixed(3)}\n通过率 ${s.passRate === null ? "—" : (s.passRate*100).toFixed(0)}%</title></circle>`
    : "").join("");
  svg.innerHTML = `${grid}
    ${area("ic", yScale, "var(--accent)")}
    ${area("icir", yScale, "var(--up)")}
    <path d="${line("ic", yScale)}" fill="none" stroke="var(--accent)" stroke-width="1.8" stroke-linejoin="round"/>
    <path d="${line("icir", yScale)}" fill="none" stroke="var(--up)" stroke-width="1.8" stroke-linejoin="round"/>
    ${series.map((s, i) => s.passRate === null ? "" :
      `<line x1="${xScale(i).toFixed(1)}" y1="${rScale(0).toFixed(1)}" x2="${xScale(i).toFixed(1)}" y2="${rScale(s.passRate).toFixed(1)}" stroke="var(--warn)" stroke-width="1" opacity=".5"/>`).join("")}
    <path d="${rateLine()}" fill="none" stroke="var(--warn)" stroke-width="1.2" stroke-dasharray="4,3" opacity=".8"/>
    ${dots("ic", yScale, "var(--accent)")}
    ${dots("icir", yScale, "var(--up)")}`;
  legend.innerHTML =
    `<span><i style="background:var(--accent)"></i>IC 中位数</span>` +
    `<span><i style="background:var(--up)"></i>ICIR 中位数</span>` +
    `<span><i style="background:var(--warn)"></i>通过率（右轴）</span>`;
}
function render() {
  renderMetrics(); renderScatter(); renderStatusChart(); renderTrend(); renderLineage(); renderTable();
  if (!useInlineDetails()) {
    renderDetail();
  } else {
    document.getElementById("detailPanel").classList.remove("open");
    document.body.classList.remove("sheet-open");
  }
}
function init() {
  state.selected = null;
  renderHeader(); fillSelects(); fillLineageSelect(); render();
  document.getElementById("searchInput").addEventListener("input", event => {
    state.query = event.target.value.trim(); renderTable();
  });
  document.getElementById("statusFilter").addEventListener("change", event => {
    state.status = event.target.value; renderTable();
  });
  document.getElementById("tagFilter").addEventListener("change", event => {
    state.tag = event.target.value; renderTable();
  });
  document.getElementById("resetButton").addEventListener("click", () => {
    state.query = ""; state.status = "all"; state.tag = "all";
    document.getElementById("searchInput").value = "";
    document.getElementById("statusFilter").value = "all";
    document.getElementById("tagFilter").value = "all";
    renderTable();
  });
  document.querySelectorAll(".sort-header").forEach(button => button.addEventListener("click", event => {
    const key = button.dataset.key;
    const defaultDir = key === "xname" || key === "status" ? 1 : -1;
    if (!state.sort || state.sort.key !== key) {
      state.sort = {key, dir: defaultDir};
    } else {
      state.sort.dir *= -1;
    }
    renderTable();
  }));
  document.getElementById("exportButton").addEventListener("click", exportCsv);
  document.getElementById("printButton").addEventListener("click", () => window.print());
  document.getElementById("refreshHint").addEventListener("click", () => alert("这是只读静态快照。更新数据后重新运行：python3 core/tools/generate_factor_dashboard.py"));
  document.getElementById("lineageBranchFilter").addEventListener("change", event => {
    graphState.branch = event.target.value;
    graphState.cache = null;
    graphState.view = null;
    renderLineage();
  });
  document.getElementById("lineageFitButton").addEventListener("click", () => {
    graphState.view = null;
    renderLineage();
  });
  document.getElementById("lineageResetButton").addEventListener("click", () => {
    graphState.branch = "all";
    document.getElementById("lineageBranchFilter").value = "all";
    graphState.cache = null;
    graphState.view = null;
    renderLineage();
  });
  const lineageSvg = document.getElementById("lineageChart");
  lineageSvg.addEventListener("wheel", onLineageWheel, {passive: false});
  lineageSvg.addEventListener("pointerdown", onLineagePointerDown);
  lineageSvg.addEventListener("pointermove", onLineagePointerMove);
  lineageSvg.addEventListener("pointerup", onLineagePointerUp);
  lineageSvg.addEventListener("pointercancel", onLineagePointerUp);
  document.addEventListener("keydown", event => {
    if (event.key === "/" && event.target.tagName !== "INPUT") {
      event.preventDefault(); document.getElementById("searchInput").focus();
    }
    if (event.key === "Escape" && state.selected) {
      state.selected = null; render();
    }
  });
  window.matchMedia("(max-width: 780px)").addEventListener("change", event => {
    if (event.matches) {
      state.selected = null;
    }
    render();
  });
}
init();
