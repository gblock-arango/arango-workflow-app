"""Tests for deploy-time app.yaml secret injection."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from inject_app_yaml_secrets import (  # noqa: E402
    backup_path,
    inject_from_env,
    read_app_yaml_value,
    set_app_yaml_value,
)

_SAMPLE = """\
env:
  - name: OPENAI_API_KEY
    description: key
    value: ""
  - name: ANTHROPIC_API_KEY
    description: anthropic
    value: ""
"""


def test_set_and_read_roundtrip() -> None:
    updated = set_app_yaml_value(_SAMPLE, "OPENAI_API_KEY", "sk-test")
    assert read_app_yaml_value(updated, "OPENAI_API_KEY") == "sk-test"
    assert read_app_yaml_value(updated, "ANTHROPIC_API_KEY") == ""


def test_inject_from_env_only_set_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    text, injected = inject_from_env(_SAMPLE)
    assert injected == ["OPENAI_API_KEY"]
    assert read_app_yaml_value(text, "OPENAI_API_KEY") == "sk-from-env"


def test_prepare_recovers_stale_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text(_SAMPLE, encoding="utf-8")
    bak = backup_path(app_yaml)
    bak.write_text('env:\n  - name: OPENAI_API_KEY\n    value: ""\n', encoding="utf-8")
    app_yaml.write_text(
        'env:\n  - name: OPENAI_API_KEY\n    description: x\n    value: "stale"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fresh")
    from inject_app_yaml_secrets import cmd_prepare

    assert cmd_prepare(app_yaml) == 0
    assert read_app_yaml_value(app_yaml.read_text(encoding="utf-8"), "OPENAI_API_KEY") == "sk-fresh"


def test_prepare_restore_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text(_SAMPLE, encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-cycle")
    monkeypatch.chdir(tmp_path)
    sys.argv = ["inject_app_yaml_secrets.py", "prepare", str(app_yaml)]
    from inject_app_yaml_secrets import cmd_prepare, cmd_restore

    assert cmd_prepare(app_yaml) == 0
    assert read_app_yaml_value(app_yaml.read_text(encoding="utf-8"), "OPENAI_API_KEY") == "sk-cycle"
    assert backup_path(app_yaml).is_file()

    assert cmd_restore(app_yaml) == 0
    assert read_app_yaml_value(app_yaml.read_text(encoding="utf-8"), "OPENAI_API_KEY") == ""
    assert not backup_path(app_yaml).exists()
