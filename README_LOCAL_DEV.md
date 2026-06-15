# Local development (Arango platform apps)

This document defines how **arango-gateway-app**, **arango-mcp-app**, and **arango-workflow-app** run on a developer laptop versus on Databricks Apps. It applies to all three repos; workflow-app hosts this file as the shared reference.

It is based on a **code review** of the three repos (as of the current tree): what works today, what **`TEST_DEPLOYMENT_MODE=local_dev`** must change, and how **Unity Catalog permissions** behave when apps run locally.

---

## Summary

- **One switch per repo:** `TEST_DEPLOYMENT_MODE` in each repo’s **`app.yaml`** drives **all** runtime branching via `deployment_profile` (peer URLs, workflow-data I/O, Arango registry, outbound Bearer, LLM provider). No scattered `LOCAL_*` toggles.
- **`local_dev`:** app processes on **localhost**, Arango on **Minikube**, **workflow-data on disk** under `local_dev/workflow-data/`; **Unity Catalog Delta tables, SQL warehouse, Model Serving, and Genie remain remote** (Databricks CLI auth); **OpenAI** for Autograph extraction and embeddings.
- **`self_managed_platform`:** cloud deploy via `deploy_app.sh` → Databricks Apps, service principals, UC peer registries, Files API.
- **Entrypoint:** `app.yaml` `command` → `scripts/start-app.sh`; **`./deploy_app.sh`** runs locally or deploys depending on mode.

We do **not** emulate Databricks. Local apps call **real** workspace APIs where the platform has no laptop substitute.

### Operator contract (what is *not* in `app.yaml`)

| Prerequisite | Why |
|--------------|-----|
| `databricks auth login` (or `DATABRICKS_HOST` + token in env) | All `WorkspaceClient()` / `execute_sql` calls |
| `export OPENAI_API_KEY=…` in shell before `./deploy_app.sh` | Autograph LLM + embeddings in `local_dev` (forced OpenAI) |
| Minikube Arango running (`https://127.0.0.1:18529`) | Gateway → Arango path |
| Same `TEST_DEPLOYMENT_MODE: "local_dev"` in **all three** `app.yaml` files | Profile constants must agree across repos |

Everything else — ports, peer URLs, filesystem roots, skip UC publish, Minikube registry row, no localhost Bearer — comes from **`TEST_DEPLOYMENT_MODE` alone** once `deployment_profile` is implemented.

---

## The single flag

In **each** repo’s `app.yaml`:

```yaml
env:
  - name: TEST_DEPLOYMENT_MODE
    description: >-
      local_dev = laptop (localhost peers, Minikube Arango, local workflow-data).
      self_managed_platform = Databricks Apps (UC peer registries, Files API, app SP).
    value: "local_dev"   # or "self_managed_platform" for cloud deploy

command:
  - "bash"
  - "-lc"
  - "export PYTHONPATH=src && bash scripts/start-app.sh"
```

| Mode | `./deploy_app.sh` | Process identity |
|------|-------------------|------------------|
| `local_dev` | `build-local.sh` → `start-local-dev.sh` (no sync/deploy) | **Your CLI user** (`databricks auth login`) |
| `self_managed_platform` | `databricks sync` + `apps deploy` | **App service principal** (per deploy) |

Legacy alias `local_docker` → `local_dev` in workflow `config.py`.

### What stays in `app.yaml` vs what profile overrides

| `app.yaml` key | Read in `local_dev`? | Effective behavior |
|----------------|----------------------|--------------------|
| `TEST_DEPLOYMENT_MODE` | **Yes — master switch** | Drives entire profile |
| `DATABRICKS_SQL_WAREHOUSE_ID` | Yes | Tier B SQL (registries, `embedding_status`, annotations) |
| `EMBEDDING_STATUS_TABLE` | Yes | Remote Delta table name |
| `AUTOGRAPH_LLM_PROVIDER` / `*_MODEL_NAME` | Read but **overridden** | Profile forces OpenAI; model names used as OpenAI ids |
| `ARANGO_*_REGISTRY_TABLE` | Yes | Peer registries **not queried** for URLs in local_dev; connection registry optional |
| `ARANGO_GATEWAY_BASE_URL` etc. | Ignored when local | Profile localhost URLs win |
| `GENIEMCP_SERVING_ENDPOINT` | Yes (mcp app) | Remote serving — unchanged |
| `OPENAI_API_KEY` | Shell only (empty in git) | Required for Autograph in local_dev |

Do **not** add parallel env vars like `USE_LOCAL_WORKFLOW_DATA=true` — extend `deployment_profile` instead.

---

## Identity and UC permissions (`local_dev`)

### Who calls Databricks?

| Runtime | `WorkspaceClient()` / `execute_sql` runs as |
|---------|---------------------------------------------|
| Databricks Apps (`self_managed_platform`) | App **service principal** (grants from `deploy_app.sh`) |
| Laptop (`local_dev`) | **Human developer** (CLI OAuth / PAT from `databricks auth login`) |

`deploy_app.sh` grants (workflow example) apply to the **deployed app SP**, not to your laptop session:

- `GRANT USE CATALOG` / `USE SCHEMA` on `workspace.default`
- `GRANT SELECT`, `MODIFY` on registry Delta tables
- `GRANT SELECT`, `MODIFY` on schema (UC Add Tables / annotations)
- `GRANT READ VOLUME`, `WRITE VOLUME` on `arango_workflow_volume`
- `GRANT CAN_USE` on peer Apps (gateway, mcp)
- Model serving `CAN_QUERY` (Autograph endpoints)

**For `local_dev`, the same operations still work if your user has equivalent (or broader) workspace permissions.** The platform does not require a separate “local UC emulator.” Typical needs:

