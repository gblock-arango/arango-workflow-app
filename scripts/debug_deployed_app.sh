#!/usr/bin/env bash
# Debug checklist for deployed arango-workflow-app (run from repo root).
# Usage: ./scripts/debug_deployed_app.sh [profile]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_NAME="${APP_NAME:-arango-workflow-app}"
PROFILE="${1:-}"

args=()
[[ -n "${PROFILE}" ]] && args=(--profile "${PROFILE}")

echo "=== Databricks app status ==="
APP_JSON="$(databricks apps get "${APP_NAME}" "${args[@]}" -o json)"
export APP_JSON
python3 <<'PY'
import json, os
d = json.loads(os.environ["APP_JSON"])
print("url:", d.get("url"))
print("app:", (d.get("app_status") or {}).get("state"))
print("compute:", (d.get("compute_status") or {}).get("state"))
PY

BASE_URL="$(python3 <<'PY'
import json, os
d = json.loads(os.environ["APP_JSON"])
print((d.get("url") or "").rstrip("/"))
PY
)"
echo ""
echo "App URL: ${BASE_URL}"
echo ""

cd "${REPO_ROOT}"
export PYTHONPATH=src

echo "=== Local /ready probe (UC registry + Arango HTTP, no gateway app) ==="
python3 <<'PY'
import json
import os
from app.services.arango_connectivity import fetch_arango_startup_status
from app.services.gateway_startup_status import ready_payload_from_startup_status

startup = fetch_arango_startup_status()
ready = ready_payload_from_startup_status(startup, gateway_base_url="")
print(json.dumps({"ready": ready, "secrets": startup.get("secrets"), "source": startup.get("source")}, indent=2))
if ready.get("status") != "ready":
    print("\nHINT: if secrets show auth_password_present false, redeploy with ARANGO_PING_BASIC_AUTH_PASSWORD set.", flush=True)
    print("      Copy the same value from arango-gateway-app/app.yaml.", flush=True)
PY
echo ""

echo "=== UC peer registries ==="
"${SCRIPT_DIR}/print_effective_peer_urls.py" 2>&1 | head -25
echo ""

if [[ -f "${SCRIPT_DIR}/_app_yaml_env.sh" ]]; then
  # shellcheck source=scripts/_app_yaml_env.sh
  source "${SCRIPT_DIR}/_app_yaml_env.sh" 2>/dev/null || true
  _resolve_from_app_yaml DATABRICKS_SQL_WAREHOUSE_ID 2>/dev/null || true
fi
WID="${DATABRICKS_SQL_WAREHOUSE_ID:-}"
if [[ -n "${WID}" ]]; then
  echo "=== embedding_status (last 5 rows) ==="
  databricks experimental aitools tools query \
    "SELECT doc_id, filename, status, parsed, chunked, embedded, chunk_count, updated_at FROM workspace.default.embedding_status ORDER BY updated_at DESC LIMIT 5" \
    "${args[@]}" 2>&1 || echo "(query failed)"
  echo ""
fi

echo "=== In-browser checks (while logged into ${BASE_URL}) ==="
cat <<EOF
  ${BASE_URL}/health
  ${BASE_URL}/ready
  ${BASE_URL}/ready?refresh=true

Look for JSON field "check": "uc_registry_direct" — if missing, old build is still running.

  ${BASE_URL}/ready/auth-diagnostics
  ${BASE_URL}/api/v1/embedding/status?limit=10
EOF
echo ""
echo "=== Redeploy ==="
echo "  export ARANGO_PING_BASIC_AUTH_PASSWORD='<same as gateway>'"
echo "  ./deploy_app.sh ${APP_NAME}"
