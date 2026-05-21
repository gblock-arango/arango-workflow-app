#!/usr/bin/env bash
set -euo pipefail

# Typical use: log in with the Databricks CLI, then from this repo:
#   ./deploy_app.sh
#
# Deploy order (peer apps):
#   1. arango-gateway-app  — publishes ARANGO_GATEWAY_REGISTRY_TABLE + ARANGO_REGISTRY_TABLE
#   2. mcp-arango-agent      — publishes ARANGO_AGENT_REGISTRY_TABLE (Genie/MCP)
#   3. arango-workflow-app   — this script (reads UC; proxies Genie to mcp-app; Arango via gateway)
#
# Optional positional overrides: app-name, workspace source path, profile, then placeholders
#   $4–$7 kept for compatibility with arango-dashboard-app/deploy_app.sh.
#
# Set DATABRICKS_SQL_WAREHOUSE_ID (or pass warehouse as $7). Genie/MCP chat is proxied to
# mcp-arango-agent via /api/workflow/genie/chat. Arango data paths use arango-gateway-app only
# (no python-arango in this app).
#
# After deploy: ./scripts/set_user_api_scopes.sh (User authorization / OBO for peer App calls).
# Inspect UC: ./scripts/read_uc_peer_registry.sh

APP_NAME="${1:-arango-workflow-app}"
PROFILE="${3:-}"

_resolve_ws_user() {
  local args=() user_json user
  [[ -n "${PROFILE}" ]] && args=(--profile "${PROFILE}")
  user_json="$(databricks current-user me "${args[@]}" 2>/dev/null)" || return 1
  user="$(printf '%s' "${user_json}" | python3 -c 'import json,sys; d=json.load(sys.stdin); e=d.get("emails") or []; print(d.get("userName") or (e[0].get("value") if e else ""))' 2>/dev/null)" || return 1
  [[ -n "${user}" ]] || return 1
  printf '%s' "${user}"
}

if [[ -n "${2:-}" ]]; then
  SOURCE_CODE_PATH="$2"
else
  _ws_user="$(_resolve_ws_user)" || {
    echo "ERROR: could not resolve workspace user via 'databricks current-user me'." >&2
    echo "Pass an explicit source path: ./deploy_app.sh ${APP_NAME} /Workspace/Users/<you>/${APP_NAME}" >&2
    exit 1
  }
  SOURCE_CODE_PATH="/Workspace/Users/${_ws_user}/${APP_NAME}"
fi

WAREHOUSE_ID="${DATABRICKS_SQL_WAREHOUSE_ID:-${7:-}}"
ARANGO_GATEWAY_REGISTRY_TABLE="${ARANGO_GATEWAY_REGISTRY_TABLE:-workspace.default.arango_gateway_registry}"
ARANGO_AGENT_REGISTRY_TABLE="${ARANGO_AGENT_REGISTRY_TABLE:-workspace.default.arango_agent_registry}"
ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE="${ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE:-workspace.default.arango_bronze_simulated_injector_registry}"
ARANGO_WORKFLOW_REGISTRY_TABLE="${ARANGO_WORKFLOW_REGISTRY_TABLE:-workspace.default.arango_workflow_registry}"
REGISTRY_TABLE="${6:-workspace.default.arango_connection_registry}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -x "${SCRIPT_DIR}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python3"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python3" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python3"
else
  PYTHON_BIN="python3"
fi
export PYTHON_BIN

if [[ -n "${PROFILE}" ]]; then
  PROFILE_ARGS=(--profile "${PROFILE}")
else
  PROFILE_ARGS=()
fi
export PROFILE_ARGS

# shellcheck source=scripts/_databricks_sql_lib.sh
source "${SCRIPT_DIR}/scripts/_databricks_sql_lib.sh"

echo "NOTE: Arango cluster credentials live on arango-gateway-app; this app uses gateway HTTP + UC URL registries."

ensure_app_running_before_deploy() {
  local json app_state compute_state
  if ! json="$(databricks apps get "${APP_NAME}" --output json "${PROFILE_ARGS[@]}" 2>/dev/null)"; then
    return 0
  fi
  app_state="$(
    "${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("app_status") or {}).get("state",""))' <<< "${json}" 2>/dev/null || true
  )"
  compute_state="$(
    "${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("compute_status") or {}).get("state",""))' <<< "${json}" 2>/dev/null || true
  )"
  if [[ "${app_state}" == "RUNNING" ]]; then
    echo "App '${APP_NAME}' is RUNNING; proceeding to deploy."
    return 0
  fi
  echo "App '${APP_NAME}' is not RUNNING (app_status=${app_state:-unknown}, compute_status=${compute_state:-unknown})."
  echo "Deploy requires RUNNING; starting app…"
  if [[ "${SKIP_APPS_START_BEFORE_DEPLOY:-}" == "1" ]]; then
    echo "SKIP_APPS_START_BEFORE_DEPLOY=1: skipping databricks apps start; deploy may fail." >&2
    return 0
  fi
  databricks apps start "${APP_NAME}" "${PROFILE_ARGS[@]}"
}

echo "Building Next static export (AOE_STATIC_EXPORT=1)…"
if [[ -d "${SCRIPT_DIR}/src/frontend" ]]; then
  (cd "${SCRIPT_DIR}/src/frontend" && AOE_STATIC_EXPORT=1 npm run build) || {
    echo "WARNING: frontend build failed; deploy without static UI or fix npm install." >&2
  }
fi

echo "Syncing local project to '${SOURCE_CODE_PATH}'..."
databricks sync . "${SOURCE_CODE_PATH}" "${PROFILE_ARGS[@]}"

