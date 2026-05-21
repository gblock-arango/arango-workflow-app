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
# Runtime config lives in ``app.yaml`` (injected by Databricks Apps). This script reads the same
# file for deploy-time values (warehouse id, UC table names). Shell env / $7 still override.
#
# After deploy: ./scripts/set_user_api_scopes.sh (User authorization / OBO for peer App calls).
# Inspect UC: ./scripts/read_uc_peer_registry.sh
# Next.js build output: logs/frontend-build.log (set WORKFLOW_FRONTEND_BUILD_FAIL_DEPLOY=1 to abort deploy on failure).

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
ARANGO_GATEWAY_REGISTRY_TABLE="${ARANGO_GATEWAY_REGISTRY_TABLE:-}"
ARANGO_AGENT_REGISTRY_TABLE="${ARANGO_AGENT_REGISTRY_TABLE:-}"
ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE="${ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE:-}"
ARANGO_WORKFLOW_REGISTRY_TABLE="${ARANGO_WORKFLOW_REGISTRY_TABLE:-}"
REGISTRY_TABLE="${6:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/_app_yaml_env.sh
source "${SCRIPT_DIR}/scripts/_app_yaml_env.sh"
load_deploy_config_from_app_yaml

echo "Deploy config (app.yaml + env overrides):"
echo "  DATABRICKS_SQL_WAREHOUSE_ID=${WAREHOUSE_ID:-<unset>}"
echo "  ARANGO_GATEWAY_REGISTRY_TABLE=${ARANGO_GATEWAY_REGISTRY_TABLE}"
echo "  ARANGO_AGENT_REGISTRY_TABLE=${ARANGO_AGENT_REGISTRY_TABLE}"
echo "  ARANGO_WORKFLOW_REGISTRY_TABLE=${ARANGO_WORKFLOW_REGISTRY_TABLE}"
echo "  ARANGO_REGISTRY_TABLE=${REGISTRY_TABLE}"
echo "  SERVICE_URL_PATH_PREFIX=${SERVICE_URL_PATH_PREFIX:-<empty>}"
echo

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
export PROFILE PROFILE_ARGS

# shellcheck source=scripts/_databricks_sql_lib.sh
source "${SCRIPT_DIR}/scripts/_databricks_sql_lib.sh"

