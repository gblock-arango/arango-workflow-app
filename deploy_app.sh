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
# LLM secrets: keep ``value: ""`` in app.yaml in git. Before sync/deploy, this script copies
# app.yaml to ``.app.yaml.deploy-backup``, injects OPENAI_API_KEY / ANTHROPIC_API_KEY /
# OPENAI_BASE_URL from the environment (or repo ``.env``), syncs, then restores app.yaml on exit.
#
# On first run, if the App does not exist yet, the script runs ``databricks apps create`` before deploy.
# A brand-new app often shows ``app_status=UNAVAILABLE`` until the first deploy; see
# ``ensure_app_running_before_deploy`` (do not ``apps start`` in that state — it races with ``apps deploy``).
#
# After deploy: ./scripts/set_user_api_scopes.sh (User authorization / OBO for peer App calls).
# Serving: app.yaml declares autograph-* serving_endpoint resources (CAN_QUERY on deploy);
#   grant_autograph_serving_permissions.py repairs ACLs if needed; ensure_serving_endpoints.py probes READY.
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

# BGE/GTE widget ids → databricks-bge-large-en / databricks-gte-large-en (FM APIs).
_normalize_autograph_embedding_endpoint() {
  local raw="${AUTOGRAPH_EMBEDDING_MODEL_NAME:-}"
  if [[ -z "${raw// }" ]]; then
    return 0
  fi
  local resolved
  resolved="$(
    PYTHONPATH="${SCRIPT_DIR}/src" RAW="${raw}" "${PYTHON_BIN}" -c \
      'from app.llm.databricks_serving import normalize_serving_endpoint_name; import os; print(normalize_serving_endpoint_name(os.environ["RAW"]))'
  )"
  if [[ -n "${resolved}" && "${resolved}" != "${raw}" ]]; then
    echo "Normalized AUTOGRAPH_EMBEDDING_MODEL_NAME: ${raw} -> ${resolved}"
    export AUTOGRAPH_EMBEDDING_MODEL_NAME="${resolved}"
  fi
}
_normalize_autograph_embedding_endpoint
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

_app_active_deployment_state() {
  local json="$1"
  "${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("active_deployment") or {}).get("status",{}).get("state",""))' <<< "${json}" 2>/dev/null || true
}

_wait_for_active_deployment_idle() {
  local json deploy_state waited=0
  local max_wait="${DEPLOY_WAIT_ACTIVE_DEPLOYMENT_SEC:-900}"
  local poll="${DEPLOY_WAIT_ACTIVE_DEPLOYMENT_POLL_SEC:-10}"
  while (( waited < max_wait )); do
    if ! json="$(_databricks apps get "${APP_NAME}" --output json 2>/dev/null)"; then
      return 1
    fi
    deploy_state="$(_app_active_deployment_state "${json}")"
    if [[ -z "${deploy_state}" || "${deploy_state}" == "SUCCEEDED" || "${deploy_state}" == "FAILED" || "${deploy_state}" == "CANCELLED" ]]; then
      return 0
    fi
    echo "  App deployment in progress (active_deployment.status.state=${deploy_state}); waiting ${poll}s…"
    sleep "${poll}"
    waited=$((waited + poll))
  done
  echo "ERROR: timed out after ${max_wait}s waiting for app deployment to finish." >&2
  return 1
}

ensure_app_running_before_deploy() {
  local json app_state compute_state app_msg
  if ! json="$(_databricks apps get "${APP_NAME}" --output json 2>/dev/null)"; then
    return 0
  fi
  app_state="$(
    "${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("app_status") or {}).get("state",""))' <<< "${json}" 2>/dev/null || true
  )"
  compute_state="$(
    "${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("compute_status") or {}).get("state",""))' <<< "${json}" 2>/dev/null || true
  )"
  app_msg="$(
    "${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("app_status") or {}).get("message",""))' <<< "${json}" 2>/dev/null || true
  )"
  if [[ "${app_state}" == "RUNNING" ]]; then
    echo "App '${APP_NAME}' is RUNNING; proceeding to deploy."
    return 0
  fi
  # After `apps create`, compute is often ACTIVE while app_status stays UNAVAILABLE until the first
  # `apps deploy`. Starting the app in that state kicks off a deployment that races with deploy.
  if [[ "${app_state}" == "UNAVAILABLE" && "${compute_state}" == "ACTIVE" ]]; then
    if echo "${app_msg}" | grep -qiE 'not been deployed|deploy(ing)?[[:space:]]+source|run your app by deploying'; then
      echo "NOTE: App '${APP_NAME}' has no source deployment yet (app_status=UNAVAILABLE, compute_status=ACTIVE)."
      echo "      Skipping \`databricks apps start\`; the next step (\`databricks apps deploy\`) uploads code and should make the app available."
      return 0
    fi
  fi
  echo "App '${APP_NAME}' is not RUNNING (app_status=${app_state:-unknown}, compute_status=${compute_state:-unknown})."
  echo "Trying \`databricks apps start\` so compute is ready (deploy may still succeed if the platform accepts it)..."
  if [[ "${SKIP_APPS_START_BEFORE_DEPLOY:-}" == "1" ]]; then
    echo "SKIP_APPS_START_BEFORE_DEPLOY=1: skipping databricks apps start; deploy may fail." >&2
    return 0
  fi
  _databricks apps start "${APP_NAME}"
  _wait_for_active_deployment_idle || true
}