if ! databricks apps get "${APP_NAME}" "${PROFILE_ARGS[@]}" &>/dev/null; then
  echo "Creating Databricks App '${APP_NAME}'…"
  databricks apps create "${APP_NAME}" \
    --description "Arango workflow — OntoExtract UI; BFF to gateway + mcp-arango-agent" \
    "${PROFILE_ARGS[@]}"
fi

ensure_app_running_before_deploy

echo "Deploying app '${APP_NAME}' from '${SOURCE_CODE_PATH}'..."
databricks apps deploy "${APP_NAME}" \
  --source-code-path "${SOURCE_CODE_PATH}" \
  "${PROFILE_ARGS[@]}"

APP_JSON="$(databricks apps get "${APP_NAME}" --output json "${PROFILE_ARGS[@]}")"
APP_URL="$(
  "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin).get("url",""))' <<< "${APP_JSON}"
)"
APP_SERVICE_PRINCIPAL_CLIENT_ID="$(
  "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin).get("service_principal_client_id",""))' <<< "${APP_JSON}"
)"

if [[ -z "${APP_URL}" ]]; then
  echo "ERROR: Could not extract URL from Databricks app metadata." >&2
  exit 1
fi
if [[ -z "${APP_SERVICE_PRINCIPAL_CLIENT_ID}" ]]; then
  echo "ERROR: Could not extract app service principal client id." >&2
  exit 1
fi

SET_USER_SCOPES_SCRIPT="${SCRIPT_DIR}/scripts/set_user_api_scopes.sh"
if [[ -x "${SET_USER_SCOPES_SCRIPT}" ]]; then
  echo "Setting user_api_scopes on '${APP_NAME}' (User authorization / OBO)…"
  if ! "${SET_USER_SCOPES_SCRIPT}" "${APP_NAME}" "${PROFILE}"; then
    echo "NOTE: set_user_api_scopes.sh failed. Peer App proxy may 401 until fixed. Re-run: ${SET_USER_SCOPES_SCRIPT} ${APP_NAME} ${PROFILE}" >&2
  fi
else
  echo "NOTE: ${SET_USER_SCOPES_SCRIPT} missing or not executable; skip user_api_scopes." >&2
fi

if [[ -z "${WAREHOUSE_ID// }" ]]; then
  echo "ERROR: DATABRICKS_SQL_WAREHOUSE_ID is not set (export it, set in app.yaml, use arango-platform-bundle, or pass as 7th positional arg)." >&2
  exit 1
fi
export WAREHOUSE_ID

echo "Granting UC privileges to app service principal '${APP_SERVICE_PRINCIPAL_CLIENT_ID}'…"
run_sql_statement "GRANT USE CATALOG ON CATALOG workspace TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"
run_sql_statement "GRANT USE SCHEMA ON SCHEMA workspace.default TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"
run_sql_statement "GRANT SELECT ON TABLE ${REGISTRY_TABLE} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"

echo "Granting SELECT on gateway URL registry (${ARANGO_GATEWAY_REGISTRY_TABLE})…"
if ! run_sql_statement "GRANT SELECT ON TABLE ${ARANGO_GATEWAY_REGISTRY_TABLE} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"; then
  echo "NOTE: GRANT on ${ARANGO_GATEWAY_REGISTRY_TABLE} failed — deploy arango-gateway-app once so the table exists." >&2
fi

echo "Granting SELECT on mcp-agent URL registry (${ARANGO_AGENT_REGISTRY_TABLE})…"
if ! run_sql_statement "GRANT SELECT ON TABLE ${ARANGO_AGENT_REGISTRY_TABLE} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"; then
  echo "NOTE: GRANT on ${ARANGO_AGENT_REGISTRY_TABLE} failed — deploy mcp-arango-agent once so the table exists." >&2
fi

echo "Granting SELECT on bronze injector registry (${ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE})…"
if ! run_sql_statement "GRANT SELECT ON TABLE ${ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"; then
  echo "NOTE: GRANT on ${ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE} failed (optional peer)." >&2
fi

echo "Publishing workflow app URL to UC (${ARANGO_WORKFLOW_REGISTRY_TABLE})…"
if ( "${SCRIPT_DIR}/update_arango_workflow_registry_uc.sh" \
  "${APP_URL}" "${APP_NAME}" "${ARANGO_WORKFLOW_REGISTRY_TABLE}" "${WAREHOUSE_ID}" "${PROFILE}" \
  "${APP_SERVICE_PRINCIPAL_CLIENT_ID}" ); then
  :
else
  echo "NOTE: Workflow URL UC publish failed. Restart arango-workflow-app once or run update_arango_workflow_registry_uc.sh manually." >&2
fi

echo
echo "DATABRICKS_APP_URL=${APP_URL}"
printf '  \033]8;;%s\033\\%s\033]8;;\033\\\n' "${APP_URL}" "→ Open arango-workflow-app"
echo
echo "Peer URL resolution (after gateway + mcp-arango-agent are deployed):"
echo "  Gateway: UC ${ARANGO_GATEWAY_REGISTRY_TABLE} unless ARANGO_GATEWAY_BASE_URL is set on the app."
echo "  MCP agent: UC ${ARANGO_AGENT_REGISTRY_TABLE} unless ARANGO_AGENT_BASE_URL is set."
echo "  This app's URL: UC ${ARANGO_WORKFLOW_REGISTRY_TABLE} (for mcp-arango-agent /mcp/aoe)."
echo "  Arango connection row (for gateway upstream): ${REGISTRY_TABLE}"
echo "  Inspect locally: ./scripts/read_uc_peer_registry.sh ${PROFILE}"
echo
echo "To export in your shell:"
echo "export DATABRICKS_APP_URL=\"${APP_URL}\""
echo "export DATABRICKS_SQL_WAREHOUSE_ID=\"${WAREHOUSE_ID}\""
