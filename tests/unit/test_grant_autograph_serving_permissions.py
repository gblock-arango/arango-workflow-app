"""Unit tests for grant_autograph_serving_permissions ACL merge."""

from __future__ import annotations

from unittest.mock import MagicMock

from scripts.grant_autograph_serving_permissions import grant_can_query


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
    w.serving_endpoints.get_permissions.return_value = perms

    assert grant_can_query(w, endpoint_name="llama", service_principal_id="sp-123") is True
    w.serving_endpoints.set_permissions.assert_not_called()
