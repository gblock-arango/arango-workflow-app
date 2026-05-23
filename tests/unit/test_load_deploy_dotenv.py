"""Tests for load_deploy_dotenv.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "load_deploy_dotenv.py"


def test_emits_only_whitelisted_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_API_KEY=sk-test\n"
        "APP_SECRET_KEY=ignored\n"
        "# OPENAI_API_KEY=comment\n"
        "ANTHROPIC_API_KEY=\n",
        encoding="utf-8",
    )
    out = subprocess.check_output([sys.executable, str(_SCRIPT), str(env)], text=True)
    assert "OPENAI_API_KEY=" in out
    assert "APP_SECRET_KEY" not in out
    assert "ANTHROPIC_API_KEY=" in out
