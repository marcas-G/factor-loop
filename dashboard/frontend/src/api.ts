import type { Snapshot } from "./types";

let etag: string | null = null;          // fetchSnapshot's validator
let lastData: Snapshot | null = null;
let probeBaseline: string | null = null; // probeSnapshot's own baseline

export interface FetchResult { data: Snapshot; changed: boolean }

export async function fetchSnapshot(): Promise<FetchResult> {
  const headers: Record<string, string> = {};
  if (etag) headers["If-None-Match"] = etag;
  const res = await fetch("/api/snapshot", { headers, cache: "no-store" });
  if (res.status === 304 && lastData) return { data: lastData, changed: false };
  if (!res.ok) throw new Error(`api ${res.status}`);
  const newEtag = res.headers.get("ETag");
  if (newEtag) etag = newEtag;
  lastData = await res.json() as Snapshot;
  probeBaseline = etag; // data and probe baseline move together
  return { data: lastData, changed: true };
}

/** HEAD probe: true when server has newer data than what we applied.
 *  Never mutates fetchSnapshot's etag. */
export async function probeSnapshot(): Promise<boolean> {
  const res = await fetch("/api/snapshot", { method: "HEAD", cache: "no-store" });
  if (!res.ok) return false;
  const server = res.headers.get("ETag");
  if (!server) return false;
  if (probeBaseline === null) { probeBaseline = server; return false; }
  return server !== probeBaseline;
}
