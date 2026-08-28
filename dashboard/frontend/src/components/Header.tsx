import type { LoadState } from "../hooks/useSnapshot";

interface Props {
  loadState: LoadState;
  stale: boolean;
  updatedAt: string | null;
  generatedAt: string;
  onRefresh: () => void;
  onApplyStale: () => void;
}

export function Header({ loadState, stale, updatedAt, generatedAt, onRefresh, onApplyStale }: Props) {
  return (
    <header className="app-header">
      <div className="brand">
        <div className="brand-mark" aria-hidden>F</div>
        <div>
          <h1>因子库看板</h1>
          <p className="meta">快照 {new Date(generatedAt).toLocaleString()}</p>
        </div>
      </div>
      <div className="header-actions">
        {stale && (
          <button className="stale-badge" role="status"
                  title="数据已更新,点击应用(不打断当前浏览)"
                  onClick={onApplyStale}>
            有新数据 · 应用
          </button>
        )}
        <button className="icon-button" onClick={onRefresh}
                title="手动刷新(保留筛选与滚动位置)">↻</button>
        <span className="load-dot" data-state={loadState} title={updatedAt ?? ""} />
      </div>
    </header>
  );
}
