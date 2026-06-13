"""Unit tests for extraction prompt templates and debug capture."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.extraction.prompts import get_builtin_template, get_template
from app.services import extraction_prompt_debug, extraction_prompt_templates


def test_list_templates_catalog_includes_builtins():
    catalog = extraction_prompt_templates.list_templates_catalog()
    keys = {item["key"] for item in catalog}
    assert "tier1_standard" in keys
    assert "tier1_technical" in keys
    assert "tier2_standard" in keys
    assert "UC_anchor_prompt" in keys
    assert "judge_faithfulness" in keys
    assert "judge_semantic_validator" in keys
    assert "judge_qualitative_map" in keys
    assert "judge_qualitative_reduce" in keys
    assert "belief_revision" in keys


def test_save_template_override_persists_to_uc_volume():
    written: dict[str, bytes] = {}

    def fake_write_bytes(*, relative_path: str, content: bytes) -> None:
        written[relative_path] = content

    with (
        patch("app.workflow_platform.workflow_data_volume.read_bytes", side_effect=FileNotFoundError),
        patch("app.workflow_platform.workflow_data_volume.write_bytes", side_effect=fake_write_bytes),
    ):
        saved = extraction_prompt_templates.save_template_override(
            "tier1_standard",
            system_prompt="SYSTEM override",
            user_prompt="USER override",
        )

    assert saved["key"] == "tier1_standard"
    assert saved["source"] == "override"
    assert written[extraction_prompt_templates._OVERRIDES_REL]
    payload = json.loads(written[extraction_prompt_templates._OVERRIDES_REL].decode("utf-8"))
    assert payload["templates"]["tier1_standard"]["system_prompt"] == "SYSTEM override"


def test_get_template_applies_uc_override():
    saved = {
        "version": 1,
        "templates": {
            "tier1_standard": {
                "system_prompt": "OVERRIDE SYSTEM {chunks_text}",
                "user_prompt": "OVERRIDE USER {chunks_text}",
            }
        },
    }
    with patch(
        "app.services.extraction_prompt_templates._read_overrides_file",
        return_value=saved,
    ):
        template = get_template("tier1_standard")
    system, user = template.render(chunks_text="chunk body")
    assert "OVERRIDE SYSTEM chunk body" in system
    assert "OVERRIDE USER chunk body" in user
    builtin = get_builtin_template("tier1_standard")
    assert builtin.system_prompt != template.system_prompt


def test_record_and_load_last_extractor_llm_call():
    written: dict[str, bytes] = {}

    def fake_write_bytes(*, relative_path: str, content: bytes) -> None:
        written[relative_path] = content

    extraction_prompt_debug._last_call_memory = None
    with patch(
        "app.workflow_platform.workflow_data_volume.write_bytes",
        side_effect=fake_write_bytes,
    ):
        extraction_prompt_debug.record_extractor_llm_call(
            run_id="run-1",
            template_key="tier1_standard",
            system_prompt="SYS",
            user_prompt="USER",
            response_text='{"classes":[]}',
            pass_num=1,
            batch_idx=0,
            model_name="gpt-4o-mini",
        )

    loaded = extraction_prompt_debug.load_last_extractor_llm_call(run_id="run-1")
    assert loaded is not None
    assert loaded["actual_prompt"].startswith("=== SYSTEM ===")
    assert loaded["response_text"] == '{"classes":[]}'
    assert written[extraction_prompt_debug._LAST_CALL_REL]


@pytest.mark.asyncio
async def test_extraction_prompts_api_handlers():
    from app.api.extraction_prompts import (
        SaveTemplateBody,
        get_extraction_prompt_template,
        get_last_extraction_prompt,
        list_extraction_prompt_templates,
        put_extraction_prompt_template,
    )

    with patch(
        "app.api.extraction_prompts.list_templates_catalog",
        return_value=[{"key": "tier1_standard", "description": "x"}],
    ):
        payload = await list_extraction_prompt_templates()
    assert payload["count"] == 1

    with patch(
        "app.api.extraction_prompts.get_template_catalog_entry",
        return_value={"key": "tier1_standard", "system_prompt": "s", "user_prompt": "u"},
    ):
        one = await get_extraction_prompt_template("tier1_standard")
    assert one["key"] == "tier1_standard"

    with patch(
        "app.api.extraction_prompts.save_template_override",
        return_value={"key": "tier1_standard", "system_prompt": "s", "user_prompt": "u"},
    ):
        saved = await put_extraction_prompt_template(
            "tier1_standard",
            SaveTemplateBody(system_prompt="s", user_prompt="u"),
        )
    assert saved["ok"] is True

    with patch(
        "app.api.extraction_prompts.load_last_extractor_llm_call",
        return_value={"run_id": "run-1", "actual_prompt": "ACT", "response_text": "RES"},
    ):
        last = await get_last_extraction_prompt(run_id="run-1")
    assert last["found"] is True
    assert last["actual_prompt"] == "ACT"
