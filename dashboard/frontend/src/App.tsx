import { useEffect, useMemo, useState } from "react";
import { Header } from "./components/Header";
import { MetricCards } from "./components/MetricCards";
import { StatusChart } from "./components/charts/StatusChart";
import { Scatter } from "./components/charts/Scatter";
import { Trend } from "./components/charts/Trend";
import { LineageTree } from "./components/LineageTree";
import { FilterBar } from "./components/FilterBar";
import { FactorTable } from "./components/FactorTable";
import { DetailPanel } from "./components/DetailPanel";
import { useSnapshot } from "./hooks/useSnapshot";
import { parseHash, writeHash, DEFAULT_FILTERS, type FilterState } from "./state";

export default function App() {
  const { data, loadState, stale, updatedAt, refresh, applyStale } = useSnapshot();
  const [filters, setFilters] = useState<FilterState>(() => parseHash());

  const parentOf = useMemo(
    () => new Map(data?.lineage_edges.map(e => [e.child_xname, e.parent_xname]) ?? []),
    [data?.lineage_edges],
  );

  useEffect(() => { writeHash(filters); }, [filters]);
  useEffect(() => {
    const onHash = () => setFilters(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (loadState === "loading") return <div className="fullpad">加载中…</div>;
  if (loadState === "error" || !data) return <div className="fullpad">API 不可达,稍后重试</div>;

  return (
    <>
      <Header loadState={loadState} stale={stale} updatedAt={updatedAt}
              generatedAt={data.meta.generatedAt}
              onRefresh={refresh} onApplyStale={applyStale} />
      <main className={`layout${filters.selected ? " with-panel" : ""}`}>
        <div className="main-column">
          <MetricCards factors={data.factors} evaluations={data.evaluations}
                       onFilterGate={() => setFilters(f => ({ ...f, gates: ["pass"] }))} />
          <div className="chart-grid">
            <Scatter factors={data.factors} selected={filters.selected}
                     onSelect={xname => setFilters(f => ({ ...f, selected: xname }))} />
            <StatusChart factors={data.factors} />
          </div>
          <div className="chart-grid">
            <Trend factors={data.factors} edges={data.lineage_edges} />
          </div>
          <div className="chart-grid">
            <LineageTree factors={data.factors} edges={data.lineage_edges}
                         branches={data.lineage_branches} branch={filters.branch}
                         onBranchChange={b => setFilters(f => ({ ...f, branch: b }))}
                         selected={filters.selected}
                         onSelect={xname => setFilters(f => ({ ...f, selected: xname }))} />
          </div>
          <div className="chart-grid">
            <FilterBar factors={data.factors} filters={filters}
                       onChange={patch => setFilters(f => ({ ...f, ...patch }))}
                       onReset={() => setFilters(f => ({
                         ...DEFAULT_FILTERS, selected: f.selected, branch: f.branch,
                       }))} />
            <FactorTable factors={data.factors} filters={filters}
                         onSort={key => setFilters(f => key === f.sortKey
                           ? { ...f, sortDir: f.sortDir === "desc" ? "asc" : "desc" }
                           : { ...f, sortKey: key, sortDir: "desc" })}
                         onSelect={xname => setFilters(f => ({
                           ...f, selected: f.selected === xname ? null : xname,
                         }))} />
          </div>
        </div>
        <DetailPanel
          factor={data.factors.find(f => f.xname === filters.selected) ?? null}
          iterations={data.iterations}
          lessons={data.lessons}
          parentOf={parentOf}
          onClose={() => setFilters(f => ({ ...f, selected: null }))} />
      </main>
    </>
  );
}
