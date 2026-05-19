# arango-workflow-app

Unified **Databricks App** ([arango-agent-autograph-job/README.md](../arango-agent-autograph-job/README.md)): FastAPI BFF + Next.js UI with the **OntoExtract** frontend (same look and routes as [arango-ontoextract](../arango-ontoextract/)). Platform shell (dashboard-app layout) is backend-only for now — not exposed in the UI yet.

## Repository layout

Matches [arango-dashboard-app](../arango-dashboard-app/) conventions:

```text
arango-workflow-app/
  app.yaml              # Databricks Apps runtime
  deploy_app.sh         # sync + deploy + UC grants
  run_local.py          # optional local uvicorn (does not shadow src/app)
  databricks.yml        # DAB bundle
  pyproject.toml
  requirements.txt
  resources/
    arango_workflow.app.yml
  scripts/
    start-databricks-app.sh
    set_user_api_scopes.sh
  src/
    asgi.py             # ASGI entry (PYTHONPATH=src)
    app/                # FastAPI — OntoExtract + workflow BFF
    migrations/         # Arango schema migrations
    frontend/           # Next.js UI
  tests/                # pytest (pythonpath=src)
```

## Routes

| Path | Description |
|------|-------------|
| `/`, `/dashboard`, `/ontology-quality`, `/pipeline`, … | OntoExtract UI (graph canvas at `/dashboard`; quality at `/ontology-quality`) |
| `/api/v1/*` | OntoExtract REST API |
| `/api/workflow/*` | Control-plane BFF (reserved; no UI yet) |

## Quick Start

Same workflow as [arango-ontoextract](../arango-ontoextract/):

```bash
cd arango-workflow-app
cp .env.example .env          # Add your API keys (or reuse your ontoextract .env)
make setup                     # Python .venv at repo root + npm install in src/frontend

make infra                     # ArangoDB + Redis via Docker
make backend                   # FastAPI on :8010 (default; same as ontoextract Makefile)
```

In a second terminal (or use `make dev` to run API + UI together):

```bash
make ui                        # Next.js on :3000 — hot reload on every save
```

### Live frontend development

Edit files under `src/frontend/src/` and the browser updates automatically (Next.js Fast Refresh):

| What to edit | Shows at |
|--------------|----------|
| `src/frontend/src/app/page.tsx` | Home `/` |
| `src/frontend/src/app/dashboard/page.tsx` | Graph canvas (formerly `/workspace`) |
| `src/frontend/src/app/ontology-quality/page.tsx` | Quality dashboard (formerly `/dashboard`) |
| `src/frontend/src/components/**` | Shared UI |

Keep **`make ui`** running in one terminal and **`make backend`** in another. After changing `BACKEND_PORT` or `BACKEND_PROXY_URL` in `.env`, restart `make ui` so the API proxy picks up the new port.

If the UI looks stale, hard-refresh the browser (Ctrl+Shift+R) or run `make clean` then `make ui`.

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8010 |
| API Docs (Swagger) | http://localhost:8010/docs |
| Frontend | http://localhost:3000 |
| ArangoDB UI | http://localhost:8530 |

**Differences from ontoextract:** venv lives at **repo root** (`.venv/`), code under `src/app/` (not `backend/`), frontend under `src/frontend/` (not `frontend/`). Default API port is **8010** (not 8000) so it matches `src/frontend/.env.development`.

**Python:** 3.11+ recommended (`pyproject.toml`). Python 3.10 works with `app/compat.py` shims.

If you see `Cannot find native binding` on `npm run dev`:

```bash
./scripts/frontend-install.sh
```

### Manual / alternate commands

```bash
export PYTHONPATH=src
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
cd src/frontend && npm run dev
```

Static export for single-process deploy:

```bash
cd src/frontend && AOE_STATIC_EXPORT=1 npm run build
export PYTHONPATH=src
export AOE_FRONTEND_OUT_DIR="$(pwd)/src/frontend/out"
uvicorn app.main:app --port 8000
```

## Databricks deploy

```bash
./deploy_app.sh
# optional: ./deploy_app.sh arango-workflow-app "" <profile>
```

Or use `databricks apps deploy` after `databricks sync . /Workspace/Users/<you>/arango-workflow-app`.

Runtime command (see `app.yaml`): `scripts/start-databricks-app.sh` with `PYTHONPATH=src`.

## Related repos

- [arango-dashboard-app](../arango-dashboard-app/) — layout reference (Flask)
- [arango-ontoextract](../arango-ontoextract/) — OntoExtract source
- [arango-gateway-app](../arango-gateway-app/) — Arango proxy + databricks-graph
- [arango-mcp-app](../arango-mcp-app/) — Genie / MCP
