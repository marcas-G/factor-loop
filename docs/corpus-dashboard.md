# Factor Autoloop Research Console

A real-data dashboard for the **Dao De Jing corpus-guided Factor Autoloop**. This is a new, independently deployable frontend rather than an image or a static mock.

## Stack

| Layer | Technology | Responsibility |
|---|---|---|
| UI | React 18 + TypeScript | Typed research views and interactive chapter selection |
| Build | Vite 6 | Local development, HMR and optimized production bundle |
| Routing | React Router 6 | Shareable `?chapter=...` deep links |
| Server state | TanStack Query 5 | Asynchronous loading, errors and 20-second polling |
| UI assets | Lucide React + authored CSS design system | Responsive visual language, no mandatory CDN or external fonts |
| API | FastAPI | **Read-only** typed JSON routes, OpenAPI documentation |
| Data | Existing Corpus Autoloop SQLite + 81 original chapters | Never creates fake metrics or triggers platform operations |
| Execution | Existing `auto-run`, OpenCode, quant-mcp | Runs separately, under the existing explicit consent gate |

## Quick start

From the repository root, with Python 3.11+ and Node 20.19+/22.12+:

```bash
python -m pip install 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1'
python -m uvicorn core.corpus_autoloop.dashboard_api:app --host 127.0.0.1 --port 8765
```

In a second terminal:

```bash
cd web
npm install
npm run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to port 8765, avoiding CORS issues. Backend documents live at http://127.0.0.1:8765/api/docs.

The dashboard is usable **without running `seed`**: chapter 1–81 can be read directly from bundled corpus files. They are labeled **尚未初始化**. To populate the real research state:

```bash
python -m core.corpus_autoloop.cli seed
```

To start actual research tasks, follow [the execution adapter runbook](corpus-execution-adapter.md), especially its real-data and explicit platform-write requirements. The web interface deliberately has **no "start research" or "commit factor" endpoint** because those require separate model, evidence and platform authorization.

## API

| GET endpoint | Response |
|---|---|
| `/api/health` | Connectivity and whether the local database already exists |
| `/api/overview` | Totals for 81 chapters, research objects and terminal decisions |
| `/api/chapters` | All 81 chapters, summary research statuses |
| `/api/chapters/{chapter}` | Source text, source hash and associated research tree |
| `/api/research-objects/{object_id}` | Research object, bounded event metadata and executor links |
| `/api/activity?limit=12` | Recent append-only events, without arbitrary payloads |

Every request is read-only; SQLite is opened with `mode=ro` and `PRAGMA query_only=ON`. A missing database is not silently created. The app binds to localhost by default and allows only localhost Vite origins during development. Production use should put `/api` behind a same-origin reverse proxy and enforce access control before making any nonlocal deployment. Do **not** expose private trading or library details publicly.

## Frontend features

- Chapter search and filters for pending, active and terminal states.
- Source text panel with source-version fingerprint.
- Selected research hypothesis, market analogy and falsifiable prediction.
- Depth-limited (`0..2`) evolution tree with clickable child nodes.
- Actual ICIR, R² and residual IC when recorded; otherwise explicit empty state.
- Recent audited lifecycle events and manual refresh; automatic 20-second cache invalidation.
- Responsive desktop/tablet/mobile layout and reduced-motion handling.

**No fake numbers.** The empty database intentionally shows 81 chapters, 0 research objects, 0 admitted factors and no experimental metrics. Source content does not imply any financial hypothesis or measurable predictive effect.

## Validation

```bash
python -m pip install 'fastapi>=0.115,<1' 'httpx>=0.27,<1'
python -m unittest discover -s tests -p 'test_corpus_dashboard_api.py' -v
cd web && npm install && npm run build
```

CI runs Python API tests and the TypeScript production build. It does not need quant-mcp tokens, production factors or simulated returns.
