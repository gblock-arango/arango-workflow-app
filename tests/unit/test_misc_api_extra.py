"""Additional coverage for small API modules."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from app.api.auth import (
    _MOCK_USER,
    AuthenticatedUser,
    LoginRequest,
    LoginResponse,
    _error_response,
    authenticate_websocket,
    login,
    user_from_claims,
)
from app.api.er import (
    ERConfigUpdate,
    ERCrossTierRequest,
    ERExplainRequest,
    ERMergeRequest,
    ERRunRequest,
    cross_tier_candidates,
    execute_merge,
    explain_match,
    get_er_config,
    get_er_run_status,
    list_candidates,
    list_clusters,
    trigger_er_run,
    update_er_config,
)
from app.api.errors import NotFoundError
from app.api.health import health, ready
from app.api.notifications import (
    get_unread_count,
    list_notifications,
    mark_notification_read,
)


class TestHealthRoutes:
    @pytest.mark.asyncio
    async def test_health_and_ready(self):
        with patch("app.api.health.get_db") as mock_get_db:
            mock_get_db.return_value.version.return_value = "3.12"
            healthy = await health()
            ready_result = await ready()

        with patch("app.api.health.get_db", side_effect=RuntimeError("db down")):
            not_ready = await ready()

        assert healthy == {"status": "ok"}
        assert ready_result == {"status": "ready", "database": "connected"}
        assert not_ready == {"status": "not_ready", "database": "db down"}


class TestNotificationRoutes:
    @pytest.mark.asyncio
    async def test_list_mark_read_and_unread_count(self):
        user = AuthenticatedUser(user_id="u1", org_id="o1")
        with (
            patch("app.api.notifications.notif_svc.list_notifications", return_value={"data": []}),
            patch(
                "app.api.notifications.notif_svc.mark_as_read",
                side_effect=[{"_key": "n1"}, None],
            ),
            patch("app.api.notifications.notif_svc.get_unread_count", return_value=3),
        ):
            listing = await list_notifications(limit=5, cursor=None, user=user)
            marked = await mark_notification_read("n1", user=user)
            unread = await get_unread_count(user=user)

            with pytest.raises(NotFoundError):
                await mark_notification_read("missing", user=user)

        assert listing == {"data": []}
        assert marked == {"_key": "n1"}
        assert unread == {"unread_count": 3}


class TestERRoutes:
    @pytest.mark.asyncio
    async def test_run_and_status_routes(self):
        run = SimpleNamespace(
            run_id="er1",
            status="completed",
            candidate_count=4,
            cluster_count=2,
            duration_seconds=1.5,
            error=None,
            config=SimpleNamespace(ontology_id="onto1"),
        )
        config = MagicMock()
        config.to_dict.side_effect = lambda: {"similarity_threshold": 0.8}
        updated = MagicMock()
        updated.to_dict.return_value = {"similarity_threshold": 0.9}

        with (
            patch("app.api.er.er_svc.ERPipelineConfig.from_dict", return_value="cfg"),
            patch("app.api.er.er_svc.run_er_pipeline", return_value=run),
            patch("app.api.er.er_svc.get_run_status", return_value=run),
            patch("app.api.er.er_svc.get_candidates", return_value=[{"score": 0.9}]),
            patch("app.api.er.er_svc.get_clusters", return_value=[{"members": 2}]),
            patch("app.api.er.er_svc.explain_match", return_value={"combined_score": 0.95}),
            patch("app.api.er.er_svc.execute_merge", return_value={"merged": True}),
            patch("app.api.er.er_svc.get_cross_tier_candidates", return_value=[{"key": "c1"}]),
            patch("app.api.er.er_svc.get_config", return_value=config),
            patch("app.api.er.er_svc.update_config", return_value=updated),
        ):
            run_result = await trigger_er_run(ERRunRequest(ontology_id="onto1", config={"x": 1}))
            status = await get_er_run_status("er1")
            candidates = await list_candidates("er1", min_score=0.5, limit=10, offset=0)
            clusters = await list_clusters("er1")
            explanation = await explain_match(ERExplainRequest(key1="a", key2="b"))
            merged = await execute_merge(ERMergeRequest(source_key="a", target_key="b"))
            cross_tier = await cross_tier_candidates(
                ERCrossTierRequest(local_ontology_id="l1", domain_ontology_id="d1", min_score=0.7)
            )
            current_config = await get_er_config()
            new_config = await update_er_config(ERConfigUpdate(similarity_threshold=0.9))

        assert run_result["run_id"] == "er1"
        assert status["candidate_count"] == 4
        assert candidates["total_count"] == 1
        assert clusters["total_count"] == 1
        assert explanation["combined_score"] == 0.95
        assert merged == {"merged": True}
        assert cross_tier["total_count"] == 1
        assert current_config == {"similarity_threshold": 0.8}
        assert new_config == {"similarity_threshold": 0.9}

    @pytest.mark.asyncio
    async def test_er_routes_handle_missing_and_value_errors(self):
        run = SimpleNamespace(config=None)
        with (
            patch("app.api.er.er_svc.get_run_status", side_effect=[None, run, run]),
            patch("app.api.er.er_svc.execute_merge", side_effect=ValueError("missing")),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_er_run_status("missing")
            empty_candidates = await list_candidates("er1")
            empty_clusters = await list_clusters("er1")
            with pytest.raises(HTTPException) as merge_exc:
                await execute_merge(ERMergeRequest(source_key="a", target_key="b"))

        assert exc.value.status_code == 404
        assert empty_candidates == {"data": [], "total_count": 0}
        assert empty_clusters == {"data": [], "total_count": 0}
        assert merge_exc.value.status_code == 404


class TestAuthRouteHelpers:
    def test_user_from_claims_and_error_response(self):
        user = user_from_claims(
            {
                "sub": "u1",
                "org_id": "o1",
                "roles": ["admin"],
                "email": "u@example.com",
                "name": "User",
            }
        )
        response = _error_response(401, "UNAUTHORIZED", "bad token")
        assert user.user_id == "u1"
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticate_websocket_valid_invalid_and_dev_mode(self):
        valid_ws = SimpleNamespace(query_params={"token": "good"})
        invalid_ws = SimpleNamespace(query_params={"token": "bad"})
        no_token_ws = SimpleNamespace(query_params={})

        with (
            patch(
                "app.api.auth.decode_jwt",
                return_value={"sub": "u1", "org_id": "o1", "roles": []},
            ),
            patch("app.api.auth.settings") as mock_settings,
        ):
            mock_settings.is_production = False
            user = await authenticate_websocket(valid_ws)
            dev_user = await authenticate_websocket(no_token_ws)

        with patch("app.api.auth.decode_jwt", side_effect=jwt.InvalidTokenError("bad")):
            invalid = await authenticate_websocket(invalid_ws)

        assert user is not None and user.user_id == "u1"
        assert dev_user == _MOCK_USER
        assert invalid is None

    @pytest.mark.asyncio
    async def test_login_returns_validation_error_or_token(self):
        invalid = await login(LoginRequest(email=" ", password=" "))
        valid = await login(LoginRequest(email="user@example.com", password="secret"))
        assert invalid.status_code == 422
        assert isinstance(valid, LoginResponse)
