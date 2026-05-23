"""Unit tests for gateway-mode database auto-creation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import DeploymentMode


def test_ensure_database_exists_creates_when_missing():
    from app.db import client as db_client

    db_client.close_db()

    settings = SimpleNamespace(
        arango_db="OntoExtract",
        can_create_databases=True,
        test_deployment_mode=DeploymentMode.SELF_MANAGED_PLATFORM,
    )
    sys_db = MagicMock()
    sys_db.has_database.return_value = False

    with (
        patch.object(db_client.app_config, "settings", settings),
        patch.object(db_client, "get_system_db", return_value=sys_db),
    ):
        db_client._ensure_database_exists()

    sys_db.create_database.assert_called_once_with("OntoExtract")


def test_ensure_database_exists_skips_when_present():
    from app.db import client as db_client

    settings = SimpleNamespace(
        arango_db="OntoExtract",
        can_create_databases=True,
        test_deployment_mode=DeploymentMode.SELF_MANAGED_PLATFORM,
    )
    sys_db = MagicMock()
    sys_db.has_database.return_value = True

    with (
        patch.object(db_client.app_config, "settings", settings),
        patch.object(db_client, "get_system_db", return_value=sys_db),
    ):
        db_client._ensure_database_exists()

    sys_db.create_database.assert_not_called()
