#!/usr/bin/env bash
# Probe Autograph LLM + embedding serving endpoints from your laptop (Databricks CLI auth).
set -euo pipefail

EMB="${AUTOGRAPH_EMBEDDING_MODEL_NAME:-databricks-bge-large-en}"
LLM="${AUTOGRAPH_LLM_MODEL_NAME:-databricks-meta-llama-3-3-70b-instruct}"

if [[ -f "$(dirname "$0")/_app_yaml_env.sh" ]]; then
  # shellcheck source=scripts/_app_yaml_env.sh
  source "$(dirname "$0")/_app_yaml_env.sh"
  _resolve_from_app_yaml AUTOGRAPH_EMBEDDING_MODEL_NAME
  _resolve_from_app_yaml AUTOGRAPH_LLM_MODEL_NAME
  EMB="${AUTOGRAPH_EMBEDDING_MODEL_NAME:-$EMB}"
  LLM="${AUTOGRAPH_LLM_MODEL_NAME:-$LLM}"
fi

if command -v python3 >/dev/null 2>&1; then
  SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
  EMB="$(PYTHONPATH="${SCRIPT_DIR}/src" RAW="${EMB}" python3 -c \
    'from app.llm.databricks_serving import normalize_serving_endpoint_name; import os; print(normalize_serving_endpoint_name(os.environ["RAW"]))')"
fi

echo "=== Serving endpoint metadata ==="
for ep in "${EMB}" "${LLM}"; do
  echo "--- ${ep} ---"
  databricks serving-endpoints get "${ep}" -o json 2>&1 | python3 -c '
import json,sys
try:
  d=json.load(sys.stdin)
except json.JSONDecodeError:
  print(sys.stdin.read())
  sys.exit(1)
st=d.get("state") or {}
print("  name:", d.get("name"))
print("  ready:", (st.get("ready") if isinstance(st,dict) else st))
' || echo "  (get failed — wrong name or no access)"
done

echo ""
echo "=== Embedding invocation (OpenAI-compatible) ==="
echo "  model/endpoint: ${EMB}"
databricks serving-endpoints query "${EMB}" --json "$(cat <<EOF
{"input": ["connectivity probe"]}
EOF
)" 2>&1 | head -c 800
echo ""

echo ""
echo "=== Chat invocation ==="
echo "  model/endpoint: ${LLM}"
databricks serving-endpoints query "${LLM}" --json "$(cat <<EOF
{
  "messages": [{"role": "user", "content": "Reply with exactly OK."}],
  "max_tokens": 32
}
EOF
)" 2>&1 | head -c 800
echo ""
