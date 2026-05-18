# arango-workflow-app

Unified **Databricks App** control plane ([arango-agent-autograph-job/README.md](../arango-agent-autograph-job/README.md)): FastAPI BFF + Next.js UI combining **OntoExtract** with the **arango-dashboard-app** platform layout.

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
| `/workflow` | Platform shell — Arango iframe, Databricks Graph, Genie/MCP chat |
| `/workspace`, `/pipeline`, … | OntoExtract pages |
| `/api/workflow/*` | Control-plane BFF (config, chat proxies) |
| `/api/v1/*` | OntoExtract REST API |

## Local development

**Python:** 3.11+ recommended (`pyproject.toml`). Python 3.10 works with `app/compat.py` shims (`StrEnum`, `UTC`).

```bash
# One-time: install backend dependencies
pip install -r requirements.txt

# Backend
export PYTHONPATH=src
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010

# Frontend (separate terminal)
cd src/frontend && npm install && npm run dev

# If you still see "Cannot find native binding" (npm optional-deps bug):
#   ./scripts/frontend-install.sh
#   # or: cd src/frontend && rm -rf node_modules package-lock.json && npm install
```

Open `http://localhost:3000/workflow` (or the port Next prints if 3000 is busy).

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
