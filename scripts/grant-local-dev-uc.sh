#!/usr/bin/env bash
# Ensure UC tables exist and grant privileges to the local_dev identity (CLI user).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export SCRIPT_DIR="${ROOT}"

# shellcheck source=scripts/load-app-yaml-env.sh
source "${SCRIPT_DIR}/scripts/load-app-yaml-env.sh"
# shellcheck source=scripts/_app_yaml_env.sh
source "${SCRIPT_DIR}/scripts/_app_yaml_env.sh"
load_deploy_config_from_app_yaml

if [[ -x "${ROOT}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${ROOT}/.venv/bin/python3"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python3" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python3"
else
  PYTHON_BIN="python3"
fi
export PYTHON_BIN

PROFILE="${DATABRICKS_CONFIG_PROFILE:-}"
if [[ -n "${PROFILE}" ]]; then
  export PROFILE
  PROFILE_ARGS=(--profile "${PROFILE}")
else
  PROFILE_ARGS=()
fi
export PROFILE_ARGS

WAREHOUSE_ID="${WAREHOUSE_ID:-${DATABRICKS_SQL_WAREHOUSE_ID:-}}"
if [[ -z "${WAREHOUSE_ID// }" ]]; then
  echo "ERROR: DATABRICKS_SQL_WAREHOUSE_ID is required for local_dev UC grants." >&2
  exit 1
fi

# shellcheck source=scripts/_databricks_sql_lib.sh
source "${SCRIPT_DIR}/scripts/_databricks_sql_lib.sh"

EMBEDDING_STATUS_TABLE="${EMBEDDING_STATUS_TABLE:-workspace.default.embedding_status}"
REGISTRY_TABLE="${REGISTRY_TABLE:-workspace.default.arango_connection_registry}"
ARANGO_GATEWAY_REGISTRY_TABLE="${ARANGO_GATEWAY_REGISTRY_TABLE:-workspace.default.arango_gateway_registry}"
ARANGO_AGENT_REGISTRY_TABLE="${ARANGO_AGENT_REGISTRY_TABLE:-workspace.default.arango_agent_registry}"
ARANGO_WORKFLOW_REGISTRY_TABLE="${ARANGO_WORKFLOW_REGISTRY_TABLE:-workspace.default.arango_workflow_registry}"
ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE="${ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE:-}"

resolve_cli_user() {
  local name="" json=""
  if [[ -n "${LOCAL_DEV_UC_GRANTEE:-}" ]]; then
    echo "${LOCAL_DEV_UC_GRANTEE}"
    return 0
  fi
  name="$(
    PYTHONPATH="${ROOT}/src" "${PYTHON_BIN}" -c "
import sys
try:
    from databricks.sdk import WorkspaceClient
    me = WorkspaceClient().current_user.me()
    print((me.user_name or '').strip())
except Exception:
    sys.exit(1)
" 2>/dev/null
  )" || true
  if [[ -n "${name}" ]]; then
    echo "${name}"
    return 0
  fi
  json="$(databricks current-user me -o json "${PROFILE_ARGS[@]}" 2>/dev/null || echo '{}')"
  name="$("${PYTHON_BIN}" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("userName") or d.get("user_name") or "").strip())' <<< "${json}" 2>/dev/null || true)"
  if [[ -n "${name}" ]]; then
    echo "${name}"
    return 0
  fi
  return 1
}

CLI_USER="$(resolve_cli_user)" || {
  echo "ERROR: could not resolve CLI user (run 'databricks auth login' or set LOCAL_DEV_UC_GRANTEE)." >&2
  exit 1
}
GRANTEE="\`${CLI_USER}\`"
echo "local_dev UC grants for user '${CLI_USER}' (warehouse ${WAREHOUSE_ID})"

_failures=0
_run_grant() {
  local desc="$1"
  local sql="$2"
  local required="${3:-optional}"
  echo "==> ${desc}"
  if run_sql_statement "${sql}"; then
    return 0
  fi
  echo "WARNING: ${desc} failed — ${sql}" >&2
  if [[ "${required}" == "required" ]]; then
    _failures=$((_failures + 1))
  fi
  return 1
}

REGISTRY_CATALOG="$(echo "${REGISTRY_TABLE}" | cut -d. -f1)"
REGISTRY_SCHEMA="$(echo "${REGISTRY_TABLE}" | cut -d. -f2)"

_run_grant "USE CATALOG on ${REGISTRY_CATALOG}" \
  "GRANT USE CATALOG ON CATALOG ${REGISTRY_CATALOG} TO ${GRANTEE}" required || true
_run_grant "USE SCHEMA on ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA}" \
  "GRANT USE SCHEMA ON SCHEMA ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA} TO ${GRANTEE}" required || true

echo "Ensuring embedding_status table ${EMBEDDING_STATUS_TABLE}..."
_ee_ensure=(env)
if [[ -n "${PROFILE}" ]]; then
  _ee_ensure+=("DATABRICKS_CONFIG_PROFILE=${PROFILE}")
fi
_ee_ensure+=(-u DATABRICKS_CLIENT_ID -u DATABRICKS_CLIENT_SECRET)
_ee_ensure+=(PYTHONPATH="${ROOT}/src" "${PYTHON_BIN}" -c "
import os
os.environ.setdefault('EMBEDDING_STATUS_TABLE', '${EMBEDDING_STATUS_TABLE}')
os.environ.setdefault('DATABRICKS_SQL_WAREHOUSE_ID', '${WAREHOUSE_ID}')
from app.services.embedding_status import ensure_embedding_status_table
ensure_embedding_status_table()
")
"${_ee_ensure[@]}"

_run_grant "SELECT, MODIFY on ${EMBEDDING_STATUS_TABLE}" \
  "GRANT SELECT, MODIFY ON TABLE ${EMBEDDING_STATUS_TABLE} TO ${GRANTEE}" required || true

_run_grant "SELECT on schema ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA}" \
  "GRANT SELECT ON SCHEMA ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA} TO ${GRANTEE}" optional || true
_run_grant "MODIFY on schema ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA}" \
  "GRANT MODIFY ON SCHEMA ${REGISTRY_CATALOG}.${REGISTRY_SCHEMA} TO ${GRANTEE}" optional || true

for tbl in \
  "${REGISTRY_TABLE}" \
  "${ARANGO_GATEWAY_REGISTRY_TABLE}" \
  "${ARANGO_AGENT_REGISTRY_TABLE}" \
  "${ARANGO_WORKFLOW_REGISTRY_TABLE}" \
  "${ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE}"; do
  [[ -n "${tbl// }" ]] || continue
  _run_grant "SELECT on ${tbl}" \
    "GRANT SELECT ON TABLE ${tbl} TO ${GRANTEE}" optional || true
done

if [[ "${_failures}" -gt 0 ]]; then
  echo "ERROR: ${_failures} required local_dev UC grant(s) failed." >&2
  exit 1
fi

echo "local_dev UC grants complete."
