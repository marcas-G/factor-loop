import { useEffect, useState } from "react";

export default function App() {
  const [msg, setMsg] = useState("loading…");
  useEffect(() => {
    fetch("/api/snapshot").then(r => r.json()).then(d => {
      setMsg(`factors: ${d.factors?.length ?? "?"}`);
    }).catch(() => setMsg("api unreachable"));
  }, []);
  return <main style={{ padding: 24, fontFamily: "monospace" }}>{msg}</main>;
}
