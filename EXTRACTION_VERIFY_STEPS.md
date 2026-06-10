# Extraction verification — one step at a time

Run **pytest** and **npm test** before every deploy. After deploy, verify in the UI in this order.

## Step −1 — Permissions pre-check (local CLI, before deploy)

Confirm the **workflow app service principal** (`94364b27-…` from `databricks apps get arango-workflow-app`) has what each extraction step needs. These checks do **not** require a redeploy.

| Extraction step | Permission needed | How to verify (live) |
|-----------------|-------------------|----------------------|
| **4** Gateway `/health` + Arango proxy | **CAN_USE** on **target** app for workflow SP (not only `app.yaml` on caller) | `databricks apps get-permissions arango-gateway-app` lists workflow `service_principal_client_id` with **CAN_USE**. Request-path startup-status can work via user token even when this grant is missing. |
| **4–5** UC registry URL resolution | **SELECT** on `arango_gateway_registry`, `arango_connection_registry`, `arango_agent_registry` | `SHOW GRANTS ON TABLE workspace.default.arango_gateway_registry` includes workflow SP |
| **2** Run-progress cache | **READ/WRITE VOLUME** on `workspace.default.arango_workflow_volume` | `SHOW GRANTS ON VOLUME workspace.default.arango_workflow_volume` includes workflow SP |
| **5** Materialize | **READ/WRITE VOLUME** + **SELECT** on `workspace.default` schema (`embedding_status`) | Same volume grants; schema **SELECT** on `workspace.default` |
| **5** LangGraph agents | **CAN_QUERY** on `AUTOGRAPH_LLM_MODEL_NAME` + `AUTOGRAPH_EMBEDDING_MODEL_NAME` | `AUTOGRAPH_*=… PYTHONPATH=src python3 scripts/ensure_serving_endpoints.py` → both `state.ready='READY'` |
| Browser BFF (Genie proxy) | **User authorization** + `user_api_scopes` on workflow app | `databricks apps get arango-workflow-app` shows `user_api_scopes`; startup-status shows `x_forwarded_access_token_present: true` |

Quick script bundle (from `arango-workflow-app/`):

```bash
# App SP + user scopes
databricks apps get arango-workflow-app -o json | python3 -c \
  'import json,sys; d=json.load(sys.stdin); print("sp:", d["service_principal_client_id"]); print("user_api_scopes:", d.get("user_api_scopes"))'

# UC grants (warehouse id from app.yaml)
databricks api post /api/2.0/sql/statements --json \
  '{"warehouse_id":"473d40703241ee4c","statement":"SHOW GRANTS ON VOLUME workspace.default.arango_workflow_volume","wait_timeout":"30s","format":"JSON_ARRAY"}'

# Serving endpoints READY
AUTOGRAPH_LLM_MODEL_NAME=databricks-meta-llama-3-3-70b-instruct \
AUTOGRAPH_EMBEDDING_MODEL_NAME=databricks-bge-large-en \
PYTHONPATH=src python3 scripts/ensure_serving_endpoints.py

# Peer URLs resolve
PYTHONPATH=src python3 scripts/print_effective_peer_urls.py

# Peer-app CAN_USE (M2M) — workflow SP must be on *gateway* app ACL
WF_SP="$(databricks apps get arango-workflow-app -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["service_principal_client_id"])')"
databricks apps get-permissions arango-gateway-app -o json | python3 -c \
  "import json,sys; sp='${WF_SP}'; d=json.load(sys.stdin); print('gateway CAN_USE for workflow SP:', any(sp in str(e.get('service_principal_name','')) for e in d.get('access_control_list',[])))"

# Repair if false (no app redeploy required):
# PYTHONPATH=src python3 scripts/grant_peer_app_can_use.py --app-name arango-workflow-app
```

**2026-06-10:** Gateway `/health` 401 with working startup-status was missing **CAN_USE on arango-gateway-app** for workflow SP `94364b27-…` (fixed via `grant_peer_app_can_use.py`; wired into `deploy_app.sh`).

