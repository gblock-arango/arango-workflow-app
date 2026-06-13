"""Semantic Validator — LLM-based OWL logical consistency checker.

Runs after the consistency checker. For each extracted class, the LLM checks
for domain/range mismatches, disjointness violations, range type mismatches,
and redundant class definitions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.extraction.agents.extractor import _get_llm
from app.llm.databricks_serving import effective_extraction_model_name
from app.models.ontology import ExtractedClass

log = logging.getLogger(__name__)

_DEFAULT_SCORE = 0.8


def _class_fields_for_validation(c: ExtractedClass) -> dict[str, list[dict[str, str]]]:
    """Normalize PGT attributes/relationships (or legacy properties) for the LLM."""
    attributes: list[dict[str, str]] = []
    relationships: list[dict[str, str]] = []

    if c.attributes or c.relationships:
        for a in c.attributes:
            attributes.append(
                {
                    "uri": a.uri,
                    "label": a.label,
                    "range_datatype": a.range_datatype,
                }
            )
        for r in c.relationships:
            relationships.append(
                {
                    "uri": r.uri,
                    "label": r.label,
                    "target_class_uri": r.target_class_uri,
                }
            )
        return {"attributes": attributes, "relationships": relationships}

    for p in c.properties:
        if p.property_type == "object":
            relationships.append(
                {
                    "uri": p.uri,
                    "label": p.label,
                    "target_class_uri": p.range,
                }
            )
        else:
            attributes.append(
                {
                    "uri": p.uri,
                    "label": p.label,
                    "range_datatype": p.range,
                }
            )
    return {"attributes": attributes, "relationships": relationships}


def _parse_response(raw_text: str, class_uris: set[str]) -> dict[str, float]:
    """Parse the LLM response into {uri: score}, falling back to defaults on error."""
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_fence = text.rfind("```")
        text = text[first_newline + 1 : last_fence].strip()

    data = json.loads(text)
    results: list[dict[str, Any]] = data.get("results", [])

    scores: dict[str, float] = {}
    for entry in results:
        uri = entry.get("uri", "")
        score = entry.get("score", _DEFAULT_SCORE)
        if uri:
            scores[uri] = max(0.0, min(1.0, float(score)))

    for uri in class_uris:
        if uri not in scores:
            scores[uri] = _DEFAULT_SCORE

    return scores


async def validate_semantics(
    classes: list[ExtractedClass],
    model_name: str | None = None,
    *,
    run_id: str | None = None,
) -> dict[str, float]:
    """Return {class_uri: validity_score} for each class.

    Sends all classes in a single LLM call to minimize cost.
    Returns default scores of 0.8 for all classes if the call fails.
    """
    if not classes:
        return {}

    class_uris = {c.uri for c in classes}
    resolved_model = model_name or effective_extraction_model_name()

    try:
        llm = _get_llm(resolved_model)
        from app.extraction.prompts import render_prompt

        class_list = []
        for c in classes:
            shapes = _class_fields_for_validation(c)
            class_list.append(
                {
                    "uri": c.uri,
                    "label": c.label,
                    "description": c.description,
                    "parent_uri": c.parent_uri,
                    "attributes": shapes["attributes"],
                    "relationships": shapes["relationships"],
                }
            )
        system_prompt, user_prompt = render_prompt(
            "judge_semantic_validator",
            extra_vars={"class_json": json.dumps(class_list, indent=2)},
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await llm.ainvoke(messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        if run_id:
            from app.services.run_agent_diagnostics import record_llm_call, usage_from_response

            pt, ct = usage_from_response(response)
            prompt_chars = len(system_prompt) + len(user_prompt)
            await asyncio.to_thread(
                record_llm_call,
                run_id,
                prompt_tokens=pt,
                completion_tokens=ct,
                prompt_chars=prompt_chars,
                step="quality_judge_semantic",
            )

        scores = _parse_response(raw_text, class_uris)
        log.info(
            "semantic validator completed",
            extra={"class_count": len(classes), "scores": scores},
        )
        return scores

    except Exception:
        log.warning(
            "semantic validator failed, returning default scores",
            exc_info=True,
        )
        return {uri: _DEFAULT_SCORE for uri in class_uris}