| Operation | API | Minimum user privilege (dev workspace) |
|-----------|-----|--------------------------------------|
| List/browse UC tables (Add Tables UI) | `WorkspaceClient.catalogs` / `schemas` / `tables` | `USE CATALOG`, `USE SCHEMA`, `SELECT` on target schema(s) |
| Read table/column metadata | `tables.get` | Same |
| Save UC comments (annotations) | `execute_sql` `COMMENT ON TABLE` / `ALTER COLUMN` | `MODIFY` on schema |
| SQL registry read/write | `execute_sql` on `*_registry` tables | `SELECT` / `MODIFY` on those tables (often skipped in `local_dev` for **peer** registries — see below) |
| Workflow-data files (target local) | Local filesystem | **No UC volume grant** |
| Workflow-data (today’s code path) | `WorkspaceClient.files.upload/download` | `READ VOLUME`, `WRITE VOLUME` on `arango_workflow_volume` if Files API is used |
| MCP chat LLM | OpenAI client → `{host}/serving-endpoints` | `CAN QUERY` (or equivalent) on `GENIEMCP_SERVING_ENDPOINT` |
| Genie spaces | Genie API via SDK | Genie / workspace permissions for your user |
| SQL warehouse statements | `statement_execution.execute_statement` | `CAN USE` on warehouse id in `app.yaml` |

**One-time laptop setup:** run cloud deploy at least once (as `self_managed_platform`) so UC tables/volumes exist, **or** create them manually. Then use a dev account with catalog/schema/volume access. Missing grants surface as SDK/SQL errors in app logs — same as any local Databricks script.

**What does not apply locally:** App SP `CAN_USE` on `*.databricksapps.com` (peers are `http://127.0.0.1:*`). `set_user_api_scopes.sh` / OBO headers are irrelevant for localhost peer calls once `deployment_profile` disables outbound Bearer between local apps.

---

## UC and volume: what stays remote in `local_dev`

These pathways **keep using the remote workspace** in both modes (only the **caller identity** changes):

| Feature | Code location | Remote API |
|---------|---------------|------------|
| UC table list/search | `workflow` `uc_catalog.list_uc_tables` | `WorkspaceClient.catalogs.list` … |
| UC table detail | `uc_catalog.get_uc_table_detail` | `tables.get` |
| UC annotations Save | `uc_catalog.save_uc_table_annotations` | `execute_sql` (warehouse) |
| UC entity selections (anchor) | `uc_entity_selections` → `UC_anchor_prompt` | Selections stored in **workflow-data**; catalog browse remote |
| UC graph extract (gateway) | `datahub_unity_catalog_workflow` | `WorkspaceClient` catalog API |
| Embedding status Delta | `embedding_status.py` | `execute_sql` MERGE/SELECT |
| Genie registry / provision | `mcp` `genie_registry.py` | SQL + Genie API |
| MCP orchestrator LLM | `genie_mcp_orchestrator.py` | `{DATABRICKS_HOST}/serving-endpoints` |
| Model serving probe (deploy) | `ensure_serving_endpoints.py` | Serving API |

**Workflow-data volume (files on UC):** Target `local_dev` profile uses **`local_dev/workflow-data/`** (no `READ/WRITE VOLUME` needed for that path). **Current code** (before `deployment_profile`) still treats `local_dev` like a cluster for I/O: `use_files_api_for_io()` returns **true** when there is no `/Volumes/...` mount (see `workflow_data_volume.py` — only `local_docker` / `local` skip Files API). Until profile lands, laptop may still hit **Files API** and needs user **WRITE VOLUME** for uploads/profiles/run-progress.

---

## What `local_dev` changes (target `deployment_profile`)

These are **not fully implemented today**; they are required so a single flag drives behavior without extra env vars.

| Concern | `self_managed_platform` (today) | `local_dev` (target) |
|---------|--------------------------------|----------------------|
| Gateway URL | UC `ARANGO_GATEWAY_REGISTRY_TABLE` or `ARANGO_GATEWAY_BASE_URL` | Fixed `http://127.0.0.1:8001` |
| MCP URL | UC `ARANGO_AGENT_REGISTRY_TABLE` or env | Fixed `http://127.0.0.1:8002` |
| Workflow URL (for MCP `/mcp/aoe`) | UC `ARANGO_WORKFLOW_REGISTRY_TABLE` | Fixed `http://127.0.0.1:8010` |
| Publish self URL to UC | gateway / mcp / workflow startup | **Skip** |
| Arango host for gateway | UC `ARANGO_REGISTRY_TABLE` SQL row | Static Minikube row (`127.0.0.1:18529`, TLS verify off) |
| Connection → registry upsert | SQL `MODIFY` on connection registry | Optional: skip or write row for other developers only |
| Workflow-data I/O | Files API or `/Volumes` mount | **`local_dev/workflow-data/`** filesystem |
| Run progress cache | Files API or `/tmp` | `local_dev/workflow-data/instance_data/run-progress/` or `/tmp` |
| Peer HTTP Bearer | M2M / user OBO to `*.databricksapps.com` | **No** `Authorization` header to localhost |
| Autograph extraction/embeddings | OpenAI or Databricks serving per `app.yaml` | **Force OpenAI** (`use_databricks_for_*` → false when `is_local`) |
| Gateway inbound auth | None today | None (unchanged) |

---

## Inter-app communication pathways

### Overview

```text
                    ┌─────────────────────────────────────────┐
                    │     Databricks workspace (remote)        │
                    │  UC APIs · SQL warehouse · Serving · Genie │
                    └──────────────▲──────────────▲────────────┘
                                   │              │
         CLI OAuth / PAT           │              │
                                   │              │
  Browser ──▶ workflow :8010 ──────┼──────────────┼──▶ mcp :8002
              (Next :3000)         │              │      /api/genie-mcp/chat
                   │               │              │           │
                   │  BFF proxy    │              │           └──▶ serving-endpoints
                   ├───────────────┘              │
                   │  /api/workflow/*               │
                   ▼                                │
              gateway :8001 ◀───────────────────────┘
                   │         (tools + optional Bearer: off locally)
                   ▼
              Minikube Arango :18529
```