_databricks() {
  if [[ ${#PROFILE_ARGS[@]} -gt 0 ]]; then
    databricks "${PROFILE_ARGS[@]}" "$@"
  else
    databricks "$@"
  fi
}

# shellcheck source=scripts/_deploy_app_print_urls.sh
source "${SCRIPT_DIR}/scripts/_deploy_app_print_urls.sh"

ensure_app_running_before_deploy() {
  local json app_state compute_state
  if ! json="$(_databricks apps get "${APP_NAME}" --output json 2>/dev/null)"; then
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
  _databricks apps start "${APP_NAME}"
}

echo "NOTE: Arango cluster credentials live on arango-gateway-app; this app uses gateway HTTP + UC URL registries."

DEPLOY_LOG_DIR="${SCRIPT_DIR}/logs"
FRONTEND_BUILD_LOG="${DEPLOY_LOG_DIR}/frontend-build.log"
mkdir -p "${DEPLOY_LOG_DIR}"

echo "Building Next static export (AOE_STATIC_EXPORT=1)…"
echo "Frontend build log: ${FRONTEND_BUILD_LOG}"
if [[ -d "${SCRIPT_DIR}/src/frontend" ]]; then
  {
    echo "=== frontend build $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
    echo "host: $(hostname 2>/dev/null || echo unknown)"
    echo "cwd: ${SCRIPT_DIR}/src/frontend"
    echo "node: $(command -v node 2>/dev/null || echo missing) $(node -v 2>/dev/null || true)"
    echo "npm: $(command -v npm 2>/dev/null || echo missing) $(npm -v 2>/dev/null || true)"
    echo "command: AOE_STATIC_EXPORT=1 npm run build"
    echo "---"
  } >"${FRONTEND_BUILD_LOG}"
  set +e
  (cd "${SCRIPT_DIR}/src/frontend" && AOE_STATIC_EXPORT=1 npm run build) 2>&1 | tee -a "${FRONTEND_BUILD_LOG}"
  _frontend_build_rc=${PIPESTATUS[0]}
  set -e
  if [[ "${_frontend_build_rc}" -ne 0 ]]; then
    echo "ERROR: frontend build failed (exit ${_frontend_build_rc}). Trace: ${FRONTEND_BUILD_LOG}" >&2
    echo "WARNING: continuing deploy without a fresh static UI (fix build, then re-run ./deploy_app.sh)." >&2
    if [[ "${WORKFLOW_FRONTEND_BUILD_FAIL_DEPLOY:-}" == "1" ]]; then
      exit "${_frontend_build_rc}"
    fi
  else
    echo "Frontend build OK."
  fi
else
  echo "NOTE: no src/frontend — skipping Next build." >&2
fi

FRONTEND_OUT_DIR="${SCRIPT_DIR}/src/frontend/out"
FRONTEND_OUT_REMOTE="${SOURCE_CODE_PATH}/src/frontend/out"

echo "Syncing local project to '${SOURCE_CODE_PATH}'..."
_databricks sync . "${SOURCE_CODE_PATH}"

echo ""
if [[ ! -f "${FRONTEND_OUT_DIR}/dashboard.html" ]]; then
  echo "ERROR: ${FRONTEND_OUT_DIR}/dashboard.html is missing after the frontend build." >&2
  echo "       /dashboard on the deployed app will 404 until this exists. See ${FRONTEND_BUILD_LOG}" >&2
  if [[ "${WORKFLOW_FRONTEND_BUILD_FAIL_DEPLOY:-}" == "1" ]]; then
    exit 1
  fi
else
  _html_count="$(find "${FRONTEND_OUT_DIR}" -maxdepth 1 -name '*.html' 2>/dev/null | wc -l | tr -d ' ')"
  echo "=== Syncing OntoExtract UI (src/frontend/out) to workspace ==="
  echo "  Local:  ${FRONTEND_OUT_DIR} (${_html_count} top-level .html files, incl. dashboard.html)"
  echo "  Remote: ${FRONTEND_OUT_REMOTE}"
  echo "  (explicit --full sync; required because databricks sync . often skips build output)"
  _databricks sync --full "${FRONTEND_OUT_DIR}" "${FRONTEND_OUT_REMOTE}"
  echo "=== Frontend static export sync complete ==="
fi
echo ""

if ! _databricks apps get "${APP_NAME}" &>/dev/null; then
  echo "Creating Databricks App '${APP_NAME}'…"
  _databricks apps create "${APP_NAME}" \
    --description "Arango workflow — OntoExtract UI; BFF to gateway + mcp-arango-agent"
fi

ensure_app_running_before_deploy

echo "Deploying app '${APP_NAME}' from '${SOURCE_CODE_PATH}'..."
_databricks apps deploy "${APP_NAME}" \
  --source-code-path "${SOURCE_CODE_PATH}"

echo "Fetching app metadata..."
APP_JSON="$(_databricks apps get "${APP_NAME}" --output json)"
APP_URL="$(
  "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin).get("url",""))' <<< "${APP_JSON}"
)"
APP_URL_NUMERIC_SUFFIX="$(_parse_app_url_numeric_suffix "${APP_JSON}")"
APP_RESOURCE_ID="$(
  "${PYTHON_BIN}" -c 'import json,sys; j=json.load(sys.stdin); print(j.get("id") or j.get("app_id") or "")' <<< "${APP_JSON}"
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

echo "App deployed - open in browser:"
print_deployed_app_urls

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
  echo "ERROR: DATABRICKS_SQL_WAREHOUSE_ID is not set. Set value in app.yaml or export / pass as deploy_app.sh arg 7." >&2
  exit 1
fi
if [[ -z "${ARANGO_GATEWAY_REGISTRY_TABLE// }" || -z "${ARANGO_AGENT_REGISTRY_TABLE// }" || -z "${REGISTRY_TABLE// }" ]]; then
  echo "ERROR: UC registry table names missing from app.yaml." >&2
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

REGISTRY_CATALOG="$(echo "${REGISTRY_TABLE}" | cut -d. -f1)"
REGISTRY_SCHEMA="$(echo "${REGISTRY_TABLE}" | cut -d. -f2)"
UC_GRAPH_VOLUME_NAME="${UC_GRAPH_VOLUME_NAME:-arango_workflow_volume}"
echo "Ensuring UC workflow-data volume ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA}.${UC_GRAPH_VOLUME_NAME}…"
run_sql_statement "CREATE VOLUME IF NOT EXISTS ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA}.${UC_GRAPH_VOLUME_NAME}"
run_sql_statement "GRANT READ VOLUME, WRITE VOLUME ON VOLUME ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA}.${UC_GRAPH_VOLUME_NAME} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"

if [[ "${WORKFLOW_DATA_SEED_AT_DEPLOY:-1}" != "0" ]]; then
  SEED_SCRIPT="${SCRIPT_DIR}/scripts/seed_workflow_volume_datasets.py"
  if [[ -f "${SEED_SCRIPT}" ]]; then
    echo "Seeding datasets/<domain>/ → UC workflow-data/builtin/<domain>/ (Files API)…"
    _seed_args=(--catalog "${REGISTRY_CATALOG}" --schema "${REGISTRY_SCHEMA}" --volume "${UC_GRAPH_VOLUME_NAME}")
    if [[ -n "${PROFILE}" ]]; then
      _seed_args+=(--profile "${PROFILE}")
    fi
    if ! "${PYTHON_BIN}" "${SEED_SCRIPT}" "${_seed_args[@]}"; then
      echo "NOTE: deploy-time volume seed failed (app startup also seeds when WORKFLOW_DATA_SEED_ON_STARTUP=true)." >&2
    fi
  fi
else
  echo "WORKFLOW_DATA_SEED_AT_DEPLOY=0: skipping deploy-time dataset seed."
fi

echo "Publishing workflow app URL to UC (${ARANGO_WORKFLOW_REGISTRY_TABLE})…"
if "${SCRIPT_DIR}/update_arango_workflow_registry_uc.sh" \
  "${APP_URL}" "${APP_NAME}" "${ARANGO_WORKFLOW_REGISTRY_TABLE}" "${WAREHOUSE_ID}" "${PROFILE}" \
  "${APP_SERVICE_PRINCIPAL_CLIENT_ID}"; then
  :
else
  echo "NOTE: Workflow URL UC publish failed. Restart arango-workflow-app once or run update_arango_workflow_registry_uc.sh manually." >&2
fi

echo "Deploy complete."
print_deployed_app_urls
echo "Peer URL resolution (after gateway + mcp-arango-agent are deployed):"
echo "  Gateway: UC ${ARANGO_GATEWAY_REGISTRY_TABLE} unless ARANGO_GATEWAY_BASE_URL is set on the app."
echo "  MCP agent: UC ${ARANGO_AGENT_REGISTRY_TABLE} unless ARANGO_AGENT_BASE_URL is set."
echo "  This app's URL: UC ${ARANGO_WORKFLOW_REGISTRY_TABLE} (for mcp-arango-agent /mcp/aoe)."
echo "  Arango connection row (for gateway upstream): ${REGISTRY_TABLE}"
echo "  Inspect locally: ./scripts/read_uc_peer_registry.sh ${PROFILE}"
echo
echo "To export in your current shell:"
echo "export DATABRICKS_APP_URL=\"${APP_URL}\""
echo "export DATABRICKS_APP_HOME_URL=\"${APP_HOME_URL}\""
echo "export DATABRICKS_APP_DASHBOARD_URL=\"${APP_DASHBOARD_URL}\""
echo "export DATABRICKS_SQL_WAREHOUSE_ID=\"${WAREHOUSE_ID}\""
if [[ -n "${APP_URL_NUMERIC_SUFFIX:-}" ]]; then
  echo "export DATABRICKS_APP_URL_NUMERIC_SUFFIX=\"${APP_URL_NUMERIC_SUFFIX}\""
fi
echo
echo "registry table (read): ${REGISTRY_TABLE}"
echo "warehouse id: ${WAREHOUSE_ID}"
