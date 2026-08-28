#!/usr/bin/env python3
"""Generate a self-contained static HTML dashboard for the factor library.

The output has no CDN, JavaScript dependency, or server requirement. Refresh it
after factor evaluation by rerunning this command and opening the HTML file.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DB_PATH  # noqa: E402
from core.tools.dashboard_snapshot import FACTOR_COLUMNS, collect_snapshot  # noqa: E402,F401

DEFAULT_OUTPUT = DB_PATH.parent / "factor_dashboard.html"


TEMPLATE_DIR = Path(__file__).resolve().parent / "dashboard_template"


def _read_template(rel: str) -> str:
    path = TEMPLATE_DIR / rel
    if not path.is_file():
        raise FileNotFoundError(f"dashboard template part missing: {path}")
    return path.read_text(encoding="utf-8")




def render_html(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).replace("</", "<\\/")
    vendor = _read_template("vendor/d3-hierarchy.min.js")
    return (_read_template("template.html")
            .replace("__VENDOR__", vendor)
            .replace("__CSS__", _read_template("style.css"))
            .replace("__JS__", _read_template("app.js"))
            .replace("__GENERATED_AT__",
                     snapshot.get("meta", {}).get("generatedAt", ""))
            .replace("__DATA__", payload))


def write_atomic(output_path: Path, html: str) -> None:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a self-contained static factor-library dashboard"
    )
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite factor database")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="output HTML path (default: data/factor_dashboard.html)",
    )
    parser.add_argument(
        "--open", action="store_true",
        help="try to open the generated page with the local desktop browser",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        snapshot = collect_snapshot(args.db)
        html = render_html(snapshot)
        write_atomic(args.output, html)
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    output_path = args.output.expanduser().resolve()
    print(f"Factor dashboard written: {output_path}")
    print(f"Factors: {len(snapshot['factors'])}; size: {output_path.stat().st_size / 1024:.1f} KiB")
    if args.open:
        import webbrowser

        webbrowser.open(output_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