## Step 0 — Tests (local, before deploy)

```bash
cd arango-workflow-app
python3 -m pytest tests/unit/test_run_status_poll.py \
  tests/unit/test_run_progress_cache.py \
  tests/unit/test_run_progress_cache_files_api.py \
  tests/unit/test_begin_extraction_run.py \
  tests/unit/test_extraction_gateway_checkpoints.py -q

cd src/frontend && npm test -- --testPathPattern="extractionDiagnostics|runStatusPoll"
```

All must pass.

## Step 1 — Status poll never blocks (backend)

**Tests:** `test_get_run_status_never_calls_run_sync`, `test_poll_never_calls_gateway`

**Deploy check:** Start a run → poll count increases **without** `signal timed out` spam.  
Even if cache is empty, status returns `preparing` (not 404, not 12s hang).

## Step 2 — Cache on Databricks (Files API)

**Test:** `test_run_progress_cache_files_api.py`

Production uses **UC Files API** (`UC_WORKFLOW_DATA_IO_MODE=auto`), not direct `/Volumes` writes.  
Cache path: `workflow-data/instance_data/run-progress/run_<id>.json`

**Deploy check:** After Start, file appears under that prefix in the volume (UC browse).

## Step 3 — Frontend bundle (must rebuild)

**Test:** `extractionDiagnostics.test.ts` — source contains `Gateway /health`

**Deploy check:** `./deploy_app.sh` must run `npm run build` (see `logs/frontend-build.log`).  
If UI still shows **“Worker started”** / **“Run queued”** old labels → frontend not rebuilt.

## Step 4 — Gateway checkpoints (backend prepare thread)

**Test:** `test_extraction_gateway_checkpoints.py`

**Deploy check:** Diagnostics shows **Gateway checkpoints** log and stages:  
`Gateway /health` → `Arango session` → `Run in Arango` → `Materialize…`

During **Materialize**, expect sub-messages at least every ~10s: staging → UC read → chunk insert progress.  
During **Schema migrations**, expect `Migration N/M: 00N_…` lines (20 numbered migrations under `src/migrations/`).

| Migration | Purpose (summary) |
|-----------|-------------------|
| `001_initial_collections` | Core collections (`documents`, `chunks`, `extraction_runs`, …) |
| `002_versioned_vertices` | Temporal vertex collections |
| `003_edge_collections` | Edge collections |
| `004_named_graphs` | Named graphs |
| `005_mdi_indexes` | MDI indexes |
| `006_ttl_indexes` | TTL indexes |
| `007_arangosearch_views` | ArangoSearch views |
| `008_vector_indexes` | Vector indexes |
| `009_er_collections` | Entity resolution collections |
| `010_process_graph` | Process graph |
| `011_all_ontologies_graph` | All-ontologies graph |
| `015_library_search` | Library search |
| `017_pgt_collections` | PGT collections |
| `018_migrate_properties` | Property migration |
| `019_backfill_expired_sentinel` | Temporal backfill |
| `020_repair_mdi_temporal_indexes` | MDI temporal repair |
| `021_ontology_releases` | Ontology releases |
| `022_quality_history` | Quality history |
| `023_repair_orphan_object_property_ranges` | Orphan range repair |
| `024_revision_meta_collection` | Revision meta |

## Step 5 — Materialize + agents

Only after Steps 1–4 pass. First run may take minutes on schema migrations.

---

## Failure pattern (e.g. run_702a2704e855)

| Symptom | Root cause | Step |
|---------|------------|------|
| Poll failed (87): signal timed out | Status poll hit Arango / thread pool | **1** |
| Old Diagnostics labels | Stale `src/frontend/out/` | **3** |
| No stage movement | Cache wrote to `/Volumes` not Files API | **2** |
| Gateway `/health` HTTP 401 (startup-status OK) | Workflow SP lacks **CAN_USE** on `arango-gateway-app` | **−1**, **4** |
