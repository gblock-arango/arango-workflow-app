# Pipeline follow-up checklist

Medium and high priority issues identified during extraction pipeline review (post materialize-to-Arango). Items marked **fixed** in this session are noted for verification after redeploy.

---

## High priority

| # | Issue | Impact | Suggested fix |
|---|--------|--------|----------------|
| H1 | **Multi-worker WebSocket events** — broadcaster is in-memory per uvicorn worker; WS may connect to a worker that never receives pipeline events | Agent DAG shows all steps pending despite run progressing | **Mitigated:** REST poll + file cache (`RUN_PROGRESS_CACHE_DIR`) + incremental `step_logs`; optional Redis for WS fan-out if scaling further |
| H2 | **`EXTRACTION_PASSES` vs `EXTRACTION_CONSISTENCY_THRESHOLD` mismatch** — e.g. passes=1 + threshold=2 yields zero classes passing consistency | Run completes with empty ontology / failed consistency | Fail-fast at startup if `threshold > passes`; document in `app.yaml`. Verify threshold is `"1"` when passes=1 |
| H3 | **`target_ontology_id` not passed into `run_pipeline`** | ER agent and belief revision skip when re-extracting into existing ontology | Thread `target_ontology_id` from run record into pipeline state / ER node |
| H4 | **No real curation gate despite `interrupt_after_filter=True`** | `execute_run` writes to graph immediately; filter pause is cosmetic | Either honor LangGraph interrupt and defer graph writes, or remove interrupt flag and document auto-commit behaviour |
| H5 | **Llama 70B JSON reliability at high concurrency** | Extractor passes fail intermittently on large docs | Lower `EXTRACTION_CONCURRENCY`; add JSON repair retry; consider smaller/faster model for structured extraction |

---

## Medium priority

| # | Issue | Impact | Suggested fix |
|---|--------|--------|----------------|
| M1 | **RAG uses first chunk embedding only** | Weak retrieval context for multi-chunk documents | Aggregate top-k chunk embeddings or query per-chunk and merge |
| M2 | **No vector index on materialize path** | Chunk vector search slow or unused at extraction time | Create ArangoSearch / vector index when materializing chunks |
| M3 | **`_annotate_confidence_tiers` / `_add_provenance` are no-ops** | Filter stage does not tier or annotate confidence | Implement or remove dead code paths |
| M4 | **`EXTRACTION_CONFIDENCE_MIN` unused** | Config suggests filtering that never runs | Wire into filter agent or remove from config |
| M5 | **Belief revision not shown on frontend DAG** | Backend node `belief_revision` maps awkwardly to UI steps | Add dedicated DAG node or document as sub-phase of quality judge |
| M6 | **Status poll timeout under load** | “Poll failed (50): signal timed out” during long runs | **Fixed:** lightweight `/status` endpoint + 12s timeout + amber “API busy” messaging; verify after redeploy |
| M7 | **Start extraction button re-enabled during active run** | User can queue duplicate runs | **Fixed:** disable button while selected run is preparing/running |
| M8 | **Agent DAG REST fallback skipped when WS open** | Wrong-worker WS shows “Live” but no step updates | **Fixed:** REST poll continues when WS is connected but silent >15s |
| M9 | **`step_logs` only written at end of pipeline** | REST/WS-less UI blind during agent phase | **Fixed:** `record_run_step_event` appends logs on step_started/completed/failed |

---

## Verify after redeploy

1. Start extraction on `10k-excerpt-acme.md` — preparation steps advance through **Launch agents**.
2. Diagnostics shows **running** (not stuck on poll timeout spam); amber message only if API is genuinely busy.
3. Agent DAG nodes tick from pending → running → completed (via WS or REST within ~2s).
4. **Start extraction** button shows **Extraction in progress…** and is disabled until run completes.
5. Arango `extraction_runs.stats.step_logs` grows during agent phase (not only at end).

---

## Deployment

```bash
cd arango-workflow-app && ./deploy_app.sh
```

Allow ~5 minutes for Databricks Apps to roll out.
