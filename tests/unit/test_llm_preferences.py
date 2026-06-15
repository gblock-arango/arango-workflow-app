"""Unit tests for persisted LLM preferences."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services import llm_preferences


@pytest.fixture(autouse=True)
def _clear_endpoint_cache():
    from app.llm import databricks_serving

    databricks_serving._resolved_endpoint_cached.cache_clear()
    llm_preferences._last_applied_signature = None
    yield
    databricks_serving._resolved_endpoint_cached.cache_clear()
    llm_preferences._last_applied_signature = None


def test_default_models_for_provider():
    databricks = llm_preferences.default_models_for_provider("databricks")
    assert databricks["extraction_model"] == "databricks-meta-llama-3-3-70b-instruct"
    assert databricks["embedding_model"] == "databricks-bge-large-en"
    assert databricks["embedding_dimension"] == 1024

    openai = llm_preferences.default_models_for_provider("openai")
    assert openai["extraction_model"] == "gpt-4o-mini"
    assert openai["embedding_model"] == "text-embedding-3-small"
    assert openai["embedding_dimension"] == 1536


def test_apply_llm_preferences_updates_settings():
    llm_preferences.apply_llm_preferences(
        {
            "provider": "databricks",
            "extraction_model": "databricks-meta-llama-3-3-70b-instruct",
            "embedding_model": "databricks-bge-large-en",
            "embedding_dimension": 1024,
            "openai_api_key": "sk-test",
        }
    )
    assert llm_preferences.settings.autograph_llm_provider == "databricks_serving"
    assert (
        llm_preferences.settings.autograph_llm_model_name
        == "databricks-meta-llama-3-3-70b-instruct"
    )
    assert llm_preferences.settings.autograph_embedding_model_name == "databricks-bge-large-en"
    assert llm_preferences.settings.autograph_embedding_dimension == 1024
    assert llm_preferences.settings.openai_api_key == "sk-test"


def test_sync_llm_preferences_from_volume_applies_when_file_changes():
    saved = {
        "version": 1,
        "provider": "openai",
        "extraction_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimension": 1536,
        "openai_api_key": "sk-synced",
    }
    with (
        patch.object(llm_preferences.settings, "autograph_llm_provider", "databricks_serving"),
        patch.object(
            llm_preferences.settings,
            "autograph_llm_model_name",
            "databricks-meta-llama-3-3-70b-instruct",
        ),
        patch(
            "app.workflow_platform.workflow_data_volume.read_bytes",
            return_value=json.dumps(saved).encode("utf-8"),
        ),
    ):
        assert llm_preferences.sync_llm_preferences_from_volume() is True
        assert llm_preferences.settings.autograph_llm_provider == "openai"
        assert llm_preferences.settings.openai_api_key == "sk-synced"
        assert llm_preferences.sync_llm_preferences_from_volume() is False


def test_save_llm_preferences_persists_and_applies(tmp_path):
    written: dict[str, bytes] = {}

    def fake_write_bytes(*, relative_path: str, content: bytes) -> None:
        written[relative_path] = content

    with (
        patch("app.workflow_platform.workflow_data_volume.read_bytes", side_effect=FileNotFoundError),
        patch("app.workflow_platform.workflow_data_volume.write_bytes", side_effect=fake_write_bytes),
    ):
        result = llm_preferences.save_llm_preferences(
            provider="openai",
            extraction_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            embedding_dimension=1536,
            openai_api_key="sk-saved",
        )

    assert result["ok"] is True
    assert result["provider"] == "openai"
    assert result["embedding_dimension"] == 1536
    assert written[llm_preferences._SETTINGS_REL]
    payload = json.loads(written[llm_preferences._SETTINGS_REL].decode("utf-8"))
    assert payload["openai_api_key"] == "sk-saved"
    assert payload["embedding_dimension"] == 1536
    assert llm_preferences.settings.autograph_llm_provider == "openai"
    assert llm_preferences.settings.autograph_embedding_dimension == 1536
    assert llm_preferences.settings.openai_api_key == "sk-saved"


def test_load_llm_preferences_from_saved_file():
    saved = {
        "version": 1,
        "provider": "openai",
        "extraction_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimension": 1536,
        "openai_api_key": "sk-stored",
    }
    with (
        patch(
            "app.workflow_platform.workflow_data_volume.read_bytes",
            return_value=json.dumps(saved).encode("utf-8"),
        ),
        patch.object(llm_preferences.settings, "autograph_llm_provider", "openai"),
        patch.object(llm_preferences.settings, "autograph_llm_model_name", "gpt-4o-mini"),
        patch.object(
            llm_preferences.settings,
            "autograph_embedding_model_name",
            "text-embedding-3-small",
        ),
        patch.object(llm_preferences.settings, "openai_api_key", "sk-stored"),
    ):
        loaded = llm_preferences.load_llm_preferences()

    assert loaded["provider"] == "openai"
    assert loaded["extraction_model"] == "gpt-4o-mini"
    assert loaded["embedding_model"] == "text-embedding-3-small"
    assert loaded["embedding_dimension"] == 1536
    assert loaded["openai_api_key_configured"] is True


@pytest.mark.asyncio
async def test_llm_settings_route_handlers():
    from app.api.system import get_llm_settings, put_llm_settings
    from app.api.system import LlmSettingsBody

    with patch(
        "app.api.system.load_llm_preferences",
        return_value={"provider": "openai", "extraction_model": "gpt-4o-mini"},
    ):
        payload = await get_llm_settings()
    assert payload["provider"] == "openai"

    with patch(
        "app.api.system.save_llm_preferences",
        return_value={"ok": True, "provider": "databricks"},
    ):
        saved = await put_llm_settings(
            LlmSettingsBody(provider="databricks", extraction_model="databricks-meta-llama-3-3-70b-instruct")
        )
    assert saved["ok"] is True
