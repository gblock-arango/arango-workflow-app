#!/usr/bin/env bash
# Prepare venv + frontend deps for local_dev (no Databricks sync/deploy).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt

mkdir -p "${ROOT}/local_dev/workflow-data"

if [[ -f src/frontend/package.json ]]; then
  (cd src/frontend && npm ci)
fi

echo "Local build ready (.venv + local_dev/workflow-data)."