### 1. Workflow → Gateway (Arango I/O)

| Step | Code | `local_dev` notes |
|------|------|-------------------|
| Resolve URL | `effective_gateway_base_url()` → `gateway_config.effective_gateway_url()` | **Must** return `http://127.0.0.1:8001` (profile); today needs env or UC row |
| HTTP | `GatewayArangoClient` → `POST /api/arango/http` | Sends `outbound_databricks_auth_headers()` today; profile should send **no** Bearer to localhost |
| Gateway → Arango | `get_active_registry_row()` + `ping_arango_endpoint` | Profile: static Minikube row; auth via `ARANGO_PING_BASIC_AUTH_*` or local profiles file |
| Readiness UI | `gateway_startup_status`, `/ready` | `GET http://127.0.0.1:8001/api/debug/startup-status` |

### 2. Workflow → MCP (Genie / MCP chat)

| Step | Code | `local_dev` notes |
|------|------|-------------------|
| Resolve URL | `effective_arango_agent_base_url()` | Profile: `http://127.0.0.1:8002` |
| Proxy | `workflow_dashboard._proxy_json` → `/api/genie-mcp/chat`, `/api/genie/chat` | Forwards `outbound_databricks_auth_headers()`; unnecessary locally |
| MCP handler | `genie_mcp_orchestrator.ask_genie_mcp_conversation_sync` | Tools in-process; LLM → **remote** serving |
| Startup status | `workflow_dashboard` merges mcp `/api/debug/startup-status` | Optional gateway fragment from localhost |

### 3. MCP → Gateway (Arango tools)

| Step | Code | `local_dev` notes |
|------|------|-------------------|
| Resolve URL | `effective_gateway_base_url(current_app.config)` | Profile: `http://127.0.0.1:8001` |
| HTTP auth | `outbound_bearer_authorization_header()` in `databricks_app_http_auth.py` | May attach workspace Bearer; gateway **does not enforce** inbound app auth today |
| Tools | `arango_connector` / `gateway_arango_client` | Same HTTP proxy path as workflow |

### 4. MCP → Workflow (OntoExtract `/mcp/aoe`)

| Step | Code | `local_dev` notes |
|------|------|-------------------|
| Resolve URL | `workflow_url_registry` / `ARANGO_WORKFLOW_APP_BASE_URL` | Profile: `http://127.0.0.1:8010` |
| HTTP | `aoe_ontoextract_mcp/workflow_client.py` | Uses `outbound_bearer_authorization_header()`; disable for localhost |

### 5. Gateway ↔ Workflow-data (connection profiles)

| Step | Code | `local_dev` notes |
|------|------|-------------------|
| Workflow saves profiles | `arango_connection_profiles` → `workflow_data_volume` | Target: `local_dev/workflow-data/settings/arango_connection_profiles.json` |
| Gateway reads auth | `workflow_profile_store.read_bytes` → `arango_basic_auth.resolve_arango_basic_auth` | Same relative path; **both repos must share the same root** (workflow repo path or symlink) |
| Connect upsert | `upsert_registry_for_profile` → `execute_sql` on `ARANGO_REGISTRY_TABLE` | **Skipped or optional** in local_dev if Arango routing is static Minikube |

### 6. UC anchor (workflow only)

| Step | Code | Remote? |
|------|------|---------|
| Browse tables | `GET /api/v1/uc/tables` → `uc_catalog.list_uc_tables` | **Yes** — `WorkspaceClient` |
| Save selections | `uc_entity_selections.save` → workflow-data JSON | **Local file** (target); drives `UC_anchor_prompt` in extraction |
| Push comments to UC | `save_uc_table_annotations` → `execute_sql` | **Yes** — needs user `MODIFY` on schema |

---

