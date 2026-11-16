"""Read-only HTTP API for Corpus Autoloop Research Console.

The dashboard never creates/modifies the research SQLite DB, submits platform
jobs, invokes LLMs, or discloses local run credentials. API works even before
`seed`: 81 real source chapters are served from the bundled corpus.

Start with `python -m uvicorn core.corpus_autoloop.dashboard_api:app --host 127.0.0.1 --port 8765`.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .corpus import load_chapters

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = Path(os.getenv("CORPUS_AUTOLOOP_DB_PATH", "~/.quant-corpus-autoloop/research.sqlite3")).expanduser()
_ALLOWED_ID = re.compile(r"^RO-DDJ-\d{3}(?:-[12]){0,2}$")
_OPTIONAL_TABLES = {
    "corpus_execution_links", "corpus_fusion_trials", "corpus_holdout_attempts",
    "corpus_fusion_holdout",
}


def _db_path() -> Path:
    return Path(os.getenv("CORPUS_AUTOLOOP_DB_PATH", str(DEFAULT_DB))).expanduser()


@contextmanager
def _read_db():
    path = _db_path()
    if not path.is_file():
        yield None
        return
    # mode=ro: no accidental creation, migrations, writes or journal commits.
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            yield conn
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="研究数据库当前不可读取") from exc


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    if name not in _OPTIONAL_TABLES:
        return False
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _record(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("hypothesis_json", "factor_json", "evaluation_json", "fusion_json", "admission_json", "split_json"):
        if key in result:
            result[key[:-5]] = _json(result.pop(key))
    return result


def _chapter(record: dict, research: list[dict]) -> dict:
    nodes = [o for o in research if o["source_id"] == record["unit_id"]]
    root = next((o for o in nodes if o["parent_id"] is None), None)
    return {
        "chapter": record["chapter"],
        "title": record["title"],
        "part": record["part"],
        "unit_id": record["unit_id"],
        "content_sha256": record["content_sha256"],
        "status": root["status"] if root else "unseeded",
        "root_id": root["object_id"] if root else f"RO-DDJ-{record['chapter']:03d}",
        "total_nodes": len(nodes),
        "completed_nodes": sum(o["status"].startswith("terminal_") for o in nodes),
    }


def _objects(db: sqlite3.Connection | None) -> list[dict]:
    if db is None:
        return []
    try:
        return [_record(r) for r in db.execute(
            "SELECT object_id,source_id,parent_id,depth,status,revision,"
            "hypothesis_json,factor_json,evaluation_json,fusion_json,admission_json,split_json,"
            "created_at,updated_at FROM research_objects ORDER BY source_id,depth,object_id"
        )]
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=503, detail="数据库尚未完成 Corpus Autoloop 初始化") from exc


def _summary(objects: list[dict], corpus: list[dict]) -> dict:
    status: dict[str, int] = {}
    for item in objects:
        status[item["status"]] = status.get(item["status"], 0) + 1
    attempted = {o["source_id"] for o in objects if o["status"] != "pending"}
    admitted = status.get("terminal_admitted", 0)
    fused = status.get("terminal_fused", 0)
    completed = sum(v for k, v in status.items() if k.startswith("terminal_"))
    return {
        "corpus_title": "道德经 · 王弼本",
        "chapter_count": len(corpus),
        "attempted_chapters": len(attempted),
        "research_objects": len(objects),
        "completed_objects": completed,
        "admitted_factors": admitted,
        "fused_factors": fused,
        "active_objects": sum(v for k, v in status.items() if k not in ("pending",) and not k.startswith("terminal_")),
        "status_counts": status,
        "data_mode": "live" if objects else "corpus_only",
        "source": "local_corpus_and_readonly_sqlite",
    }


app = FastAPI(title="Factor Autoloop Research Console API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
# The Vite dev server is the sole supported cross-origin client in development.
# Production should reverse-proxy same-origin /api instead of using wildcard CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "read_only", "database_exists": _db_path().is_file()}


@app.get("/api/overview")
def overview():
    corpus = load_chapters()
    with _read_db() as db:
        objects = _objects(db)
    return _summary(objects, corpus)


@app.get("/api/chapters")
def chapters():
    corpus = load_chapters()
    with _read_db() as db:
        objects = _objects(db)
    return {"chapters": [_chapter(unit, objects) for unit in corpus]}


@app.get("/api/chapters/{chapter}")
def chapter_detail(chapter: int):
    if not 1 <= chapter <= 81:
        raise HTTPException(status_code=404, detail="章节不存在")
    unit = load_chapters()[chapter - 1]
    with _read_db() as db:
        objects = [o for o in _objects(db) if o["source_id"] == unit["unit_id"]]
    return {"source": unit, "research_objects": objects}


@app.get("/api/research-objects/{object_id}")
def research_detail(object_id: str):
    if not _ALLOWED_ID.fullmatch(object_id):
        raise HTTPException(status_code=404, detail="研究对象不存在")
    with _read_db() as db:
        if db is None:
            raise HTTPException(status_code=404, detail="研究对象尚未创建")
        row = db.execute("SELECT * FROM research_objects WHERE object_id=?", (object_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="研究对象不存在")
        obj = _record(row)
        # Event payloads can contain extensive model reasoning; return only the
        # bounded latest history, not raw filesystem paths or credentials.
        events = []
        for event in db.execute(
            "SELECT id,kind,recorded_at FROM research_events WHERE object_id=? ORDER BY id DESC LIMIT 80",
            (object_id,),
        ):
            events.append(dict(event))
        links = {}
        if _table_exists(db, "corpus_execution_links"):
            links["execution"] = [dict(r) for r in db.execute(
                "SELECT phase,status,run_id,updated_at FROM corpus_execution_links WHERE object_id=?", (object_id,)
            )]
        if _table_exists(db, "corpus_fusion_trials"):
            links["fusion"] = [dict(r) for r in db.execute(
                "SELECT status,run_id,updated_at FROM corpus_fusion_trials WHERE object_id=?", (object_id,)
            )]
    return {"research_object": obj, "events": events, "links": links}


@app.get("/api/activity")
def activity(limit: int = Query(12, ge=1, le=50)):
    with _read_db() as db:
        if db is None:
            return {"events": []}
        events = [dict(row) for row in db.execute(
            "SELECT id,object_id,kind,recorded_at FROM research_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )]
    return {"events": events}
