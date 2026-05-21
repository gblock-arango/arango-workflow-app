#!/usr/bin/env bash
# Read Unity Catalog peer-app registry tables + effective URLs for arango-workflow-app.
# Mirrors arango-dashboard-app deploy/UC patterns (see arango-dashboard-app/README_Agent.md).
#
# Usage:
#   export DATABRICKS_SQL_WAREHOUSE_ID=<hex>
#   ./scripts/read_uc_peer_registry.sh [profile]
#
# Optional env: ARANGO_GATEWAY_REGISTRY_TABLE, ARANGO_AGENT_REGISTRY_TABLE, ARANGO_REGISTRY_TABLE

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -x "${REPO_ROOT}/.venv/bin/python3" ]]; then
  PY="${REPO_ROOT}/.venv/bin/python3"
else
  PY=python3
fi

PROFILE="${1:-}"
if [[ -n "${PROFILE}" ]]; then
  export DATABRICKS_CONFIG_PROFILE="${PROFILE}"
fi

cd "${REPO_ROOT}"
export PYTHONPATH=src

echo "UC registry tables (SQL warehouse):"
"${PY}" "${SCRIPT_DIR}/query_uc_registry_tables.py"
echo
echo "Effective peer URLs (env overrides + UC cache logic):"
"${PY}" "${SCRIPT_DIR}/print_effective_peer_urls.py"
