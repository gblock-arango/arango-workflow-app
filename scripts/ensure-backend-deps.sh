#!/usr/bin/env bash
# Idempotent repo-root venv + dev deps (arango-workflow-app uses src/ layout, not backend/).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ ! -x .venv/bin/python ]]; then
  echo "==> Creating .venv (uv if available, else stdlib venv)..."
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv
  else
    python3 -m venv .venv
  fi
fi

PY=".venv/bin/python"

if command -v uv >/dev/null 2>&1; then
  echo "==> uv pip install -e \".[dev]\" (--python ${PY})"
  uv pip install -e ".[dev]" --python "${PY}"
elif "${PY}" -m pip --version >/dev/null 2>&1; then
  echo "==> python -m pip install -e \".[dev]\""
  "${PY}" -m pip install -e ".[dev]"
else
  echo "==> bootstrapping pip via ensurepip..."
  "${PY}" -m ensurepip --upgrade --default-pip
  "${PY}" -m pip install -e ".[dev]"
fi
