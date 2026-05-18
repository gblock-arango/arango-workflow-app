"""Unit tests for migration 019 (expired sentinel backfill)."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest

NEVER = sys.maxsize


@pytest.fixture()
def mod019():
    return importlib.import_module("migrations.019_backfill_expired_sentinel")


def test_backfill_collection_updates_matching_documents(
    mod019,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_backfill_collection runs AQL that sets expired to NEVER_EXPIRES."""
    captured: list[dict] = []

    def fake_run_aql(db, query: str, bind_vars: dict | None = None):
        captured.append({"query": query, "bind_vars": bind_vars or {}})
        return iter([2])

    monkeypatch.setattr(mod019, "run_aql", fake_run_aql)

    db = MagicMock()
    db.has_collection.return_value = True

    n = mod019._backfill_collection(db, "ontology_classes")
    assert n == 2
    assert captured, "run_aql should be called"
    assert captured[0]["bind_vars"]["@col"] == "ontology_classes"
    assert captured[0]["bind_vars"]["never"] == NEVER
    assert "UPDATE doc WITH { expired: @never }" in captured[0]["query"]


def test_backfill_skips_missing_collection(mod019) -> None:
    db = MagicMock()
    db.has_collection.return_value = False
    assert mod019._backfill_collection(db, "missing") == 0


def test_never_expires_matches_app_sentinel(mod019) -> None:
    assert mod019.NEVER_EXPIRES == NEVER
