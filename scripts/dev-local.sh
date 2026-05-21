#!/usr/bin/env bash
# Start FastAPI + Next.js in one terminal. Ctrl+C stops both app processes.
# Arango: arango-gateway-app (UC registry or ARANGO_GATEWAY_BASE_URL). No Docker.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${BACKEND_PORT:-8010}"
export BACKEND_PROXY_URL="${BACKEND_PROXY_URL:-http://127.0.0.1:${PORT}}"
export PYTHONPATH="${ROOT}/src"

UV="${ROOT}/.venv/bin/uvicorn"
if [[ ! -x "$UV" ]]; then
  echo "error: missing $UV — run: make setup" >&2
  exit 1
fi

cleanup() {
  if [[ -n "${API_PID:-}" ]] && kill -0 "$API_PID" 2>/dev/null; then
    echo ""
    echo "==> Stopping API (pid $API_PID)"
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

echo "==> Arango via arango-gateway-app (set ARANGO_GATEWAY_BASE_URL or UC registry in .env)"
echo "==> Redis: set REDIS_URL in .env, or RATE_LIMIT_ENABLED=false if none"
echo ""

echo "==> API  http://127.0.0.1:${PORT}   (proxy ${BACKEND_PROXY_URL})"
echo "==> UI   http://localhost:3000"
echo ""

(cd "$ROOT" && exec env PYTHONPATH=src "$UV" app.main:app --reload --host 127.0.0.1 --port "$PORT") &
API_PID=$!

ok=0
for _ in $(seq 1 60); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "error: API process exited — check logs above" >&2
    exit 1
  fi
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 || curl -sf "http://127.0.0.1:${PORT}/ready" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 0.2
done

if [[ "$ok" -ne 1 ]]; then
  echo "error: API did not become ready on port ${PORT}" >&2
  exit 1
fi

echo "==> API is up — starting Next.js"
cd "$ROOT/src/frontend"
npm run dev
