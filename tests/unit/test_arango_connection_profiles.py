"""Unit tests for Arango connection profiles (Connection page backend)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services import arango_connection_profiles as profiles


def test_parse_server_endpoint_host_only():
    host, protocol, port = profiles.parse_server_endpoint("gg8dcifd.rnd.pilot.arango.ai")
    assert host == "gg8dcifd.rnd.pilot.arango.ai"
    assert protocol == "https"
    assert port == 443


def test_parse_server_endpoint_with_port():
    host, protocol, port = profiles.parse_server_endpoint("http://127.0.0.1:18529")
    assert host == "127.0.0.1"
    assert protocol == "http"
    assert port == 18529


def test_save_and_load_profiles_masks_password(tmp_path):
    stored: dict[str, bytes] = {}

    def fake_write(*, relative_path: str, content: bytes) -> str:
        stored[relative_path] = content
        return relative_path

    def fake_read(relative_path: str) -> bytes:
        if relative_path not in stored:
            raise FileNotFoundError(relative_path)
        return stored[relative_path]

    with (
        patch.object(profiles.vol, "write_bytes", side_effect=fake_write),
        patch.object(profiles.vol, "read_bytes", side_effect=fake_read),
        patch.object(profiles.vol, "ensure_workflow_data_dirs"),
    ):
        created = profiles.create_connection_profile(display_name="AWS Prod", environment="aws")
        key = created["profile_key"]
        profiles.save_connection_profile(
            key,
            {
                "username": "root",
                "password": "secret123",
                "server_endpoint": "gg8dcifd.rnd.pilot.arango.ai",
                "cluster_name": "aws-prod",
            },
        )
        loaded = profiles.load_connection_profiles()

    assert key in loaded["profiles"]
    assert loaded["profiles"][key]["username"] == "root"
    assert loaded["profiles"][key]["password"] == ""
    assert loaded["profiles"][key]["password_set"] is True
    assert loaded["profiles"][key]["saved"] is True
    assert loaded["profiles"][key]["display_name"] == "AWS Prod"

    raw = json.loads(stored[profiles._PROFILES_REL].decode("utf-8"))
    assert raw["profiles"][key]["password"] == "secret123"


def test_save_profile_keeps_password_when_placeholder():
    stored = {
        profiles._PROFILES_REL: json.dumps(
            {
                "version": 2,
                "profiles": {
                    "aws-prod": {
                        "display_name": "AWS Prod",
                        "environment": "aws",
                        "cluster_name": "aws",
                        "username": "root",
                        "password": "keep-me",
                        "server_endpoint": "host.example",
                    }
                },
            }
        ).encode("utf-8")
    }

    def fake_write(*, relative_path: str, content: bytes) -> str:
        stored[relative_path] = content
        return relative_path

    def fake_read(relative_path: str) -> bytes:
        return stored[relative_path]

    with (
        patch.object(profiles.vol, "write_bytes", side_effect=fake_write),
        patch.object(profiles.vol, "read_bytes", side_effect=fake_read),
        patch.object(profiles.vol, "ensure_workflow_data_dirs"),
    ):
        profiles.save_connection_profile(
            "aws-prod",
            {
                "username": "root",
                "password": profiles._PASSWORD_PLACEHOLDER,
                "server_endpoint": "host.example",
            },
        )

    raw = json.loads(stored[profiles._PROFILES_REL].decode("utf-8"))
    assert raw["profiles"]["aws-prod"]["password"] == "keep-me"


@patch("app.services.arango_connection_profiles.execute_sql")
@patch("app.services.arango_connection_profiles.workflow_config_dict")
@patch.object(profiles.vol, "ensure_workflow_data_dirs")
@patch.object(profiles.vol, "write_bytes")
@patch.object(profiles.vol, "read_bytes")
def test_upsert_registry_for_profile(mock_read, mock_write, _ensure, mock_cfg, mock_sql):
    mock_cfg.return_value = {
        "ARANGO_REGISTRY_TABLE": "workspace.default.arango_connection_registry",
        "DATABRICKS_SQL_WAREHOUSE_ID": "wh1",
    }
    mock_read.return_value = json.dumps(
        {
            "version": 2,
            "profiles": {
                "aws-prod": {
                    "display_name": "AWS Prod",
                    "environment": "aws",
                    "cluster_name": "aws-prod",
                    "username": "root",
                    "password": "pw",
                    "server_endpoint": "gg8dcifd.rnd.pilot.arango.ai",
                }
            },
        }
    ).encode("utf-8")

    result = profiles.upsert_registry_for_profile("aws-prod")

    assert result["ok"] is True
    assert result["registry"]["ip_address"] == "gg8dcifd.rnd.pilot.arango.ai"
    assert result["active_profile_display_name"] == "AWS Prod"
    assert mock_sql.call_count == 2


def test_invalid_profile_key():
    with pytest.raises(ValueError, match="profile_key"):
        profiles.save_connection_profile("Azure Cloud!", {})


def test_upsert_requires_password():
    stored = {
        profiles._PROFILES_REL: json.dumps(
            {
                "version": 2,
                "profiles": {
                    "aws-prod": {
                        "display_name": "AWS Prod",
                        "environment": "aws",
                        "cluster_name": "aws-prod",
                        "username": "root",
                        "password": "",
                        "server_endpoint": "host.example",
                    }
                },
            }
        ).encode("utf-8")
    }

    with (
        patch.object(profiles.vol, "read_bytes", return_value=stored[profiles._PROFILES_REL]),
        patch(
            "app.services.arango_connection_profiles.workflow_config_dict",
            return_value={
                "ARANGO_REGISTRY_TABLE": "workspace.default.arango_connection_registry",
                "DATABRICKS_SQL_WAREHOUSE_ID": "wh1",
            },
        ),
    ):
        with pytest.raises(ValueError, match="password is required"):
            profiles.upsert_registry_for_profile("aws-prod")


def test_connection_ui_unset_when_no_saved_profiles():
    with patch.object(profiles.vol, "read_bytes", side_effect=FileNotFoundError):
        ui = profiles.connection_ui_for_ready(probe_ok=False, registry_ok=False)
    assert ui["ui_variant"] == "unset"
    assert ui["ui_message"] == "Click to Connect"


def test_connection_ui_failed_when_saved_but_not_connected():
    stored = {
        profiles._PROFILES_REL: json.dumps(
            {
                "version": 2,
                "active_profile": "local-dev",
                "profiles": {
                    "local-dev": {
                        "display_name": "Local Dev",
                        "environment": "local",
                        "cluster_name": "local-minikube-dev",
                        "username": "root",
                        "password": "pw",
                        "server_endpoint": "127.0.0.1",
                    }
                },
            }
        ).encode("utf-8")
    }
    with patch.object(profiles.vol, "read_bytes", return_value=stored[profiles._PROFILES_REL]):
        ui = profiles.connection_ui_for_ready(probe_ok=False, registry_ok=False)
    assert ui["ui_variant"] == "failed"
    assert ui["ui_message"] == "Connection Failed"
    assert ui["active_profile_display_name"] == "Local Dev"


def test_connection_ui_connected_shows_profile_name():
    stored = {
        profiles._PROFILES_REL: json.dumps(
            {
                "version": 2,
                "active_profile": "aws-prod",
                "profiles": {
                    "aws-prod": {
                        "display_name": "AWS Production",
                        "environment": "aws",
                        "cluster_name": "aws-prod",
                        "username": "root",
                        "password": "pw",
                        "server_endpoint": "host.example",
                    }
                },
            }
        ).encode("utf-8")
    }
    with patch.object(profiles.vol, "read_bytes", return_value=stored[profiles._PROFILES_REL]):
        ui = profiles.connection_ui_for_ready(probe_ok=True, registry_ok=True)
    assert ui["ui_variant"] == "connected"
    assert ui["ui_message"] == "AWS Production"
