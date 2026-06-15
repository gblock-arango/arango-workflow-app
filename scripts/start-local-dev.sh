#!/usr/bin/env bash
# Local dev: uvicorn API on :8010 + Next.js on :3000 (see scripts/dev-local.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/load-app-yaml-env.sh
source "${ROOT}/scripts/load-app-yaml-env.sh"

export BACKEND_PORT="${BACKEND_PORT:-8010}"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

exec bash "${ROOT}/scripts/dev-local.sh"
