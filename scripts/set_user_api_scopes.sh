#!/usr/bin/env bash
# Set Databricks Apps *user* OAuth scopes on the dashboard app (enables
# x-forwarded-access-token for server-side calls to other Apps, e.g. Genie proxy).
#
# Prereqs (platform; cannot be automated from this repo alone):
#   - Workspace admin has enabled **User authorization** for Apps (Public Preview).
#   - Your user can run ``databricks apps update`` on this app.
#
# Docs: https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth
# API:  https://docs.databricks.com/api/workspace/apps/update
#
# Usage:
#   ./scripts/set_user_api_scopes.sh [APP_NAME] [PROFILE]
#
# Override scopes (comma-separated OAuth scope strings for Apps user tokens):
#   USER_API_SCOPES="apps,sql,dashboards.genie,catalog.catalogs:read" ./scripts/set_user_api_scopes.sh
#
# After a scope change, Databricks may require an app restart before headers appear;
# if /debug still shows x_forwarded_access_token_present false, try:
#   databricks apps stop  APP_NAME [--profile PROFILE]
#   databricks apps start APP_NAME [--profile PROFILE]

set -euo pipefail

APP_NAME="${1:-arango-workflow-app}"
PROFILE="${2:-}"

if [[ -n "${PROFILE}" ]]; then
  PROFILE_ARGS=(--profile "${PROFILE}")
else
  PROFILE_ARGS=()
fi

# Default: UC SQL + Genie + peer Apps (tune per least-privilege).
# Apps user tokens use granular scopes (``unity-catalog`` umbrella is rejected by apps update).
# Scope names: https://docs.databricks.com/api/workspace/api/scopes
RAW_SCOPES="${USER_API_SCOPES:-apps,sql,dashboards.genie,catalog.catalogs:read,catalog.schemas:read,catalog.tables:read}"

JSON_BODY="$(USER_API_SCOPES="${RAW_SCOPES}" python3 << 'PY'
import json, os
raw = os.environ.get("USER_API_SCOPES", "")
scopes = [s.strip() for s in raw.split(",") if s.strip()]
if not scopes:
    raise SystemExit("USER_API_SCOPES resolved to empty list")
print(json.dumps({"user_api_scopes": scopes}))
PY
)"

echo "Updating app ${APP_NAME} with user_api_scopes from USER_API_SCOPES (or default)…" >&2
if [[ ${#PROFILE_ARGS[@]} -gt 0 ]]; then
  databricks "${PROFILE_ARGS[@]}" apps update "${APP_NAME}" --json "${JSON_BODY}" >/dev/null
else
  databricks apps update "${APP_NAME}" --json "${JSON_BODY}" >/dev/null
fi
echo "OK: apps update returned success. Fetching effective scopes…" >&2
if [[ ${#PROFILE_ARGS[@]} -gt 0 ]]; then
  databricks "${PROFILE_ARGS[@]}" apps get "${APP_NAME}" --output json \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("user_api_scopes:", d.get("user_api_scopes")); print("effective_user_api_scopes:", d.get("effective_user_api_scopes"))'
else
  databricks apps get "${APP_NAME}" --output json \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("user_api_scopes:", d.get("user_api_scopes")); print("effective_user_api_scopes:", d.get("effective_user_api_scopes"))'
fi

echo >&2
echo "Next: open /debug on the app; expect dashboard_proxy_auth.x_forwarded_access_token_present true after you load the UI and consent (if prompted). If still false, restart the app (stop/start) and reload." >&2
