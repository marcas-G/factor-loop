#!/usr/bin/env python3
"""Factor dashboard HTTP server (stdlib only).

- GET /api/snapshot : fresh JSON from the SQLite db, ETag-cached on (mtime, size)
- GET /*            : static files from the Vite build (dist/), SPA fallback
The db is opened read-only (immutable=1) per snapshot; no pip dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools.dashboard_snapshot import DEFAULT_DB, collect_snapshot

DIST_DIR = Path(__file__).resolve().parent / "frontend" / "dist"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".map": "application/json",
}


class SnapshotCache:
    """(mtime_ns, size) → ETag;db 未变直接回缓存,变了重算。"""

    def __init__(self, db_path: Path | str) -> None:
        raw = str(db_path)
        self._fs_path = Path(raw.partition("?")[0].removeprefix("file:"))
        self._uri = raw if raw.startswith("file:") else f"file:{raw}?mode=ro&immutable=1"
        self._lock = threading.Lock()
        self._etag: str | None = None
        self._body: bytes = b""
        self.calls = 0  # times collect_snapshot actually ran (test observability)

    def _stamp(self) -> tuple[int, int]:
        st = self._fs_path.stat()
        return st.st_mtime_ns, st.st_size

    def etag(self) -> str:
        mtime_ns, size = self._stamp()
        return f'W/"{mtime_ns:x}-{size:x}"'

    def get(self) -> tuple[str, bytes]:
        etag = self.etag()
        with self._lock:
            if etag == self._etag:
                return etag, self._body
        snapshot = collect_snapshot(self._uri)
        body = json.dumps(
            snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        with self._lock:
            self._etag, self._body = etag, body
            self.calls += 1
        return etag, body


def make_handler(cache: SnapshotCache, dist_dir: Path | None) -> type[BaseHTTPRequestHandler]:
    dist = dist_dir if dist_dir is not None else DIST_DIR

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, code: int, body: bytes, ctype: str,
                   extra: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD" and code != 304:
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client went away mid-transfer; not an error

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] == "/api/snapshot":
                return self._api()
            return self._static()

        def _api(self) -> None:
            try:
                etag, body = cache.get()
            except Exception as exc:  # db missing/corrupt: 503, don't crash
                self._reply(503, f'{{"error":"{type(exc).__name__}"}}'.encode(),
                            "application/json; charset=utf-8")
                return
            if self.headers.get("If-None-Match") == etag:
                self._reply(304, b"", "application/json; charset=utf-8",
                            {"ETag": etag})
                return
            self._reply(200, body, "application/json; charset=utf-8",
                        {"ETag": etag})

        def _static(self) -> None:
            if dist is None or not dist.is_dir():
                self._reply(503, "frontend not built; run: cd dashboard/frontend && npm run build"
                            .encode(), "text/plain; charset=utf-8")
                return
            rel = self.path.split("?", 1)[0].lstrip("/")
            candidate = (dist / rel).resolve()
            if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
                return self._send_file(candidate)
            # SPA fallback: only for route-like paths (no file extension).
            # A missing asset (e.g. /assets/nope.js) must 404, not serve html.
            if not Path(rel).suffix:
                index = dist / "index.html"
                if index.is_file():
                    return self._send_file(index)
            self._reply(404, b"not found", "text/plain; charset=utf-8")

        def _send_file(self, path: Path) -> None:
            body = path.read_bytes()
            self._reply(200, body, MIME.get(path.suffix, "application/octet-stream"))

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[http] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def make_server(addr: tuple[str, int], cache: SnapshotCache,
                dist_dir: Path | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(addr, make_handler(cache, dist_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Factor dashboard server")
    parser.add_argument("--db", default=os.environ.get("FACTORS_DB", str(DEFAULT_DB)),
                        help="SQLite factor db (path or file: URI)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", "8765")))
    parser.add_argument("--dist", type=Path, default=DIST_DIR, help="frontend build dir")
    args = parser.parse_args()
    httpd = make_server(("0.0.0.0", args.port), SnapshotCache(args.db), dist_dir=args.dist)
    print(f"[http] dashboard on 0.0.0.0:{args.port} (db={args.db}, dist={args.dist})", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
