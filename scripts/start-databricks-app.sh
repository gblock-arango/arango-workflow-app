#!/usr/bin/env bash
# Single-process entry for Databricks Apps: FastAPI BFF + OntoExtract API + Next static export.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${DATABRICKS_APP_PORT:-8000}"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -d "${ROOT}/src/frontend/out" ]]; then
  export AOE_FRONTEND_OUT_DIR="${ROOT}/src/frontend/out"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --workers 1
