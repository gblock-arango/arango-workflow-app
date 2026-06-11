"""Idempotent create when Arango database/collection already exists."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db.gateway_database import GatewayAPIError


def test_ensure_database_exists_treats_duplicate_name_as_ok():
    from app.db import client as db_client

    db_client.close_db()
    sys_db = MagicMock()
    sys_db.has_database.return_value = False
    sys_db.create_database.side_effect = GatewayAPIError("duplicate name", error_code=1207)

    with patch.object(db_client, "get_system_db", return_value=sys_db):
        db_client.set_active_arango_database("AutoGraph_1")
        db_client._ensure_database_exists(db_name="AutoGraph_1")

    sys_db.create_database.assert_called_once_with("AutoGraph_1")
    db_client.clear_active_arango_database()


def test_get_collection_treats_duplicate_name_as_ok():
    from app.services import extraction as extraction_svc

    db = MagicMock()
    db.has_collection.return_value = False
    db.create_collection.side_effect = GatewayAPIError("duplicate name", error_code=1210)
    col = MagicMock()
    db.collection.return_value = col

    out = extraction_svc._get_collection(db, "extraction_runs")
    assert out is col
    db.collection.assert_called_once_with("extraction_runs")