## Data planes (three storage tiers)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Tier A — Local disk (local_dev only)                                     │
│   local_dev/workflow-data/                                               │
│     uploads/<doc-id>/raw + parsed.json + chunks.jsonl + embeddings.jsonl │
│     settings/arango_connection_profiles.json                             │
│     settings/uc_entity_selections.json                                   │
│     settings/kubeconfig/ …                                               │
│     instance_data/run-progress/run_*.json                                │
│     builtin/<domain>/… (seeded from repo datasets/)                      │
└─────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────┐
│ Tier B — Remote UC Delta (both modes; CLI user locally, app SP in cloud) │
│   workspace.default.embedding_status                                       │
│   workspace.default.arango_*_registry (peer URLs; skipped in local_dev)  │
│   workspace.default.arango_connection_registry (optional in local_dev)   │
│   Annotations via COMMENT ON TABLE/COLUMN                                │
└─────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────┐
│ Tier C — Minikube Arango (local_dev) / cluster (cloud)                   │
│   documents, chunks, extraction_runs, ontology_* collections             │
│   All I/O via gateway POST /api/arango/http                              │
└─────────────────────────────────────────────────────────────────────────┘
```

**Rule:** Tier A paths are **never** UC volume paths in `local_dev`. Tier B always uses `execute_sql` / `WorkspaceClient`. Tier C is always **gateway-mediated** — workflow and mcp never open a direct `python-arango` connection in platform mode.

---

## UC inventory (tables, volumes, APIs)

| Asset | Env key | Used by | `local_dev` | `self_managed_platform` |
|-------|---------|---------|-------------|-------------------------|
| `embedding_status` Delta | `EMBEDDING_STATUS_TABLE` | workflow ingest + extraction gate | Remote SQL (CLI user) | Remote SQL (app SP) |
| `arango_connection_registry` | `ARANGO_REGISTRY_TABLE` | gateway routing; workflow Connect upsert | **Static Minikube row** (profile); Connect upsert optional | SQL row from Connect |
| `arango_gateway_registry` | `ARANGO_GATEWAY_REGISTRY_TABLE` | workflow, mcp peer URL | **Skipped** — profile URL | Published at gateway startup |
| `arango_agent_registry` | `ARANGO_AGENT_REGISTRY_TABLE` | workflow BFF | **Skipped** — profile URL | Published at mcp startup |
| `arango_workflow_registry` | `ARANGO_WORKFLOW_REGISTRY_TABLE` | mcp OntoExtract tools | **Skipped** — profile URL | Published at workflow startup |
| `arango_bronze_simulated_injector_registry` | (workflow platform config) | dashboard bronze demos | Remote SQL read (optional) | Remote SQL read |
| UC catalog tables/columns | — | Add Tables UI, annotations | Remote `WorkspaceClient` | Remote |
| `arango_workflow_volume` / workflow-data | `UC_GRAPH_VOLUME_NAME` | cloud file I/O | **Not used** — Tier A disk | Files API or `/Volumes` mount |
| Model serving endpoints | `GENIEMCP_SERVING_ENDPOINT`, `AUTOGRAPH_*` | mcp chat; cloud Autograph | mcp: remote; Autograph: **OpenAI** | Per `app.yaml` |
| Genie spaces | mcp `genie_registry` | `/api/genie/chat` | Remote Genie API | Remote |

---

## End-to-end scenario map

Each scenario lists: **trigger → code path → data tier → identity → `local_dev` branch**.

### Scenario A — Document upload and staging

| Step | Detail |
|------|--------|
| **Trigger** | UI `POST /api/v1/documents` (multipart) or volume ingest `POST …/ingest-from-volume` |
| **Code** | `api/documents.py` → `workflow_data.persist_upload` → `workflow_data_volume.save_upload` |
| **Writes** | Tier A: `uploads/<doc-id>/<filename>` |
| **Registry** | `_register_embedding_row` → `embedding_status.register_document` → Tier B Delta MERGE |
| **Identity** | Files: local process; SQL: CLI user |
| **`local_dev` branch** | `deployment_profile.local_workflow_data_root()` + `use_files_api_for_io() → false` for `local_dev` |
| **Cloud delta** | Same paths under UC volume via Files API |

Startup may seed **builtin** corpora: `workflow_data.seed_builtin_if_configured` → `seed_builtin_datasets_from_bundle` (repo `datasets/` → `builtin/`). Works on Tier A filesystem when profile fixes I/O mode.

### Scenario B — Parse → chunk → embed pipeline

| Step | Detail |
|------|--------|
| **Trigger** | UI Documents page batch actions or auto pipeline after upload |
| **API** | `POST /api/v1/embedding/pipeline/batch` or document-level background task |
| **Orchestrator** | `services/embedding_pipeline.py` |
| **Stages** | `run_parse_stage` → `run_chunk_stage` → `run_embed_stage` |
| **Parse** | `ingestion.parse_*` (PDF/DOCX/PPTX/MD); writes `uploads/<doc-id>/parsed.json` |
| **Chunk** | `ingestion.chunk_document`; writes `chunks.jsonl` |
| **Embed** | `services/embedding.embed_texts` via OpenAI async client |
| **Status** | Each stage updates Tier B `embedding_status` (`parsing` → `parsed` → `chunking` → `embedding` → `ready`) |
| **LLM** | `uses_databricks_serving_for_embeddings()` → **`false` when `is_local`** (`config.use_databricks_for_embeddings`) → OpenAI + `OPENAI_API_KEY` |
| **Model** | `effective_embedding_model_name()` → `AUTOGRAPH_EMBEDDING_MODEL_NAME` as OpenAI id (e.g. `text-embedding-3-small`) when profile forces provider |
| **Arango** | **None** — pipeline is UC-volume + Delta only until extraction |

```text
upload ──▶ parse ──▶ chunk ──▶ embed ──▶ embedding_status=ready
           │         │          │
           └─ Tier A artifacts (parsed.json, chunks.jsonl, embeddings.jsonl)
           └─ Tier B embedding_status rows (remote SQL each stage)