_deploy_app() {
  local deploy_out deploy_rc
  set +e
  deploy_out="$(_databricks apps deploy "${APP_NAME}" --source-code-path "${SOURCE_CODE_PATH}" 2>&1)"
  deploy_rc=$?
  set -e
  if [[ "${deploy_rc}" -eq 0 ]]; then
    return 0
  fi
  if echo "${deploy_out}" | grep -qiE 'active deployment in progress|deployment in progress'; then
    echo "NOTE: ${deploy_out}"
    echo "Another deployment is already running (often from \`databricks apps start\`). Waiting, then retrying deploy…"
    _wait_for_active_deployment_idle
    _databricks apps deploy "${APP_NAME}" --source-code-path "${SOURCE_CODE_PATH}"
    return $?
  fi
  echo "${deploy_out}" >&2
  return "${deploy_rc}"
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

APP_YAML="${SCRIPT_DIR}/app.yaml"
INJECT_SECRETS_SCRIPT="${SCRIPT_DIR}/scripts/inject_app_yaml_secrets.py"

_restore_app_yaml_secrets() {
  if [[ -f "${INJECT_SECRETS_SCRIPT}" ]]; then
    "${PYTHON_BIN}" "${INJECT_SECRETS_SCRIPT}" restore "${APP_YAML}" 2>/dev/null || true
  fi
}

LOAD_DOTENV_SCRIPT="${SCRIPT_DIR}/scripts/load_deploy_dotenv.py"
if [[ -f "${SCRIPT_DIR}/.env" && -f "${LOAD_DOTENV_SCRIPT}" ]]; then
  echo "Loading deploy secrets from ${SCRIPT_DIR}/.env"
  # shellcheck disable=SC1090
  eval "$("${PYTHON_BIN}" "${LOAD_DOTENV_SCRIPT}" "${SCRIPT_DIR}/.env")"
fi

if [[ -f "${INJECT_SECRETS_SCRIPT}" ]]; then
  if ! "${PYTHON_BIN}" "${INJECT_SECRETS_SCRIPT}" prepare "${APP_YAML}"; then
    echo "ERROR: inject_app_yaml_secrets.py prepare failed." >&2
    exit 1
  fi
  trap _restore_app_yaml_secrets EXIT
  _openai_deploy_key="$("${PYTHON_BIN}" "${SCRIPT_DIR}/scripts/read_app_yaml_env.py" OPENAI_API_KEY "${APP_YAML}" 2>/dev/null || true)"
  if [[ -z "${_openai_deploy_key// }" ]]; then
    echo "WARNING: OPENAI_API_KEY is empty after deploy injection." >&2
    echo "  Export OPENAI_API_KEY, add it to ${SCRIPT_DIR}/.env, or set in Databricks App UI after deploy." >&2
    echo "  LLM embedding/extraction will fail until a key is configured." >&2
  else
    echo "OPENAI_API_KEY will be deployed via app.yaml for this sync only."
  fi
else
  echo "NOTE: ${INJECT_SECRETS_SCRIPT} missing; app.yaml is synced as-is." >&2
fi

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
  echo "  explicit --full sync; required because databricks sync . often skips build output"
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
_deploy_app

echo "Fetching app metadata..."
APP_JSON="$(_databricks apps get "${APP_NAME}" --output json)"
APP_URL="$(
  APP_JSON="${APP_JSON}" "${PYTHON_BIN}" -c 'import json,os; print(json.loads(os.environ["APP_JSON"]).get("url",""))'
)"
APP_URL_NUMERIC_SUFFIX="$(_parse_app_url_numeric_suffix "${APP_JSON}")"
APP_RESOURCE_ID="$(
  APP_JSON="${APP_JSON}" "${PYTHON_BIN}" -c 'import json,os; j=json.loads(os.environ["APP_JSON"]); print(j.get("id") or j.get("app_id") or "")'
)"
APP_SERVICE_PRINCIPAL_CLIENT_ID="$(
  APP_JSON="${APP_JSON}" "${PYTHON_BIN}" -c 'import json,os; print(json.loads(os.environ["APP_JSON"]).get("service_principal_client_id",""))'
)"

if [[ -z "${APP_URL}" ]]; then
  echo "ERROR: Could not extract URL from Databricks app metadata." >&2
  exit 1
fi
if [[ -z "${APP_SERVICE_PRINCIPAL_CLIENT_ID}" ]]; then
  echo "ERROR: Could not extract app service principal client id." >&2
  exit 1
fi

