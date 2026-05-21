#!/usr/bin/env python3
"""Read ``env:`` entry ``value`` from a Databricks App ``app.yaml`` (for deploy_app.sh)."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def read_app_yaml_value(app_yaml: Path, name: str) -> str:
    text = app_yaml.read_text(encoding="utf-8")
    # Match: - name: VAR ... value: "..." or value: '...' or value: bare
    pattern = (
        rf"-\s*name:\s*{re.escape(name)}\s*\n"
        r"(?:\s+[^\n]+\n)*?"
        r'\s+value:\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))'
    )
    m = re.search(pattern, text)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3) or "").strip()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: read_app_yaml_env.py NAME [app.yaml]", file=sys.stderr)
        return 2
    name = sys.argv[1]
    path = Path(sys.argv[2] if len(sys.argv) > 2 else "app.yaml")
    if not path.is_file():
        print("", end="")
        return 1
    print(read_app_yaml_value(path, name), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
