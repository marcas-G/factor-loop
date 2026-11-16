"""Read-only research console API for the 81-chapter corpus autoloop.

Designed to bind only to loopback by default. Reads the actual SQLite ledger
with mode=ro and never instantiates CorpusAutoloop (which could mutate the DB).
If no DB exists, serves the canonical chapter texts marked *not initialized*.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .corpus import CORPUS_ID, load_chapters

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = Path(os.getenv("CORPUS_AUTOLOOP_DB_PATH", "~/.quant-corpus-autoloop/research.sqlite3")).expanduser()
OBJECT_ID_RE = re.compile(r"^RO-DDJ-(?:0(?:0[1-9]|[1-7][0-9]|8[01]))(?:-[12]){0,2}$")
TERMINAL_STATES = {"terminal_admitted", "terminal_fused", "terminal_exhausted", "terminal_split"}
RESULT_KEYS = ("hypothesis", "factor", "evaluation", "fusion", "admission", "split")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_db(path: Path) -> tuple[list[dict], list[dict], int, bool]:
    """Snapshot existing ledger without creating or changing any file."""
    if not path.is_file():
        return [], [], 0, False
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=2) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        rows = [dict(row) for row in conn.execute(
            "SELECT object_id, source_id, parent_id, depth, status, revision, "
            "hypothesis_json, factor_json, evaluation_json, fusion_json, "
            "admission_json, split_json, created_at, updated_at "
            "FROM research_objects ORDER BY object_id"
        )]
        events = [dict(row) for row in conn.execute(
            "SELECT object_id, kind, recorded_at FROM research_events "
            "ORDER BY id DESC LIMIT 200"
        )]
        total_events = conn.execute("SELECT COUNT(*) FROM research_events").fetchone()[0]
        return rows, events, total_events, True


def _status_group(status: str) -> str:
    if status == "uninitialized":
        return "uninitialized"
    if status == "pending":
        return "pending"
    if status == "terminal_admitted" or status == "terminal_fused":
        return "admitted"
    if status in ("terminal_exhausted", "terminal_split"):
        return "closed"
    return "running"


def _compact_object(row: dict) -> dict:
    parsed = dict(row)
    for key in RESULT_KEYS:
        raw = parsed.pop(f"{key}_json", None)
        parsed[key] = json.loads(raw) if raw else None
    hypo = parsed["hypothesis"] or {}
    factor = parsed["factor"] or {}
    evaluation = parsed["evaluation"] or {}
    predictive = evaluation.get("predictive") or {}
    independent = evaluation.get("independence") or {}
    fusion = parsed["fusion"] or {}
    return {
        "id": parsed["object_id"],
        "chapter": int(parsed["source_id"].rsplit("-", 1)[1]),
        "parentId": parsed["parent_id"],
        "depth": parsed["depth"],
        "status": parsed["status"],
        "group": _status_group(parsed["status"]),
        "revision": parsed["revision"],
        "updatedAt": parsed["updated_at"],
        "sourceQuote": hypo.get("source_quote") or "",
        "hypothesis": hypo.get("hypothesis") or "",
        "sourcePrinciple": hypo.get("source_principle") or "",
        "marketAnalogy": hypo.get("market_analogy") or "",
        "observablePrediction": hypo.get("observable_prediction") or "",
        "requiredData": hypo.get("required_data") or [],
        "factorName": factor.get("name") or "",
        "factorFormula": factor.get("formula") or "",
        "factorIntuition": factor.get("intuition") or "",
        "metricName": predictive.get("metric_name") or "",
        "metricValue": predictive.get("metric_value"),
        "predictivePassed": predictive.get("passed"),
        "r2": independent.get("r2_x"),
        "resIc": independent.get("res_ic"),
        "independence": independent.get("decision") or "",
        "nearestFactors": independent.get("nearest_factors") or [],
        "executionRef": evaluation.get("execution_ref") or "",
        "dataSplit": evaluation.get("data_split") or "",
        "fusionSucceeded": fusion.get("success") if fusion else None,
        "admitted": bool(parsed["admission"]),
    }


def load_dashboard(db_path: Path | str = DEFAULT_DB) -> dict:
    """Real source + read-only DB snapshot; no invented experiments or scores."""
    source_units = load_chapters()
    raw_rows, raw_events, event_count, initialized = _read_db(Path(db_path).expanduser())
    objects = [_compact_object(row) for row in raw_rows]
    if not initialized:
        objects = [{
            "id": f"RO-DDJ-{unit['chapter']:03d}",
            "chapter": unit["chapter"],
            "parentId": None, "depth": 0,
            "status": "uninitialized", "group": "uninitialized",
            "revision": 0, "updatedAt": None,
            "sourceQuote": "", "hypothesis": "", "sourcePrinciple": "",
            "marketAnalogy": "", "observablePrediction": "", "requiredData": [],
            "factorName": "", "factorFormula": "", "factorIntuition": "",
            "metricName": "", "metricValue": None, "predictivePassed": None,
            "r2": None, "resIc": None, "independence": "",
            "nearestFactors": [], "executionRef": "", "dataSplit": "",
            "fusionSucceeded": None, "admitted": False,
        } for unit in source_units]
    roots = {o["chapter"]: o for o in objects if o["parentId"] is None}
    grouped = Counter(o["group"] for o in objects)
    counts = Counter(o["status"] for o in objects)
    chapters = [{
        "chapter": unit["chapter"],
        "title": unit["title"],
        "part": unit["part"],
        "sourceId": unit["unit_id"],
        "text": unit["text"],
        "sourceFile": unit["source_file"],
        "sourceStatus": unit.get("source_status") or "unknown",
        "status": roots.get(unit["chapter"], {}).get("status", "uninitialized"),
        "group": roots.get(unit["chapter"], {}).get("group", "uninitialized"),
        "objects": sum(o["chapter"] == unit["chapter"] for o in objects),
    } for unit in source_units]
    finished_roots = sum(c["status"] in TERMINAL_STATES for c in chapters)
    next_obj = next((o["id"] for o in sorted(objects, key=lambda x: (
        x["chapter"], x["depth"], x["id"]))
        if o["group"] in ("running", "pending")), None)
    return {
        "version": 1, "corpusId": CORPUS_ID, "timestamp": _utc_now(),
        "initialized": initialized,
        "mode": "live_readonly" if initialized else "corpus_preview",
        "summary": {
            "chapters": len(chapters), "completedChapters": finished_roots,
            "totalObjects": len(raw_rows) if initialized else 0,
            "admitted": grouped["admitted"],
            "running": grouped["running"], "pending": grouped["pending"],
            "closed": grouped["closed"],
            "events": event_count,
            "nextObjectId": next_obj if initialized else None,
            "states": dict(counts),
        },
        "chapters": chapters,
        "objects": objects,
        "recentEvents": raw_events[:24],
    }


def object_detail(snapshot: dict, object_id: str) -> dict | None:
    if not OBJECT_ID_RE.fullmatch(object_id):
        return None
    matched = next((x for x in snapshot["objects"] if x["id"] == object_id), None)
    if matched is None:
        return None
    source = next((c for c in snapshot["chapters"]
                   if c["chapter"] == matched["chapter"]), None)
    lineage = sorted((x for x in snapshot["objects"]
                      if x["chapter"] == matched["chapter"]),
                     key=lambda x: (x["depth"], x["id"]))
    events = [e for e in snapshot["recentEvents"] if e["object_id"] == object_id]
    return {"object": matched, "source": source, "lineage": lineage, "events": events}


class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "CorpusConsole/1.0"

    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def _json(self, payload: dict, code: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _problem(self, message: str, code: int) -> None:
        self._json({"error": message}, code)

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/"):
            try:
                snapshot = load_dashboard(self.server.research_db)  # type: ignore[attr-defined]
                if path == "/api/health":
                    self._json({"ok": True, "initialized": snapshot["initialized"],
                                "mode": snapshot["mode"]})
                elif path == "/api/dashboard":
                    self._json(snapshot)
                elif path.startswith("/api/objects/") and path.count("/") == 3:
                    detail = object_detail(snapshot, path.rsplit("/", 1)[-1])
                    if detail is None:
                        self._problem("research object not found", 404)
                    else:
                        self._json(detail)
                else:
                    self._problem("unknown API endpoint", 404)
            except (ValueError, sqlite3.DatabaseError, OSError) as exc:
                self.log_error("read-only dashboard request failed: %s", exc)
                self._problem("research ledger unavailable or invalid", 503)
            return
        if path == "/" or path.startswith("/assets/") or path in ("/index.html", "/favicon.svg"):
            return super().do_GET()
        self.send_error(404, "not found")

    def do_POST(self) -> None:
        self._problem("read-only API; mutations are disabled", 405)

    def log_message(self, format: str, *args: object) -> None:
        # Keep stock server logs from exposing API response contents.
        super().log_message(format, *args)


def serve(host: str, port: int, db_path: Path, static_dir: Path, *, api_only: bool = False) -> None:
    if not api_only and (not static_dir.is_dir() or not (static_dir / "index.html").exists()):
        raise SystemExit(f"Frontend build missing: {static_dir}. Run npm run build in web/ first.")
    from functools import partial
    handler = partial(DashboardHandler, directory=str(static_dir))
    with ThreadingHTTPServer((host, port), handler) as httpd:
        httpd.research_db = db_path
        print(f"Corpus research console: http://{host}:{port}")
        print(f"Research DB (read-only): {db_path}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Read-only Factor Autoloop research console")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Loopback only by default; do not expose research data publicly")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--static", type=Path, default=ROOT / "web" / "dist")
    parser.add_argument("--api-only", action="store_true",
                        help="Allow Vite dev server without first building web/dist")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    serve(args.host, args.port, args.db.expanduser(), args.static.resolve(),
          api_only=args.api_only)


if __name__ == "__main__":
    main()
