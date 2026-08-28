import { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { useSnapshot } from "./hooks/useSnapshot";
import { parseHash, writeHash, type FilterState } from "./state";

export default function App() {
  const { data, loadState, stale, updatedAt, refresh, applyStale } = useSnapshot();
  const [filters, setFilters] = useState<FilterState>(() => parseHash());

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
      <main className="layout">
        {/* Tasks 7-11 fill this in */}
      </main>
    </>
  );
}
