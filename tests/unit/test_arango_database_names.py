"""Unit tests for per-run Arango database naming."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db.arango_database_names import (
    resolve_arango_database_name,
    suggest_auto_graph_database_name,
    validate_arango_database_name,
)


def test_validate_arango_database_name_accepts_auto_graph():
    assert validate_arango_database_name("AutoGraph_12") == "AutoGraph_12"


def test_validate_arango_database_name_rejects_invalid():
    with pytest.raises(ValueError, match="start with a letter"):
        validate_arango_database_name("9bad")


def test_suggest_auto_graph_database_name_increments():
    sys_db = MagicMock()
    sys_db.databases.return_value = ["_system", "AutoGraph_1", "AutoGraph_3", "Other"]

    with patch("app.db.client.get_system_db", return_value=sys_db):
        assert suggest_auto_graph_database_name() == "AutoGraph_4"


def test_resolve_arango_database_name_uses_request():
    assert resolve_arango_database_name("MyGraph_1") == "MyGraph_1"


def test_resolve_arango_database_name_suggests_when_empty():
    with patch(
        "app.db.arango_database_names.suggest_auto_graph_database_name",
        return_value="AutoGraph_7",
    ):
        assert resolve_arango_database_name(None) == "AutoGraph_7"