verify_serving_endpoint() {
  local ep="$1"
  if [[ -z "${ep// }" ]]; then
    return 0
  fi
  echo "Serving endpoint probe: '${ep}'"
  local se_json
  if ! se_json="$(_databricks serving-endpoints get "${ep}" -o json 2>/dev/null)"; then
    echo "WARNING: databricks serving-endpoints get '${ep}' failed (wrong name or permissions)." >&2
    return 0
  fi
  "${PYTHON_BIN}" -c '
import json,sys
d=json.load(sys.stdin)
name=d.get("name") or ""
state=d.get("state") or {}
ready=state.get("ready") if isinstance(state,dict) else None
print(f"  endpoint={name!r} state.ready={ready!r}")
' <<< "${se_json}" || true
}

verify_serving_endpoint "${AUTOGRAPH_LLM_MODEL_NAME:-}"
verify_serving_endpoint "${AUTOGRAPH_EMBEDDING_MODEL_NAME:-}"

GRANT_SERVING_SCRIPT="${SCRIPT_DIR}/scripts/grant_autograph_serving_permissions.py"
if [[ -f "${GRANT_SERVING_SCRIPT}" ]]; then
  _grant_args=(--app-name "${APP_NAME}" --service-principal-id "${APP_SERVICE_PRINCIPAL_CLIENT_ID}")
  if [[ -n "${AUTOGRAPH_LLM_MODEL_NAME:-}" ]]; then
    _grant_args+=(--endpoint "${AUTOGRAPH_LLM_MODEL_NAME}")
  fi
  if [[ -n "${AUTOGRAPH_EMBEDDING_MODEL_NAME:-}" ]]; then
    _grant_args+=(--endpoint "${AUTOGRAPH_EMBEDDING_MODEL_NAME}")
  fi
  if [[ ${#_grant_args[@]} -gt 2 ]]; then
    echo "Granting CAN_QUERY on Autograph serving endpoints to app SP…"
    set +e
    "${PYTHON_BIN}" "${GRANT_SERVING_SCRIPT}" "${_grant_args[@]}"
    _grant_rc=$?
    set -e
    if [[ "${_grant_rc}" -ne 0 ]]; then
      echo "WARNING: grant_autograph_serving_permissions failed (deploy user needs CAN MANAGE on endpoints)." >&2
      if [[ "${GRANT_SERVING_PERMISSIONS_FAIL_DEPLOY:-}" == "1" ]]; then
        exit 1
      fi
    fi
  fi
fi

ENSURE_SERVING_SCRIPT="${SCRIPT_DIR}/scripts/ensure_serving_endpoints.py"
if [[ -f "${ENSURE_SERVING_SCRIPT}" ]]; then
  if [[ -n "${PROFILE}" ]]; then
    export DATABRICKS_CONFIG_PROFILE="${PROFILE}"
  fi
  export AUTOGRAPH_LLM_MODEL_NAME="${AUTOGRAPH_LLM_MODEL_NAME:-}"
  export AUTOGRAPH_EMBEDDING_MODEL_NAME="${AUTOGRAPH_EMBEDDING_MODEL_NAME:-}"
  # Embedding is on the ingest green path; block deploy when FM API endpoint is missing or not READY.
  ENSURE_SERVING_ENDPOINTS_FAIL_DEPLOY="${ENSURE_SERVING_ENDPOINTS_FAIL_DEPLOY:-1}"
  set +e
  "${PYTHON_BIN}" "${ENSURE_SERVING_SCRIPT}"
  _ensure_se_rc=$?
  set -e
  if [[ "${_ensure_se_rc}" -ne 0 ]]; then
    echo "ERROR: serving endpoint(s) missing or not READY (Autograph LLM/embeddings will fail)." >&2
    if [[ "${ENSURE_SERVING_ENDPOINTS_FAIL_DEPLOY}" == "1" ]]; then
      exit 1
    fi
    echo "WARNING: continuing deploy (ENSURE_SERVING_ENDPOINTS_FAIL_DEPLOY=0)." >&2
  fi
fi

echo "App deployed - open in browser:"
print_deployed_app_urls

SET_USER_SCOPES_SCRIPT="${SCRIPT_DIR}/scripts/set_user_api_scopes.sh"
if [[ -x "${SET_USER_SCOPES_SCRIPT}" ]]; then
  echo "Setting user_api_scopes on '${APP_NAME}' for User authorization / OBO…"
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

echo "Granting UC table metadata read + annotation write (Add Tables /api/v1/uc) on ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA}…"
echo "  SELECT ON SCHEMA — list tables, read table/column metadata via WorkspaceClient"
echo "  MODIFY ON SCHEMA — COMMENT ON TABLE / ALTER COLUMN COMMENT when users click Save"
if ! run_sql_statement "GRANT SELECT ON SCHEMA ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"; then
  echo "NOTE: GRANT SELECT ON SCHEMA ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA} failed — Add Tables may not list or load UC tables." >&2
fi
if ! run_sql_statement "GRANT MODIFY ON SCHEMA ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA} TO \`${APP_SERVICE_PRINCIPAL_CLIENT_ID}\`"; then
  echo "NOTE: GRANT MODIFY ON SCHEMA ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA} failed — Add Tables cannot push annotations to UC." >&2
fi

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
echo "  Add Tables UC scope: SELECT + MODIFY on SCHEMA ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA}; other schemas need extra GRANTs"
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
