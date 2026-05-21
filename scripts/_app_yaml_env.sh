#!/usr/bin/env bash
# shellcheck disable=SC2034
# Read deploy-time defaults from app.yaml (used by deploy_app.sh). Env vars still override.

_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_app_yaml_env() {
  local name="$1"
  local root="${SCRIPT_DIR:-$(cd "${_SCRIPTS_DIR}/.." && pwd)}"
  local app_yaml="${2:-${root}/app.yaml}"
  local py="${PYTHON_BIN:-python3}"
  local script="${_SCRIPTS_DIR}/read_app_yaml_env.py"
  if [[ ! -f "${app_yaml}" ]]; then
    return 1
  fi
  "${py}" "${script}" "${name}" "${app_yaml}" 2>/dev/null || true
}

# Resolve VAR: $1=shell var name, $2=app.yaml key (defaults to $1)
_resolve_from_app_yaml() {
  local var_name="$1"
  local yaml_key="${2:-${var_name}}"
  local current="${!var_name:-}"
  if [[ -n "${current// }" ]]; then
    return 0
  fi
  local from_yaml
  from_yaml="$(_app_yaml_env "${yaml_key}")"
  if [[ -n "${from_yaml}" ]]; then
    printf -v "${var_name}" '%s' "${from_yaml}"
  fi
}

load_deploy_config_from_app_yaml() {
  local app_yaml="${SCRIPT_DIR}/app.yaml"
  _resolve_from_app_yaml WAREHOUSE_ID DATABRICKS_SQL_WAREHOUSE_ID
  _resolve_from_app_yaml ARANGO_GATEWAY_REGISTRY_TABLE
  _resolve_from_app_yaml ARANGO_AGENT_REGISTRY_TABLE
  _resolve_from_app_yaml ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE
  _resolve_from_app_yaml ARANGO_WORKFLOW_REGISTRY_TABLE
  _resolve_from_app_yaml REGISTRY_TABLE ARANGO_REGISTRY_TABLE
  _resolve_from_app_yaml UC_GRAPH_VOLUME_NAME
  _resolve_from_app_yaml SERVICE_URL_PATH_PREFIX
}
