"""Tests for schema_state persistence via gateway collections."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.db.gateway_database import GatewayCollection, GatewayDatabase
from migrations.runner import _save_schema_state


def test_gateway_collection_has_uses_get() -> None:
    db = MagicMock(spec=GatewayDatabase)
    db.name = "AutoGraph_1"
    col = GatewayCollection(db, "aoe_system_meta")
    col.get = MagicMock(return_value={"_key": "schema_state"})  # type: ignore[method-assign]

    assert col.has("schema_state") is True
    col.get.assert_called_once_with("schema_state")

    col.get.return_value = None  # type: ignore[attr-defined]
    assert col.has("schema_state") is False


def test_save_schema_state_inserts_when_missing() -> None:
    col = MagicMock()
    col.insert = MagicMock()
    col.replace = MagicMock()
    db = MagicMock()
    db.collection.return_value = col

    state = {"applied_migrations": [{"name": "001_initial_collections", "applied_at": 1.0}]}
    reads: list[int] = []

    def fake_doc_get(_col: MagicMock, key: str) -> dict | None:
        reads.append(1)
        return None if len(reads) == 1 else {"_key": key}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("migrations.runner.doc_get", fake_doc_get)
        _save_schema_state(db, state)

    col.insert.assert_called_once()
    col.replace.assert_not_called()
    inserted = col.insert.call_args[0][0]
    assert inserted["_key"] == "schema_state"


def test_save_schema_state_raises_when_read_back_empty() -> None:
    col = MagicMock()
    db = MagicMock()
    db.collection.return_value = col

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("migrations.runner.doc_get", lambda *_a, **_k: None)
        with pytest.raises(RuntimeError, match="Failed to persist"):
            _save_schema_state(db, {"applied_migrations": []})
