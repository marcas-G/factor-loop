export interface FilterState {
  q: string;                    // text search
  status: string[];             // status multi-select
  tags: string[];               // tag multi-select
  gates: string[];              // gate combo: "pass"|"ic"|"icir"|"res_ic"|"r2"
  origin: string[];             // origin_type/class_name multi-select
  opChainMin: number | null;    // operator chain length range
  opChainMax: number | null;
  createdFrom: string | null;   // ISO date
  createdTo: string | null;
  sortKey: string;
  sortDir: "asc" | "desc";
  selected: string | null;      // selected factor xname
  branch: string;               // lineage branch "all"|root_xname
}

export const DEFAULT_FILTERS: FilterState = {
  q: "", status: [], tags: [], gates: [], origin: [],
  opChainMin: null, opChainMax: null, createdFrom: null, createdTo: null,
  sortKey: "agg_score", sortDir: "desc", selected: null, branch: "all",
};

export function parseHash(): FilterState {
  const out = { ...DEFAULT_FILTERS };
  const h = new URLSearchParams(location.hash.replace(/^#/, ""));
  if (h.has("q")) out.q = h.get("q") ?? "";
  for (const key of ["status", "tags", "gates", "origin"] as const) {
    const v = h.get(key);
    if (v) out[key] = v.split(",").filter(Boolean);
  }
  const num = (k: "opChainMin" | "opChainMax") => {
    const v = h.get(k);
    if (v !== null && v !== "" && Number.isFinite(Number(v))) out[k] = Number(v);
  };
  num("opChainMin"); num("opChainMax");
  if (h.get("from")) out.createdFrom = h.get("from");
  if (h.get("to")) out.createdTo = h.get("to");
  if (h.get("sort")) out.sortKey = h.get("sort")!;
  if (h.get("dir") === "asc" || h.get("dir") === "desc") out.sortDir = h.get("dir") as "asc" | "desc";
  if (h.get("sel")) out.selected = h.get("sel");
  if (h.get("branch")) out.branch = h.get("branch")!;
  return out;
}

export function writeHash(f: FilterState): void {
  const h = new URLSearchParams();
  if (f.q) h.set("q", f.q);
  for (const key of ["status", "tags", "gates", "origin"] as const) {
    if (f[key].length) h.set(key, f[key].join(","));
  }
  if (f.opChainMin !== null) h.set("opChainMin", String(f.opChainMin));
  if (f.opChainMax !== null) h.set("opChainMax", String(f.opChainMax));
  if (f.createdFrom) h.set("from", f.createdFrom);
  if (f.createdTo) h.set("to", f.createdTo);
  if (f.sortKey !== DEFAULT_FILTERS.sortKey || f.sortDir !== DEFAULT_FILTERS.sortDir) {
    h.set("sort", f.sortKey); h.set("dir", f.sortDir);
  }
  if (f.selected) h.set("sel", f.selected);
  if (f.branch !== "all") h.set("branch", f.branch);
  const s = h.toString();
  const next = s ? `#${s}` : "";
  if (location.hash !== next) history.replaceState(null, "", next || location.pathname);
}
