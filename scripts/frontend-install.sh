#!/usr/bin/env bash
# Clean npm install for src/frontend (fixes missing @tailwindcss/oxide native bindings).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="${ROOT}/src/frontend"

cd "${FRONTEND}"
echo "Removing node_modules and package-lock.json in ${FRONTEND}…"
rm -rf node_modules package-lock.json

echo "Installing dependencies (includes platform-native Tailwind bindings)…"
npm install

if [[ ! -d node_modules/@tailwindcss/oxide-linux-x64-gnu ]]; then
  echo "Installing @tailwindcss/oxide-linux-x64-gnu explicitly…" >&2
  npm install @tailwindcss/oxide-linux-x64-gnu@4.3.0 --save
fi

echo "Done. Run: cd src/frontend && npm run dev"
