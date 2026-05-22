# arango-workflow-app

Credit: Arthur Keen - this dashboard UI is based on Arthur's onto-extractor repo.  I added components for workflows associated with event recognition and GraphML (graphlet detetection and visualization), Genie Chat integration, querying Unity Catalog metadata and enriching it with graph semantics, and a framework for deploying on Databricks with the gateway and other apps.

Unified **Databricks App**: FastAPI BFF + static Next.js UI (**OntoExtract**). Genie chat is proxied to [arango-mcp-app](../arango-mcp-app/); Arango data via [arango-gateway-app](../arango-gateway-app/) only.

## Deploy (primary path)

**Config:** [`app.yaml`](app.yaml) — env vars, UC table names, peer app resources. Not `.env` (`.env` is gitignored and only for optional local overrides).

**Order:** gateway → mcp-arango-agent → this app.

```bash
# 1. Edit app.yaml (DATABRICKS_SQL_WAREHOUSE_ID, registry tables, secrets in App UI)
# 2. Set APP_SECRET_KEY + LLM keys in Databricks App environment / secrets (see app.yaml comments)

../arango-gateway-app/deploy_app.sh
../arango-mcp-app/deploy_app.sh
./deploy_app.sh
./scripts/read_uc_peer_registry.sh
```

`deploy_app.sh` will:

- Read **warehouse id and UC table names from `app.yaml`** (shell env still overrides)
- Build the Next.js static export (`src/frontend/out`)
- `databricks sync` + `apps deploy`
- Grant UC `SELECT` to the app service principal
- Publish this app’s URL to `ARANGO_WORKFLOW_REGISTRY_TABLE`

Runtime: `scripts/start-databricks-app.sh` — single **uvicorn** process serves API + static UI (no separate frontend process in Databricks).

## Makefile

**Not required for deployment.** Optional helpers:

| Target | Purpose |
|--------|---------|
| `make build-static` | Same frontend build as `deploy_app.sh` |
| `make test` | Unit tests |
| `make lint` | ruff / mypy |

There is no `make dev`, `make infra`, or `make backend` — local two-process dev was removed in favor of Databricks-only delivery.

## Layout

```text
arango-workflow-app/
  app.yaml              # Databricks Apps config (source of truth)
  deploy_app.sh         # sync + deploy + UC grants (reads app.yaml)
  scripts/start-databricks-app.sh
  src/app/              # FastAPI
  src/frontend/         # Next.js → static export at deploy time
  tests/
```

## Routes (deployed)

| Path | Description |
|------|-------------|
| `/`, `/dashboard`, … | OntoExtract UI (static export) |
| `/api/v1/*` | OntoExtract REST API |
| `/api/workflow/*` | BFF: gateway embed, Genie → mcp-app, `/ontoextract/v1` peer API |

## Related repos

- [arango-dashboard-app](../arango-dashboard-app/) — shell layout reference
- [arango-gateway-app](../arango-gateway-app/) — Arango proxy
- [arango-mcp-app](../arango-mcp-app/) — Genie / MCP + `/mcp/aoe`
