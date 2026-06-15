# Shared ``databricks apps deploy`` helpers for deploy_app.sh scripts.
#
# Callers must set: APP_NAME, SOURCE_CODE_PATH, PROFILE_ARGS (array), PYTHON_BIN
#
# Optional env:
#   DEPLOY_WAIT_ACTIVE_DEPLOYMENT_SEC — max wait for in-flight deployment (default 1200)
#   DEPLOY_WAIT_ACTIVE_DEPLOYMENT_POLL_SEC — poll interval while waiting (default 10)
#   DEPLOY_RETRY_SLEEP_SEC — pause between deploy retries after lock errors (default 15)
#   DEPLOY_TIMEOUT — ``apps deploy`` / ``apps start`` wait timeout (default 20m)
#   DEPLOY_FORCE_LOCK=1 — pass ``--force-lock`` on deploy attempts (stale lock recovery)
#   SKIP_APPS_START_BEFORE_DEPLOY=1 — never call ``apps start`` before deploy

if ! declare -F _databricks >/dev/null 2>&1; then
  _databricks() {
    if [[ ${#PROFILE_ARGS[@]} -gt 0 ]]; then
      databricks "${PROFILE_ARGS[@]}" "$@"
    else
      databricks "$@"
    fi
  }
fi

_apps_get_json() {
  _databricks apps get "${APP_NAME}" --output json 2>/dev/null
}

_app_deployment_field_state() {
  local json="$1" field="$2"
  DEPLOY_JSON="${json}" DEPLOY_FIELD="${field}" "${PYTHON_BIN}" -c '
import json, os
d = json.loads(os.environ["DEPLOY_JSON"])
dep = d.get(os.environ["DEPLOY_FIELD"]) or {}
print((dep.get("status") or {}).get("state", ""))
' 2>/dev/null || true
}

_deployment_state_in_flight() {
  local state="${1:-}"
  case "${state}" in
    IN_PROGRESS|PENDING|QUEUED|RUNNING) return 0 ;;
    *) return 1 ;;
  esac
}

_apps_deployments_in_flight() {
  local json="$1"
  local active pending
  active="$(_app_deployment_field_state "${json}" "active_deployment")"
  pending="$(_app_deployment_field_state "${json}" "pending_deployment")"
  if _deployment_state_in_flight "${active}"; then
    echo "active_deployment=${active}"
    return 0
  fi
  if _deployment_state_in_flight "${pending}"; then
    echo "pending_deployment=${pending}"
    return 0
  fi
  if [[ -n "${pending}" ]]; then
    echo "pending_deployment=${pending}"
    return 0
  fi
  return 1
}

_wait_for_apps_deploy_idle() {
  local json inflight waited=0
  local max_wait="${DEPLOY_WAIT_ACTIVE_DEPLOYMENT_SEC:-1200}"
  local poll="${DEPLOY_WAIT_ACTIVE_DEPLOYMENT_POLL_SEC:-10}"
  while (( waited < max_wait )); do
    if ! json="$(_apps_get_json)"; then
      echo "  Could not query app status; waiting ${poll}s…" >&2
      sleep "${poll}"
      waited=$((waited + poll))
      continue
    fi
    if inflight="$(_apps_deployments_in_flight "${json}")"; then
      echo "  Deployment still in flight (${inflight}); waiting ${poll}s…"
      sleep "${poll}"
      waited=$((waited + poll))
      continue
    fi
    return 0
  done
  echo "ERROR: timed out after ${max_wait}s waiting for in-flight app deployment." >&2
  return 1
}

ensure_app_running_before_deploy() {
  local json app_state compute_state
  if ! json="$(_apps_get_json)"; then
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
  # Compute is already up — ``apps deploy`` uploads code. ``apps start`` kicks off a competing
  # deployment and races with ``apps deploy`` ("pending deployment in progress").
  if [[ "${compute_state}" == "ACTIVE" ]]; then
    echo "NOTE: App '${APP_NAME}' compute is ACTIVE (app_status=${app_state:-unknown}); skipping \`databricks apps start\` — \`apps deploy\` uploads code."
    return 0
  fi
  echo "App '${APP_NAME}' is not RUNNING (app_status=${app_state:-unknown}, compute_status=${compute_state:-unknown})."
  echo "Trying \`databricks apps start\` so compute is ready…"
  if [[ "${SKIP_APPS_START_BEFORE_DEPLOY:-}" == "1" ]]; then
    echo "SKIP_APPS_START_BEFORE_DEPLOY=1: skipping databricks apps start; deploy may fail." >&2
    return 0
  fi
  _databricks apps start "${APP_NAME}" --timeout "${DEPLOY_TIMEOUT:-20m}"
  _wait_for_apps_deploy_idle || true
}

_is_deploy_lock_error() {
  echo "$1" | grep -qiE 'active deployment in progress|deployment in progress|pending deployment'
}

_deploy_app() {
  local deploy_out deploy_rc attempt=0
  local max_wait="${DEPLOY_WAIT_ACTIVE_DEPLOYMENT_SEC:-1200}"
  local poll="${DEPLOY_RETRY_SLEEP_SEC:-15}"
  local deadline=$((SECONDS + max_wait))
  local lock_flags=()

  if [[ "${DEPLOY_FORCE_LOCK:-}" == "1" ]]; then
    lock_flags=(--force-lock)
  fi

  while (( SECONDS < deadline )); do
    attempt=$((attempt + 1))
    set +e
    deploy_out="$(_databricks apps deploy "${APP_NAME}" \
      --source-code-path "${SOURCE_CODE_PATH}" \
      --timeout "${DEPLOY_TIMEOUT:-20m}" \
      "${lock_flags[@]}" 2>&1)"
    deploy_rc=$?
    set -e
    if [[ "${deploy_rc}" -eq 0 ]]; then
      if [[ "${attempt}" -gt 1 ]]; then
        echo "Deploy succeeded on attempt ${attempt}."
      fi
      return 0
    fi
    if _is_deploy_lock_error "${deploy_out}"; then
      echo "NOTE: (attempt ${attempt}) ${deploy_out}"
      echo "Waiting for the in-flight deployment to finish, then retrying deploy…"
      _wait_for_apps_deploy_idle || true
      sleep "${poll}"
      continue
    fi
    echo "${deploy_out}" >&2
    return "${deploy_rc}"
  done

  echo "ERROR: deploy failed — deployment lock still held after ~${max_wait}s." >&2
  echo "  An in-flight deployment may still succeed; check the Databricks Apps UI." >&2
  echo "  Retry shortly, or: DEPLOY_FORCE_LOCK=1 ./deploy_app.sh" >&2
  return 1
}
