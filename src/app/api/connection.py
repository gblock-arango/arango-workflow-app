"""Arango connection profile API — named profiles stored on UC workflow-data volume."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from app.api.errors import ValidationError
from app.services import arango_connection_profiles as profiles

router = APIRouter(prefix="/api/v1/connection", tags=["connection"])


class SaveProfileBody(BaseModel):
    display_name: str | None = None
    environment: str | None = None
    username: str = "root"
    password: str | None = None
    server_endpoint: str = ""
    cluster_name: str = ""
    protocol: str = "https"
    port: int | None = None


class CreateProfileBody(BaseModel):
    display_name: str
    environment: str = "aws"
    profile_key: str | None = None


class TestProfileBody(BaseModel):
    username: str | None = None
    password: str | None = None
    server_endpoint: str | None = None
    verify_tls: bool = True
    timeout_seconds: float = Field(default=5.0, ge=1.0, le=60.0)


@router.get("/profiles")
async def get_profiles() -> dict[str, Any]:
    """Load saved connection profiles from the UC workflow-data volume."""
    return await asyncio.to_thread(profiles.load_connection_profiles)


@router.post("/profiles")
async def create_profile(body: CreateProfileBody) -> dict[str, Any]:
    """Create a new named connection profile shell."""
    try:
        return await asyncio.to_thread(
            profiles.create_connection_profile,
            display_name=body.display_name,
            environment=body.environment,
            profile_key=body.profile_key,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.put("/profiles/{profile_key}")
async def put_profile(profile_key: str, body: SaveProfileBody) -> dict[str, Any]:
    """Save one profile (password omitted or placeholder keeps existing secret)."""
    try:
        return await asyncio.to_thread(
            profiles.save_connection_profile,
            profile_key,
            body.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.post("/profiles/{profile_key}/activate")
async def activate_profile(profile_key: str) -> dict[str, Any]:
    """Save active profile, upsert UC registry, and verify gateway → Arango (extraction path)."""
    from app.api.health import invalidate_ready_cache

    try:
        result = await asyncio.to_thread(profiles.upsert_registry_for_profile, profile_key)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        raise ValidationError(f"Failed to activate profile: {exc}") from exc

    invalidate_ready_cache()

    gateway_probe = await asyncio.to_thread(profiles.verify_gateway_arango_ping)
    result["gateway_probe"] = gateway_probe
    if not gateway_probe.get("ok"):
        err = str(gateway_probe.get("error") or "Gateway could not reach Arango")
        raise ValidationError(
            f"Registry updated but gateway path failed: {err}. "
            "Extraction uses the gateway proxy — fix CAN_USE, gateway READ on UC_WORKFLOW_VOLUME_NAME, "
            "or wait a few seconds and Connect again."
        )
    return result


@router.post("/profiles/{profile_key}/test")
async def test_profile(profile_key: str, body: TestProfileBody | None = None) -> dict[str, Any]:
    """Probe Arango using saved or supplied credentials."""
    try:
        payload = body.model_dump(exclude_none=True) if body else None
        return await asyncio.to_thread(profiles.test_profile_connection, profile_key, payload)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.post("/profiles/{profile_key}/kubeconfig")
async def upload_kubeconfig(
    profile_key: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload kubeconfig YAML; stored under workflow-data/settings/kubeconfig/."""
    content = await file.read()
    filename = (file.filename or "").strip() or f"{profile_key}-kubeconfig.yaml"
    try:
        return await asyncio.to_thread(
            profiles.save_kubeconfig,
            profile_key,
            filename=filename,
            content=content,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
