#!/usr/bin/env bash
set -euo pipefail

# Typical use: log in with the Databricks CLI, then from this repo:
#   ./deploy_app.sh
#
# Optional positional overrides: app-name, workspace source path, profile, then placeholders
#   $4–$7 kept for compatibility with arango-dashboard-app/deploy_app.sh.
#
# Genie/MCP chat is proxied via this app's BFF to arango-mcp-app. Set ARANGO_AGENT_BASE_URL
# or ensure ARANGO_AGENT_REGISTRY_TABLE has an active row after deploying mcp-arango-agent.
#
# After a successful ``apps deploy``, runs ``./scripts/set_user_api_scopes.sh`` (non-fatal).

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
REGISTRY_TABLE="${6:-workspace.default.arango_connection_registry}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -x "${SCRIPT_DIR}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python3"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python3" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python3"
else
  PYTHON_BIN="python3"
fi

if [[ -n "${PROFILE}" ]]; then
  PROFILE_ARGS=(--profile "${PROFILE}")
else
  PROFILE_ARGS=()
fi

ensure_app_running_before_deploy() {
  local json app_state
  if ! json="$(databricks apps get "${APP_NAME}" --output json "${PROFILE_ARGS[@]}" 2>/dev/null)"; then
    return 0
  fi
  app_state="$(
    "${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("app_status") or {}).get("state",""))' <<< "${json}" 2>/dev/null || true
  )"
  if [[ "${app_state}" == "RUNNING" ]]; then
    echo "App '${APP_NAME}' is RUNNING; proceeding to deploy."
    return 0
  fi
  echo "App '${APP_NAME}' is not RUNNING (app_status=${app_state:-unknown}). Starting…"
  if [[ "${SKIP_APPS_START_BEFORE_DEPLOY:-}" == "1" ]]; then
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
    --description "Arango workflow — OntoExtract UI; platform BFF reserved for later" \
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

SET_USER_SCOPES_SCRIPT="${SCRIPT_DIR}/scripts/set_user_api_scopes.sh"
if [[ -x "${SET_USER_SCOPES_SCRIPT}" ]]; then
  echo "Setting user_api_scopes on '${APP_NAME}'…"
  "${SET_USER_SCOPES_SCRIPT}" "${APP_NAME}" "${PROFILE}" || true
fi

if [[ -z "${WAREHOUSE_ID// }" ]]; then
  echo "ERROR: DATABRICKS_SQL_WAREHOUSE_ID is not set." >&2
  exit 1
fi

run_sql_statement() {
  local statement="$1"
  local payload
  payload="$(
    "${PYTHON_BIN}" -c 'import json,sys; print(json.dumps({"warehouse_id":sys.argv[1], "statement":sys.argv[2], "wait_timeout":"30s"}))' \
      "${WAREHOUSE_ID}" "${statement}"
  )"
  local response statement_id status
  response="$(databricks api post /api/2.0/sql/statements --json "${payload}" "${PROFILE_ARGS[@]}")"
  statement_id="$("${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin).get("statement_id",""))' <<< "${response}")"
  status="$("${PYTHON_BIN}" -c 'import json,sys; print((json.load(sys.stdin).get("status") or {}).get("state",""))' <<< "${response}")"
  for _ in $(seq 1 30); do
    [[ "${status}" == "SUCCEEDED" ]] && return 0
    [[ "${status}" == "FAILED" || "${status}" == "CANCELED" ]] && exit 1
    sleep 1
    response="$(databricks api get "/api/2.0/sql/statements/${statement_id}" "${PROFILE_ARGS[@]}")"
    status="$("${PYTHON_BIN}" -c 'import json,sys; print((json.load(sys.stdin).get("status") or {}).get("state",""))' <<< "${response}")"
  done
  exit 1
}

if [[ -n "${APP_SERVICE_PRINCIPAL_CLIENT_ID}" ]]; then
  echo "Granting UC privileges to app SP '${APP_SERVICE_PRINCIPAL_CLIENT_ID}'…"
  run_sql_statement "GRANT USE CATALOG ON CATALOG workspace TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`" || true
  run_sql_statement "GRANT USE SCHEMA ON SCHEMA workspace.default TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`" || true
  run_sql_statement "GRANT SELECT ON TABLE ${REGISTRY_TABLE} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`" || true
  run_sql_statement "GRANT SELECT ON TABLE ${ARANGO_GATEWAY_REGISTRY_TABLE} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`" || true
  run_sql_statement "GRANT SELECT ON TABLE ${ARANGO_AGENT_REGISTRY_TABLE} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`" || true
  run_sql_statement "GRANT SELECT ON TABLE ${ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`" || true
fi

echo
echo "DATABRICKS_APP_URL=${APP_URL}"
printf '  \033]8;;%s\033\\%s\033]8;;\033\\\n' "${APP_URL}" "→ Open OntoExtract app"
