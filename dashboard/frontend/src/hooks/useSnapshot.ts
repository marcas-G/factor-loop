import { useCallback, useEffect, useState } from "react";
import { fetchSnapshot, probeSnapshot } from "../api";
import type { Snapshot } from "../types";

export type LoadState = "loading" | "ready" | "error";

export function useSnapshot() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [stale, setStale] = useState(false);       // probed newer data, not applied
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { data: snap } = await fetchSnapshot();
      setData(snap);
      setUpdatedAt(new Date().toISOString());
      setStale(false);
      setLoadState("ready");
    } catch {
      setLoadState(s => (s === "ready" ? s : "error"));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // background probe every 60s: badge only, NEVER auto-applies
  useEffect(() => {
    const id = setInterval(() => {
      probeSnapshot().then(changed => {
        if (changed) setStale(true);
      }).catch(() => { /* network down: silent */ });
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  return { data, loadState, stale, updatedAt, refresh,
           applyStale: () => { void refresh(); } };
}
