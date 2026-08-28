import type { Factor } from "../types";
import type { FilterState } from "../state";

export const GATE_OPTIONS: { value: string; label: string }[] = [
  { value: "pass", label: "闸门全过" },
  { value: "ic", label: "IC 达标" },
  { value: "icir", label: "ICIR 达标" },
  { value: "res_ic", label: "残差IC 达标" },
  { value: "r2", label: "R² 达标" },
];

/** Number of operators in the chain. null when operator_chain is absent,
 *  0 when present but empty/whitespace. The DB stores the chain as a JSON
 *  array string ("[21]", "[21, 23]" — persist.py json.dumps(operator_refs)),
 *  so try that first; fall back to separator-split for legacy/plain text. */
export function operatorChainLength(f: Factor): number | null {
  const c = f.operator_chain;
  if (c === null || c === undefined) return null;
  const s = c.trim();
  if (s === "") return 0;
  if (s.startsWith("[")) {
    try {
      const parsed: unknown = JSON.parse(s);
      if (Array.isArray(parsed)) return parsed.length;
    } catch { /* fall through to separator split */ }
  }
  const parts = s.split(/[->+·]+/).filter(Boolean);
  return parts.length;
}

function matchesText(f: Factor, q: string): boolean {
  const hay = [
    f.xname,
    f.formula_text ?? "",
    f.intuition ?? "",
    ...f.tags.map(t => t.name),
  ].join("\n").toLowerCase();
  return hay.includes(q);
}

function matchesGates(f: Factor, gates: string[]): boolean {
  for (const g of gates) {
    if (g === "pass") {
      if (!f.gate_pass) return false;
    } else if (f.failed_gates.includes(g)) {
      return false;
    }
  }
  return true;
}

function matchesOrigin(f: Factor, origin: string[]): boolean {
  const keys = [f.origin_type, f.class_name].filter((v): v is string => v !== null);
  return origin.some(o => keys.includes(o));
}

export function applyFilters(factors: Factor[], fl: FilterState): Factor[] {
  const q = fl.q.trim().toLowerCase();
  return factors.filter(f => {
    if (q && !matchesText(f, q)) return false;
    if (fl.status.length && !fl.status.includes(f.status)) return false;
    if (fl.tags.length && !f.tags.some(t => fl.tags.includes(t.name))) return false;
    if (fl.gates.length && !matchesGates(f, fl.gates)) return false;
    if (fl.origin.length && !matchesOrigin(f, fl.origin)) return false;
    if (fl.opChainMin !== null || fl.opChainMax !== null) {
      const len = operatorChainLength(f);
      if (len === null) return false; // null chains excluded when a range is set
      if (fl.opChainMin !== null && len < fl.opChainMin) return false;
      if (fl.opChainMax !== null && len > fl.opChainMax) return false;
    }
    if (fl.createdFrom && (f.created_ts ?? "") < fl.createdFrom) return false;
    if (fl.createdTo && (f.created_ts ?? "") > fl.createdTo + "T23:59:59") return false;
    return true;
  });
}

type SortKey = FilterState["sortKey"];

const NUMERIC: Record<string, (f: Factor) => number | null> = {
  latest_ic: f => f.latest_ic,
  latest_icir: f => f.latest_icir,
  latest_r2_x: f => f.latest_r2_x,
  latest_res_ic: f => f.latest_res_ic,
  resic_ic_ratio: f => f.resic_ic_ratio,
  agg_score: f => f.agg_score,
  s_ic: f => f.s_ic,
  s_icir: f => f.s_icir,
  quality_score: f => f.quality_score,
};

const STRINGY: Record<string, (f: Factor) => string | null> = {
  xname: f => f.xname,
  verdict: f => f.verdict,
  status: f => f.status,
  created_ts: f => f.created_ts,
  last_updated_ts: f => f.last_updated_ts,
};

/** Nulls always sink to the bottom regardless of direction. */
export function sortFactors(
  factors: Factor[],
  key: SortKey,
  dir: "asc" | "desc",
): Factor[] {
  const num = NUMERIC[key];
  const str = STRINGY[key];
  const mul = dir === "asc" ? 1 : -1;
  return [...factors].sort((a, b) => {
    if (num) {
      const va = num(a), vb = num(b);
      if (va === null && vb === null) return 0;
      if (va === null) return 1;   // nulls sink
      if (vb === null) return -1;
      return (va - vb) * mul;
    }
    if (str) {
      const va = str(a) ?? "", vb = str(b) ?? "";
      // empty (null-ish) sinks too
      if (va === "" && vb === "") return 0;
      if (va === "") return 1;
      if (vb === "") return -1;
      return va.localeCompare(vb) * mul;
    }
    return 0;
  });
}