```

### Scenario C — Extraction run acceptance (HTTP → background thread)

| Step | Detail |
|------|--------|
| **Trigger** | `POST /api/v1/extraction/runs` with `doc_ids` |
| **Gate** | `extraction_materialize.validate_embedding_documents_ready` — each doc must be `ready` in Tier B |
| **Thread** | `ExtractionRunService._start_run_in_thread` |
| **Auth checkpoint** | `pin_outbound_service_principal_bearer()` — **skip in `local_dev`** (no M2M to localhost gateway) |
| **Progress** | `run_progress_cache` — Tier A `instance_data/run-progress/run_<id>.json` or `/tmp/aoe-run-progress` |
| **Deferred prep** | Optional two-phase: HTTP returns `preparing`, worker runs `prepare_arango_workflow` before LangGraph |

### Scenario D — Extraction preparation (gateway + UC chunks + schema)

Executed in `extraction/prepare_arango_workflow.py` (and mirrored in LangGraph `prepare_arango_node` when not deferred).

| Checkpoint stage | Code | Tier | `local_dev` |
|------------------|------|------|-------------|
| `gateway_health` | `extraction_gateway_checkpoints.probe_gateway_health_checkpoint` → `gateway_connectivity_status` | HTTP → `127.0.0.1:8001` | Profile gateway URL; no Bearer |
| `gateway_arango` | `connect_arango_checkpoint` → `get_db()` → `GatewayArangoClient` | Tier C via gateway | Gateway uses static Minikube registry row |
| `run_persisted` | `persist_run_record_checkpoint` — insert into `extraction_runs` | Tier C | Same |
| `loading_uc_chunks` | `load_chunks_for_extraction` per doc | Tier A artifacts + Tier B status check | Reads local `chunks.jsonl` / `embeddings.jsonl` |
| `schema_migrations` | `schema_bootstrap.ensure_ontology_schema` | Tier C collections via gateway | Same |
| `launching_pipeline` | Hand off to LangGraph | — | — |

**Materialize-to-Arango (lineage, optional):** `extraction_materialize.materialize_embedding_documents_for_lineage` copies Tier A chunks into Tier C `documents`/`chunks` **before** agent runs when configured — still via gateway bulk APIs.

### Scenario E — LangGraph extraction agent pipeline

Compiled in `extraction/pipeline.py`. All LLM nodes call `extractor._get_llm` → OpenAI when `is_local`.

| Node | Purpose | External deps |
|------|---------|---------------|
| `prepare_arango` | Prep wrapper (may no-op if deferred) | gateway, Tier A/B |
| `strategy_selector` | Pass / domain strategy | OpenAI |
| `extractor` | N-pass batched chunk extraction | OpenAI |
| `consistency_checker` | Cross-pass agreement | OpenAI |
| `quality_judge` | Qualitative eval (map/reduce over chunks) | OpenAI |
| `er_agent` | Entity resolution vs existing ontology | OpenAI + Tier C AQL via gateway |
| `belief_revision` | Merge with prior beliefs | OpenAI |
| `filter` | Pre-curation filter | OpenAI |
| `finalize_graph` | Persist to graph | Tier C via `extraction_persist` |

**UC anchor in prompts:** `format_uc_entities_for_prompt()` reads Tier A `settings/uc_entity_selections.json` (table/column picks from remote browse UI).

**Domain context:** `serialize_multi_domain_context` — Tier C AQL for selected ontology graphs.

**WebSocket / polling:** `run_progress_cache` + optional WS event bus; cache dir follows workflow-data profile.

### Scenario F — Graph materialization (post-extraction)

| Step | Code | Storage |
|------|------|---------|
| Persist classes/properties/edges | `extraction._materialize_to_graph` | Tier C ontology collections |
| Lineage edges | `extracted_from`, `has_chunk`, `produced_by` | Tier C |
| Ontology graph ensure | `ontology_graphs.ensure_ontology_graph` | Tier C |
| Quality metrics | `quality_metrics.compute_ontology_quality` | Tier C reads |

All `db.*` operations are `GatewayDatabase` proxies — no behavior change between modes except gateway URL/auth.

### Scenario G — Connection profiles and Connect

| Step | Code | Storage |
|------|------|---------|
| List/save profiles | `api/connection.py` → `arango_connection_profiles` | Tier A `settings/arango_connection_profiles.json` |
| Gateway reads password | `gateway.workflow_profile_store.load_connection_profiles_doc` | **Same Tier A path** (shared root via profile) |
| Activate / Connect | `upsert_registry_for_profile` → SQL MERGE on Tier B registry | **`local_dev`: skip or no-op** — gateway uses static Minikube row |
| Verify | `verify_gateway_arango_ping` → gateway → Arango | Minikube |

**Minikube profile defaults (profile constant):**

```text
protocol=https  host=127.0.0.1  port=18529  verify_tls=false
username=root   password=<from single-node-arango-on-minikube/.state/arango-root-password.txt>
```

Save once via Connection UI or copy password into active profile so gateway `arango_basic_auth` resolves credentials.

### Scenario H — UC Add Tables and annotations

| Action | API | Remote? |
|--------|-----|---------|
| Search/browse tables | `GET /api/v1/uc/tables` → `uc_catalog.list_uc_tables` | Yes — `WorkspaceClient` |
| Table detail | `GET /api/v1/uc/tables/{fqn}` | Yes |
| Save entity selections (anchor) | `PUT /api/v1/uc/entity-selections` | **Tier A JSON** only |
| Push comments to UC | `POST /api/v1/uc/tables/.../annotations` | Yes — `execute_sql` |

Extraction and ER agents consume anchor text from Tier A; catalog metadata always live from workspace.

### Scenario I — Workflow BFF → MCP (Genie / MCP chat)

| Step | Code |
|------|------|
| UI calls | Next.js → workflow `:8010/api/workflow/...` |
| Proxy | `api/workflow_dashboard._proxy_json` |
| Targets | `http://127.0.0.1:8002/api/genie-mcp/chat`, `/api/genie/chat`, diagnostics |
| MCP LLM | `genie_mcp_orchestrator` → remote `{DATABRICKS_HOST}/serving-endpoints/{GENIEMCP_SERVING_ENDPOINT}` |
| MCP tools | In-process → `effective_gateway_base_url` → gateway → Minikube |

`local_dev`: profile fixes mcp URL; outbound Bearer omitted for localhost.

### Scenario J — MCP OntoExtract tools → workflow

| Step | Code |
|------|------|
| HTTP tools | `aoe_ontoextract_mcp/tools_http.py` |
| Client | `workflow_client.workflow_request` → `http://127.0.0.1:8010/api/v1/...` |
| Auth | `outbound_bearer_authorization_header` — disabled for localhost in profile |

### Scenario K — Gateway UC graph export (optional)

| Step | Code | Remote? |
|------|------|---------|
| Export UC metadata to JSONL bundle | `datahub_unity_catalog_workflow` | Yes — catalog REST |
| Publish bundle to volume | `uc_graph_jsonl_bundle.publish_local_bundle_to_uc_volume` | Yes — Files API to UC volume |
| Import into Arango | workflow `graph_json_import` / ontology import jobs | Tier C via gateway |

Used for DataHub-style graph bootstrap demos; not required for core OntoExtract loop. **Unchanged in `local_dev`** except caller identity (CLI user).

### Scenario L — Admin, reset, bronze injector

| Feature | Code | `local_dev` |
|---------|------|-------------|
| Ontology reset | `api/admin.py` | Tier C via gateway |
| LLM settings UI | `api/system.py` → `llm_preferences` | Tier A JSON; profile still forces OpenAI for actual calls |
| Bronze injector URL | `bronze_injector_uc_registry` | Remote SQL read if table populated |
| Belief revision / consolidation | admin + extraction services | OpenAI + Tier C |

### Scenario M — `/ready` and diagnostics

