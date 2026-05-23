#!/usr/bin/env python3
"""Inject deploy-time secrets into app.yaml from the environment (deploy_app.sh)."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# Env var name -> app.yaml env entry name
_INJECT_FROM_ENV: tuple[tuple[str, str], ...] = (
    ("OPENAI_API_KEY", "OPENAI_API_KEY"),
    ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    ("OPENAI_BASE_URL", "OPENAI_BASE_URL"),
)

_BACKUP_SUFFIX = ".deploy-backup"


def backup_path(app_yaml: Path) -> Path:
    return app_yaml.with_name(app_yaml.name + _BACKUP_SUFFIX)


def read_app_yaml_value(text: str, name: str) -> str:
    pattern = (
        rf"-\s*name:\s*{re.escape(name)}\s*\n"
        r"(?:\s+[^\n]+\n)*?"
        r'\s+value:\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))'
    )
    m = re.search(pattern, text)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3) or "").strip()


def yaml_double_quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def set_app_yaml_value(text: str, name: str, new_value: str) -> str:
    pattern = (
        rf"(-\s*name:\s*{re.escape(name)}\s*\n"
        r"(?:\s+[^\n]+\n)*?"
        r"\s+value:\s*)(?:\"[^\"]*\"|'[^']*'|\S+)"
    )

    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1)}{yaml_double_quoted(new_value)}"

    updated, count = re.subn(pattern, repl, text, count=1)
    if count != 1:
        raise ValueError(f"app.yaml has no env entry named {name!r}")
    return updated


def inject_from_env(text: str) -> tuple[str, list[str]]:
    """Return updated text and list of yaml keys that were injected."""
    injected: list[str] = []
    for env_name, yaml_name in _INJECT_FROM_ENV:
        value = (os.environ.get(env_name) or "").strip()
        if not value:
            continue
        text = set_app_yaml_value(text, yaml_name, value)
        injected.append(yaml_name)
    return text, injected


def cmd_prepare(app_yaml: Path) -> int:
    bak = backup_path(app_yaml)
    if bak.exists():
        # Prior deploy may have exited before the EXIT trap restored app.yaml.
        shutil.copy2(bak, app_yaml)
        bak.unlink()
    shutil.copy2(app_yaml, bak)
    text = app_yaml.read_text(encoding="utf-8")
    updated, injected = inject_from_env(text)
    if not injected:
        print(
            "NOTE: no deploy secrets in environment "
            f"({', '.join(e for e, _ in _INJECT_FROM_ENV)}); app.yaml values unchanged.",
            file=sys.stderr,
        )
        app_yaml.write_text(updated, encoding="utf-8")
        return 0
    app_yaml.write_text(updated, encoding="utf-8")
    print(f"Injected into {app_yaml.name}: {', '.join(injected)}")
    return 0


def cmd_restore(app_yaml: Path) -> int:
    bak = backup_path(app_yaml)
    if not bak.is_file():
        return 0
    shutil.move(str(bak), str(app_yaml))
    print(f"Restored {app_yaml.name} from deploy backup.")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: inject_app_yaml_secrets.py prepare|restore APP_YAML",
            file=sys.stderr,
        )
        return 2
    command = sys.argv[1]
    app_yaml = Path(sys.argv[2])
    if not app_yaml.is_file():
        print(f"ERROR: not a file: {app_yaml}", file=sys.stderr)
        return 1
    if command == "prepare":
        return cmd_prepare(app_yaml)
    if command == "restore":
        return cmd_restore(app_yaml)
    print(f"ERROR: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
