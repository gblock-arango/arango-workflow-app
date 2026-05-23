#!/usr/bin/env python3
"""Emit shell ``export`` lines for deploy-time secrets (used by deploy_app.sh)."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

_DEPLOY_KEYS = frozenset({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"})


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in _DEPLOY_KEYS:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key] = val
    return values


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    values = _parse_dotenv(path)
    for key in sorted(values):
        print(f"export {key}={shlex.quote(values[key])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