| Endpoint | Checks |
|----------|--------|
| workflow `/ready` | gateway startup status, embedding table, optional Arango probe |
| gateway `/api/debug/startup-status` | registry row, profile auth, ping |
| mcp `/api/mcp/diagnostics` | gateway URL, workflow URL, serving endpoint reachability |

All peer URLs and registry sources follow `deployment_profile` in `local_dev`.

---

## `deployment_profile.py` (required module)

Add to each repo (identical constants or thin re-export):

```python
# workflow: src/app/workflow_platform/deployment_profile.py
# gateway: src/arango_gateway/deployment_profile.py
# mcp:     src/arango_dashboard_agent/deployment_profile.py

from enum import StrEnum

class DeploymentMode(StrEnum):
    LOCAL_DEV = "local_dev"
    SELF_MANAGED_PLATFORM = "self_managed_platform"
    MANAGED_PLATFORM = "managed_platform"

def current_mode() -> DeploymentMode: ...
def is_local_dev() -> bool: ...

# Peer URLs (override env + UC registries when is_local_dev)
def local_gateway_base_url() -> str: ...      # http://127.0.0.1:8001
def local_mcp_base_url() -> str: ...          # http://127.0.0.1:8002
def local_workflow_base_url() -> str: ...     # http://127.0.0.1:8010

def should_publish_peer_url_to_uc() -> bool: ...  # False in local_dev
def should_use_uc_files_api_for_workflow_data() -> bool: ...  # False in local_dev
def local_workflow_data_root() -> Path: ...     # <repo>/local_dev/workflow-data

def is_localhost_peer_url(url: str) -> bool: ...
def should_attach_outbound_bearer(url: str) -> bool: ...  # False for localhost peers

def static_arango_registry_row() -> dict: ...   # Minikube row for gateway
def should_upsert_connection_registry_on_connect() -> bool: ...  # False in local_dev

def force_openai_for_autograph() -> bool: ...   # True in local_dev
def should_pin_service_principal_for_extraction() -> bool: ...  # False in local_dev
```

**Integration pattern:** every call site checks `is_local_dev()` **once** at the top of registry/resolver functions — never duplicate port numbers in feature code.

**Critical fix (workflow + gateway):** in `use_files_api_for_io()`, treat `local_dev` like `local_docker`:

```python
deploy = (os.environ.get("TEST_DEPLOYMENT_MODE") or "").strip().lower()
if deploy in ("local_dev", "local_docker", "local"):
    return False
```

Today only `local_docker`/`local` skip Files API — **`local_dev` incorrectly selects Files API** when `/Volumes` is absent.

**Workflow-data root:** when `is_local_dev()`, `workflow_data_root()` returns `local_workflow_data_root()` instead of `/Volumes/.../workflow-data`. Gateway `workflow_profile_store` must use the **same absolute path** (env `LOCAL_WORKFLOW_DATA_ROOT` set by `load-app-yaml-env.sh` from profile, or symlink).

---

## Code touchpoints (implementation map)

Implement **`deployment_profile.py`** (each repo or shared) and branch these call sites:

### arango-workflow-app

| Module | Branch on `local_dev` |
|--------|------------------------|
| **`workflow_platform/deployment_profile.py`** | **New** — single source of truth (see above) |
| `workflow_platform/services/gateway_url_registry.py` | `effective_gateway_base_url`, iframe URL → profile |
| `workflow_platform/services/agent_url_registry.py` | `effective_arango_agent_base_url` → profile |
| `workflow_platform/services/workflow_url_registry.py` | Skip `publish_self_workflow_url_to_uc_if_configured` |
| `workflow_platform/workflow_data_volume.py` | `workflow_data_root()`, `use_files_api_for_io()` — **`local_dev` → filesystem** |
| `workflow_platform/databricks_outbound_auth.py` | Return `{}` when `not should_attach_outbound_bearer(url)` |
| `services/arango_connectivity.py` | Gateway ping uses profile URL |
| `services/arango_connection_profiles.py` | Skip `upsert_registry_for_profile` SQL when profile says so |
| `services/embedding_status.py` | **Unchanged** — remote Delta |
| `services/embedding_pipeline.py` | **Unchanged** — reads/writes via `workflow_data_volume` (profile fixes I/O) |
| `services/embedding.py` | **Unchanged** — OpenAI path when `force_openai_for_autograph()` |
| `services/extraction.py` | Skip `pin_outbound_service_principal_bearer` when profile says so |
| `services/extraction_gateway_checkpoints.py` | **Unchanged** — uses `get_db()` / gateway (profile fixes URL) |
| `services/extraction_materialize.py` | **Unchanged** — Tier A artifacts + Tier B gate |
| `services/run_progress_cache.py` | Filesystem under local workflow-data (via fixed `use_files_api_for_io`) |
| `services/uc_catalog.py` | **Unchanged** — remote UC |
| `services/uc_entity_selections.py` | **Unchanged** — uses `workflow_data_volume` (profile fixes root) |
| `services/llm_preferences.py` | Persist prefs to Tier A; **`config` still forces OpenAI for calls** |
| `llm/databricks_serving.py` | `uses_databricks_serving_*` respect `force_openai_for_autograph()` |
| `db/gateway_arango_client.py` | Bearer via outbound auth (profile disables for localhost) |
| `config.py` | `is_local`, `use_databricks_for_*` → false when local + force OpenAI |
| `main.py` lifespan | Skip workflow URL publish; keep `ensure_embedding_status_table` |
| `api/workflow_dashboard.py` | Proxies use profile peer URLs |
| `api/documents.py` | **Unchanged** — delegates to volume + embedding_status |
| `api/connection.py` | Connect succeeds without UC registry when profile skips upsert |
| `extraction/agents/extractor.py` | **Unchanged** — provider from `uses_databricks_serving_for_extraction()` |
| `scripts/start-app.sh`, `deploy_app.sh` | Mode switch (see shell contract) |

### arango-gateway-app

