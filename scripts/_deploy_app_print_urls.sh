# shellcheck shell=bash
# URL helpers for deploy_app.sh (source after APP_URL / APP_JSON are set).

_workflow_public_base_url() {
  local base="${1%/}"
  local prefix="${SERVICE_URL_PATH_PREFIX:-}"
  prefix="${prefix%/}"
  if [[ -n "${prefix}" ]]; then
    [[ "${prefix}" != /* ]] && prefix="/${prefix}"
    printf '%s%s' "${base}" "${prefix}"
  else
    printf '%s' "${base}"
  fi
}

_parse_app_url_numeric_suffix() {
  local json="$1"
  APP_JSON="${json}" "${PYTHON_BIN:-python3}" -c "
import json, os
from urllib.parse import urlparse
j = json.loads(os.environ['APP_JSON'])
url = j.get('url', '') or ''
host = urlparse(url).hostname or ''
sub = host.split('.')[0] if host else ''
parts = sub.rsplit('-', 1)
print(parts[1] if len(parts) == 2 and parts[1].isdigit() else '')
"
}

print_deployed_app_urls() {
  local home_url="${APP_HOME_URL:-}"
  local dashboard_url="${APP_DASHBOARD_URL:-}"
  if [[ -z "${home_url}" ]]; then
    home_url="$(_workflow_public_base_url "${APP_URL}")"
    dashboard_url="${home_url%/}/dashboard"
    APP_HOME_URL="${home_url}"
    APP_DASHBOARD_URL="${dashboard_url}"
  fi
  echo
  echo "DATABRICKS_APP_URL=${APP_URL}"
  echo "DATABRICKS_APP_HOME_URL=${APP_HOME_URL}"
  echo "DATABRICKS_APP_DASHBOARD_URL=${APP_DASHBOARD_URL}"
  printf '  \033]8;;%s\033\\%s\033]8;;\033\\\n' "${APP_DASHBOARD_URL}" "-> Open OntoExtract UI /dashboard"
  printf '  \033]8;;%s\033\\%s\033]8;;\033\\\n' "${APP_HOME_URL}" "-> Open app home /"
  if [[ -n "${APP_URL_NUMERIC_SUFFIX:-}" ]]; then
    echo "DATABRICKS_APP_URL_NUMERIC_SUFFIX=${APP_URL_NUMERIC_SUFFIX}  (from apps get url hostname)"
  else
    echo "DATABRICKS_APP_URL_NUMERIC_SUFFIX=  (could not parse; check hostname pattern)"
  fi
  if [[ -n "${APP_RESOURCE_ID:-}" ]]; then
    echo "DATABRICKS_APP_RESOURCE_ID=${APP_RESOURCE_ID}  (id from apps get JSON)"
  fi
  echo
}
