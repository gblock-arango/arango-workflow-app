"""Unit tests for gateway-mode database auto-creation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import DeploymentMode


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        arango_db="OntoExtract",
        can_create_databases=True,
        test_deployment_mode=DeploymentMode.SELF_MANAGED_PLATFORM,
    )


def test_ensure_database_exists_creates_per_run_database_when_missing():
    from app.db import client as db_client

    db_client.close_db()
    sys_db = MagicMock()
    sys_db.has_database.return_value = False

    with (
        patch.object(db_client.app_config, "settings", _settings()),
        patch.object(db_client, "get_system_db", return_value=sys_db),
    ):
        db_client.set_active_arango_database("AutoGraph_1")
        db_client._ensure_database_exists(db_name="AutoGraph_1")

    sys_db.create_database.assert_called_once_with("AutoGraph_1")
    db_client.clear_active_arango_database()


def test_ensure_database_exists_skips_env_default_without_thread_pin():
    from app.db import client as db_client

    db_client.close_db()
    sys_db = MagicMock()
    sys_db.has_database.return_value = False

    with (
        patch.object(db_client.app_config, "settings", _settings()),
        patch.object(db_client, "get_system_db", return_value=sys_db),
    ):
        db_client._ensure_database_exists(db_name="OntoExtract")

    sys_db.create_database.assert_not_called()
    sys_db.has_database.assert_not_called()


def test_ensure_database_exists_never_creates_legacy_env_default_even_when_pinned():
    from app.db import client as db_client

    db_client.close_db()
    sys_db = MagicMock()
    sys_db.has_database.return_value = False

    with (
        patch.object(db_client.app_config, "settings", _settings()),
        patch.object(db_client, "get_system_db", return_value=sys_db),
    ):
        db_client.set_active_arango_database("OntoExtract")
        db_client._ensure_database_exists(db_name="OntoExtract")

    sys_db.create_database.assert_not_called()
    db_client.clear_active_arango_database()


def test_ensure_database_exists_recreates_when_database_missing():
    from app.db import client as db_client

    db_client.close_db()
    sys_db = MagicMock()
    sys_db.has_database.return_value = False

    with (
        patch.object(db_client.app_config, "settings", _settings()),
        patch.object(db_client, "get_system_db", return_value=sys_db),
    ):
        db_client.set_active_arango_database("AutoGraph_2")
        db_client._ensure_database_exists(db_name="AutoGraph_2")

    sys_db.create_database.assert_called_once_with("AutoGraph_2")
    db_client.clear_active_arango_database()


def test_ensure_database_exists_skips_when_present():
    from app.db import client as db_client

    db_client.close_db()
    sys_db = MagicMock()
    sys_db.has_database.return_value = True

    with (
        patch.object(db_client.app_config, "settings", _settings()),
        patch.object(db_client, "get_system_db", return_value=sys_db),
    ):
        db_client.set_active_arango_database("AutoGraph_1")
        db_client._ensure_database_exists(db_name="AutoGraph_1")

    sys_db.create_database.assert_not_called()
    db_client.clear_active_arango_database()
