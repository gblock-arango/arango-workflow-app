"""Unit tests for grant_autograph_serving_permissions ACL merge."""

from __future__ import annotations

from unittest.mock import MagicMock

from scripts.grant_autograph_serving_permissions import (
    _resolve_serving_endpoint_id,
    grant_can_query,
)


def test_resolve_serving_endpoint_id_maps_name_to_id():
    se_api = MagicMock()
    se_api.get.return_value = MagicMock(id="ep-uuid-123", name="databricks-bge-large-en")

    assert _resolve_serving_endpoint_id(se_api, "databricks-bge-large-en") == "ep-uuid-123"
    se_api.get.assert_called_once_with("databricks-bge-large-en")


def test_grant_can_query_skips_when_sp_already_has_query():
    w = MagicMock()
    entry = MagicMock()
    entry.service_principal_name = "sp-123"
    entry.user_name = None
    entry.group_name = None
    from databricks.sdk.service.serving import ServingEndpointPermissionLevel

    entry.permission_level = ServingEndpointPermissionLevel.CAN_QUERY
    perms = MagicMock()
    perms.access_control_list = [entry]
    w.serving_endpoints.get.return_value = MagicMock(id="ep-llama", name="llama")
    w.serving_endpoints.get_permissions.return_value = perms

    assert grant_can_query(w, endpoint_name="llama", service_principal_id="sp-123") is True
    w.serving_endpoints.get_permissions.assert_called_once_with("ep-llama")
    w.serving_endpoints.set_permissions.assert_not_called()
