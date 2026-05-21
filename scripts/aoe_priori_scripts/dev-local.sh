#!/usr/bin/env bash
# Legacy copy — use ../dev-local.sh from repo root. No Docker.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "${ROOT}/scripts/dev-local.sh"