| Module | Branch on `local_dev` |
|--------|------------------------|
| **`deployment_profile.py`** | **New** — shared constants with workflow |
| `services/gateway_url_registry.py` | Skip `publish_self_gateway_url_to_uc_if_configured` |
| `services/arango_registry.py` | `get_active_registry_row` → `static_arango_registry_row()` |
| `services/workflow_profile_store.py` | `workflow_data_root()` → profile path; **`local_dev` in filesystem branch** |
| `services/arango_basic_auth.py` | Minikube password / active profile from Tier A |
| `app.py` | Background startup skips UC publish when profile says so |
| `routes/api.py` | ping/http use registry helper (already centralized) |
| `config.py` | Add `TEST_DEPLOYMENT_MODE`, `is_local` via profile |
| `services/datahub_unity_catalog_workflow.py` | **Unchanged** — remote UC (CLI user) |
| `scripts/start-app.sh`, `deploy_app.sh` | Mode switch |

### arango-mcp-app

| Module | Branch on `local_dev` |
|--------|------------------------|
| **`deployment_profile.py`** | **New** |
| `services/agent_url_registry.py` | Skip publish; `effective_agent_base_url` → profile |
| `services/gateway_url_registry.py` | Profile gateway URL |
| `services/workflow_url_registry.py` | Profile workflow URL |
| `services/databricks_app_http_auth.py` | No Bearer when `not should_attach_outbound_bearer(url)` |
| `services/genie_registry.py` | **Unchanged** — remote Genie + SQL |
| `services/genie_mcp_orchestrator.py` | **Unchanged** — remote serving (CLI user token) |
| `services/genie_workspace_client.py` | **Unchanged** — `WorkspaceClient()` = CLI user locally |
| `aoe_ontoextract_mcp/workflow_client.py` | Uses profile workflow URL + auth helper |
| `arango_mcp/arango_connector.py` | Profile gateway URL |
| `webapp.py` create_app | Skip agent URL publish when local |
| `config.py` | Add `TEST_DEPLOYMENT_MODE` |
| `scripts/start-app.sh`, `deploy_app.sh` | Mode switch |

---

## MCP serving and Genie (clarification)

`GENIEMCP_SERVING_ENDPOINT` and `TOOL_ROUTER_SERVING_ENDPOINT` are **endpoint names** in your workspace, not separate apps.

- **Accessible via mcp-app:** yes — `POST /api/genie-mcp/chat` on **`http://127.0.0.1:8002`** (workflow BFF proxies from `:8010`).
- **Where inference runs:** Databricks Model Serving (`OpenAI` client with `base_url=f"{host}/serving-endpoints"` in `genie_mcp_orchestrator.py`).
- **Where tools run:** inside local mcp-app → local gateway → Minikube.
- **Genie spaces** (`/api/genie/chat`): remote Genie API via SDK; still through local mcp-app.

Requires: valid `GENIEMCP_SERVING_ENDPOINT` in mcp `app.yaml`, `databricks auth login`, user **CAN QUERY** on that endpoint.

---

## Shared shell contract (all three repos)

| Script | Role |
|--------|------|
| `scripts/read_app_yaml_env.py` | Read `env:` values from `app.yaml` |
| `scripts/load-app-yaml-env.sh` | Export all `app.yaml` env keys (shell overrides win) |
| `scripts/start-app.sh` | `local_dev` → `start-local-dev.sh`, else `start-databricks-app.sh` |
| `scripts/start-local-dev.sh` | Repo-specific localhost run |
| `scripts/build-local.sh` | venv + npm (workflow: Next **dev**, not static export) |
| `deploy_app.sh` | If `local_dev`: build + start locally and **exit**; else cloud deploy + grants |

**Secrets:** `OPENAI_API_KEY` (workflow) remains shell/env-only; empty in git `app.yaml`.

---

## Per-repo local run

Order: **gateway → mcp → workflow** (three terminals). Set `TEST_DEPLOYMENT_MODE: "local_dev"` in all three `app.yaml` files.

| Repo | Port | `start-local-dev.sh` |
|------|------|----------------------|
| gateway | 8001 | `python app.py` or single-worker gunicorn |
| mcp | 8002 | `gunicorn asgi:app -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8002 --workers 1` |
| workflow | 8010 + Next :3000 | uvicorn `--reload` + `npm run dev` |

```bash
# Terminal 1–3
cd arango-gateway-app && ./deploy_app.sh
cd arango-mcp-app && ./deploy_app.sh
cd arango-workflow-app && ./deploy_app.sh
```

Smoke:

```bash
curl -sS -X POST http://127.0.0.1:8001/api/arango/ping | head
curl -sS http://127.0.0.1:8010/ready | head
curl -sS http://127.0.0.1:8002/api/mcp/diagnostics | head
```

---

## Cloud deploy

`TEST_DEPLOYMENT_MODE: "self_managed_platform"` → existing `./deploy_app.sh` (sync, deploy, SP grants, UC publish).

**arango-platform-bundle:** cloud only (`databricks bundle deploy -t dev`). Optional bundle variable to set `TEST_DEPLOYMENT_MODE` per target — not the laptop orchestrator.

---

## Directory layout

```text
arango-workflow-app/
  app.yaml
  deploy_app.sh
  local_dev/
    workflow-data/          # gitignored — profiles, uploads, uc_entity_selections.json
  scripts/
    load-app-yaml-env.sh
    start-app.sh
    start-local-dev.sh
    start-databricks-app.sh
    build-local.sh
    read_app_yaml_env.py
```

Gateway and mcp: same `scripts/` pattern; gateway/mcp should read **the same** `local_dev/workflow-data` path (absolute path in profile or symlink from workflow repo).

---

## Testing matrix

