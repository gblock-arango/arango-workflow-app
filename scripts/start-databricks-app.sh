#!/usr/bin/env bash
# Single-process entry for Databricks Apps: FastAPI BFF + OntoExtract API + Next static export.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${DATABRICKS_APP_PORT:-8000}"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -d "${ROOT}/src/frontend/out" ]]; then
  export AOE_FRONTEND_OUT_DIR="${ROOT}/src/frontend/out"
fi

# Use BACKEND_WORKERS (app.yaml) or default to min(4, vCPU count). More workers help when
# SQL warehouse / Files API calls block threads; static UI is still served from one process tree.
WORKERS="${BACKEND_WORKERS:-}"
if [[ -z "${WORKERS}" ]]; then
  WORKERS="$(nproc 2>/dev/null || echo 2)"
  if [[ "${WORKERS}" -gt 4 ]]; then
    WORKERS=4
  fi
  if [[ "${WORKERS}" -lt 1 ]]; then
    WORKERS=1
  fi
fi
echo "Starting uvicorn with --workers ${WORKERS} (set BACKEND_WORKERS to override)"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --workers "${WORKERS}"
