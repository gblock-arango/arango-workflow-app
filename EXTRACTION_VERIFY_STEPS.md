# Extraction verification — one step at a time

Run **pytest** and **npm test** before every deploy. After deploy, verify in the UI in this order.

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

## Step 5 — Materialize + agents

Only after Steps 1–4 pass. First run may take minutes on schema migrations.

---

## Failure pattern (e.g. run_702a2704e855)

| Symptom | Root cause | Step |
|---------|------------|------|
| Poll failed (87): signal timed out | Status poll hit Arango / thread pool | **1** |
| Old Diagnostics labels | Stale `src/frontend/out/` | **3** |
| No stage movement | Cache wrote to `/Volumes` not Files API | **2** |