| Capability | `local_dev` | `self_managed_platform` |
|------------|-------------|-------------------------|
| App UI + API | Yes (localhost) | Yes (Databricks Apps URL) |
| Document upload → Tier A files | Yes (local disk) | Yes (UC Files API) |
| Parse / chunk / embed pipeline | Yes (OpenAI + Tier B SQL) | Yes (serving or OpenAI) |
| `embedding_status` Delta | Yes (CLI user) | Yes (app SP) |
| Extraction LangGraph (all nodes) | Yes (OpenAI) | Configurable LLM |
| Materialize ontology to Arango | Yes (gateway → Minikube) | Yes (gateway → cluster) |
| Run progress cache | Yes (local workflow-data or `/tmp`) | Files API or `/tmp` |
| Minikube Arango via gateway | Yes | Cluster / tunnel |
| UC table browse + anchor selections | Yes (remote UC + local JSON) | Yes |
| UC annotation Save (`COMMENT ON`) | Yes if user has MODIFY | Yes (app SP) |
| MCP `/api/genie-mcp/chat` | Yes (local mcp + remote serving) | Yes |
| Genie `/api/genie/chat` | Yes (remote) | Yes |
| MCP OntoExtract → workflow API | Yes (localhost) | Yes (UC registry URL) |
| Connection profiles shared gateway/workflow | Yes (shared Tier A root) | Yes (UC volume) |
| UC peer URL registries | Skipped (localhost URLs) | Published at startup |
| Workflow-data on UC volume | No (Tier A disk) | Files API |
| App SP `CAN_USE` between peers | N/A | Required |
| Deploy-time SQL grants | Skipped on local run | Applied to SP |

### Suggested E2E smoke (after profile ships)

1. Upload a small `.md` file → confirm row in `embedding_status` and files under `local_dev/workflow-data/uploads/`.
2. Run parse → chunk → embed → status `ready`.
3. Save UC entity selections in Add Tables → confirm `settings/uc_entity_selections.json`.
4. Activate Minikube connection profile → gateway ping OK.
5. Start extraction run → preparation checkpoints through `launching_pipeline` → completed run with classes in Arango (via gateway).
6. Open MCP chat in UI → tool call hits gateway → remote serving response.

---

## Current gaps (before `deployment_profile` ships)

Without the profile branches above, **`TEST_DEPLOYMENT_MODE=local_dev` alone does not switch behavior** except:

- workflow `config.is_local` (GAE flags, legacy `ARANGO_HOST`)
- `use_files_api_for_io()` treats **`local_dev` like cloud** (Files API if no `/Volumes` mount)

**Will fail or misroute until profile is implemented:**

- Peer discovery without `ARANGO_*_BASE_URL` env overrides (UC registry rows point at cloud URLs)
- Gateway Arango without UC connection registry row for Minikube
- Shared connection profiles if gateway/workflow use different volume roots
- Workflow → gateway Bearer may still attach SP/user token (usually harmless locally)

**Will work today on laptop** (with CLI auth + user grants):

- UC catalog list/detail/annotate
- MCP chat if mcp is running and serving endpoint is reachable
- Files API workflow-data if user has WRITE VOLUME and code path uses Files API

---

## Implementation checklist (ordered)

### Phase 1 — Profile + I/O (unblocks upload → embed)

- [ ] `deployment_profile.py` in all three repos (shared constants for ports/URLs/Minikube row)
- [ ] Fix `use_files_api_for_io()` in **workflow** and **gateway** to treat **`local_dev`** as filesystem
- [ ] `workflow_data_root()` → `local_dev/workflow-data` when `is_local_dev()`
- [ ] `LOCAL_WORKFLOW_DATA_ROOT` exported by `load-app-yaml-env.sh` (same path for gateway + workflow)
- [ ] `TEST_DEPLOYMENT_MODE` in gateway + mcp `app.yaml` (workflow already has it)

### Phase 2 — Peer routing + auth

- [ ] `effective_*_base_url` in all URL registries → profile localhost URLs
- [ ] Skip `publish_self_*_url_to_uc` in gateway / mcp / workflow startup
- [ ] `outbound_databricks_auth_headers` / `outbound_bearer_authorization_header` → no Bearer for localhost
- [ ] `get_active_registry_row` → static Minikube row in gateway
- [ ] Skip `pin_outbound_service_principal_bearer` in extraction thread when local
- [ ] Optional skip `upsert_registry_for_profile` SQL on Connect

### Phase 3 — Shell + deploy

- [ ] `scripts/load-app-yaml-env.sh`, `start-app.sh`, `start-local-dev.sh`, `build-local.sh` (all repos)
- [ ] `deploy_app.sh` local branch: build + start, no sync/deploy
- [ ] `app.yaml` `command` → `scripts/start-app.sh` (workflow still points at `start-databricks-app.sh` today)

### Phase 4 — LLM + docs

- [ ] `force_openai_for_autograph()` wired through `config.use_databricks_for_*` and `llm/databricks_serving.py`
- [ ] `scripts/grant-local-dev-user.sh` optional helper (human UC grants analog to deploy grants)
- [ ] Unit tests: `use_files_api_for_io` with `TEST_DEPLOYMENT_MODE=local_dev`, registry resolvers, outbound auth skip

### Phase 5 — Validation

- [ ] E2E smoke sequence (see Testing matrix)
- [ ] Confirm `embedding_status` and Genie/serving work under CLI user without app SP grants

---

## Messaging

> Local development runs gateway, MCP, and workflow on the developer machine with Minikube Arango and on-disk workflow-data. Unity Catalog, SQL warehouse, Model Serving, and Genie use a real Databricks workspace under the developer’s CLI identity. Production validation uses `TEST_DEPLOYMENT_MODE=self_managed_platform` on Databricks Apps with service-principal grants from `deploy_app.sh`.

---

## Related

- [README.md](./README.md)
- [../arango-gateway-app/README.md](../arango-gateway-app/README.md)
- [../arango-mcp-app/README.md](../arango-mcp-app/README.md)
- [../single-node-arango-on-minikube/README.md](../../single-node-arango-on-minikube/README.md)
