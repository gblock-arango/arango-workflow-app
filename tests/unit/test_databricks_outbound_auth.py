"""Outbound Databricks Apps auth (peer app calls)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.workflow_platform.databricks_outbound_auth import (
    capture_outbound_bearer_from_request,
    outbound_databricks_auth_headers,
    reset_outbound_bearer_override,
    reset_outbound_service_principal_mode,
    set_outbound_bearer_override,
    set_outbound_service_principal_mode,
)


def test_capture_prefers_x_forwarded_access_token():
    req = MagicMock()
    req.headers.items.return_value = [("x-forwarded-access-token", "user-token-abc")]
    with patch(
        "app.workflow_platform.databricks_outbound_auth.current_request",
        return_value=req,
    ):
        assert capture_outbound_bearer_from_request() == "user-token-abc"


def test_outbound_bearer_override_used_without_request():
    token = set_outbound_bearer_override("thread-token")
    try:
        with patch(
            "app.workflow_platform.databricks_outbound_auth.current_request",
            return_value=None,
        ):
            headers = outbound_databricks_auth_headers()
        assert headers == {"Authorization": "Bearer thread-token"}
    finally:
        reset_outbound_bearer_override(token)


def test_force_service_principal_skips_copied_user_token():
    req = MagicMock()
    req.headers.items.return_value = [("x-forwarded-access-token", "user-token-abc")]
    sp_mode = set_outbound_service_principal_mode(True)
    try:
        with patch(
            "app.workflow_platform.databricks_outbound_auth.current_request",
            return_value=req,
        ), patch("databricks.sdk.WorkspaceClient") as mock_wc:
            mock_wc.return_value.config.authenticate.return_value = {
                "Authorization": "Bearer sp-token"
            }
            headers = outbound_databricks_auth_headers()
        assert headers == {"Authorization": "Bearer sp-token"}
    finally:
        reset_outbound_service_principal_mode(sp_mode)
