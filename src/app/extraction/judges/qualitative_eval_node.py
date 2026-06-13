"""Qualitative Evaluation Agent — map-reduce LLM-based strengths/weaknesses.

Phase 1 (map): For each chunk batch, the LLM sees the actual source text
alongside the classes extracted from it and produces evidence-grounded
observations (what was captured well, what was missed, what looks hallucinated).

Phase 2 (reduce): A single LLM call synthesises all per-batch observations
into a final strengths/weaknesses summary with cross-batch patterns.

Runs async (fire-and-forget) so it never blocks staging graph creation.
The result is stored in ``extraction_runs.stats.qualitative_evaluation``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage

from app.config import settings
from app.extraction.agents.extractor import _batch_chunks, _get_llm
from app.llm.databricks_serving import effective_extraction_model_name
from app.models.ontology import ExtractedClass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_RESPONSE_SCHEMA = {
    "title": "qualitative_evaluation",
    "type": "object",
    "properties": {
        "strengths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Markdown bullet points describing extraction strengths",
        },
        "weaknesses": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Markdown bullet points describing extraction weaknesses",
        },
    },
    "required": ["strengths", "weaknesses"],
    "additionalProperties": False,
}

_MAP_OBSERVATIONS_SCHEMA = {
    "title": "batch_observations",
    "type": "object",
    "properties": {
        "observations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Evidence-grounded observations about extraction quality for this batch",
        },
    },
    "required": ["observations"],
    "additionalProperties": False,
}


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    """Parse an LLM response, stripping markdown fences if present."""
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_fence = text.rfind("```")
        text = text[first_newline + 1 : last_fence].strip()
    return cast(dict[str, Any], json.loads(text))


async def _invoke_llm_json(
    llm: Any,
    messages: list[Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Invoke the LLM with structured output, falling back to text parsing."""
    try:
        structured = llm.with_structured_output(schema)
        result = await structured.ainvoke(messages)
        if isinstance(result, dict):
            return result
    except (AttributeError, NotImplementedError, TypeError, ValueError):
        pass

    response = await llm.ainvoke(messages)
    raw = response.content if isinstance(response.content, str) else str(response.content)
    return _parse_json_response(raw)


# ---------------------------------------------------------------------------
# Phase 1 — MAP: per-batch observations grounded in source text
# ---------------------------------------------------------------------------


def _classes_for_batch(
    classes: list[ExtractedClass],
    batch_chunk_indices: list[int],
    chunks: list[dict[str, Any]],
) -> list[ExtractedClass]:
    """Return classes whose provenance overlaps with the given batch chunk indices.

    Falls back to returning all classes if provenance info is unavailable.
    """
    batch_chunk_ids = set()
    for idx in batch_chunk_indices:
        if idx < len(chunks):
            chunk = chunks[idx]
            batch_chunk_ids.add(chunk.get("_key", chunk.get("id", str(idx))))

    if not batch_chunk_ids:
        return classes

    matched = []
    for cls in classes:
        source_chunks = getattr(cls, "source_chunks", None) or []
        if source_chunks:
            if any(sc in batch_chunk_ids for sc in source_chunks):
                matched.append(cls)
        else:
            # No provenance — include all classes so the LLM can judge
            return classes
    return matched or classes


async def _map_single_batch(
    llm: Any,
    batch_text: str,
    batch_classes: list[ExtractedClass],
    batch_index: int,
) -> list[str]:
    """Run the map phase for a single chunk batch."""

    def _labels_for_class(cls: ExtractedClass) -> dict[str, list[str]]:
        if cls.attributes or cls.relationships:
            return {
                "attributes": [a.label for a in cls.attributes],
                "relationships": [r.label for r in cls.relationships],
            }
        return {
            "attributes": [p.label for p in cls.properties if p.property_type != "object"],
            "relationships": [p.label for p in cls.properties if p.property_type == "object"],
        }

    class_summaries = [
        {
            "label": cls.label,
            "description": cls.description or "",
            **_labels_for_class(cls),
        }
        for cls in batch_classes
    ]

    from app.extraction.prompts import render_prompt

    _, prompt = render_prompt(
        "judge_qualitative_map",
        extra_vars={
            "batch_number": batch_index + 1,
            "batch_text": batch_text,
            "class_count": len(class_summaries),
            "class_json": json.dumps(class_summaries, indent=2),
        },
    )

    try:
        result = await _invoke_llm_json(
            llm,
            [HumanMessage(content=prompt)],
            _MAP_OBSERVATIONS_SCHEMA,
        )
        observations_raw = result.get("observations", [])
        observations: list[str]
        if isinstance(observations_raw, list):
            observations = [str(x) for x in observations_raw]
        else:
            observations = []
        log.debug(
            "qualitative map batch %d: %d observations",
            batch_index,
            len(observations),
        )
        return observations
    except Exception:
        log.warning("qualitative map batch %d failed", batch_index, exc_info=True)
        return []


async def _map_phase(
    llm: Any,
    classes: list[ExtractedClass],
    chunks: list[dict[str, Any]],
    batch_size: int,
    *,
    max_concurrency: int | None = None,
) -> list[str]:
    """Run map phase across chunk batches with bounded concurrency.

    Without the ``asyncio.Semaphore`` gate, large documents fan out
    dozens of simultaneous OpenAI calls — which trips per-minute rate
    limits, triggers a long retry storm, and saturates the single
    uvicorn worker so unrelated API and WebSocket traffic times out.

    ``max_concurrency`` defaults to
    :data:`app.config.settings.qualitative_eval_max_concurrency`
    (override is exposed mainly for tests). A value of ``0`` or
    negative restores fully-unbounded fan-out (not recommended).
    """
    cap = (
        max_concurrency
        if max_concurrency is not None
        else settings.qualitative_eval_max_concurrency
    )
    batch_texts = _batch_chunks(chunks, batch_size)

    sem: asyncio.Semaphore | None = asyncio.Semaphore(cap) if cap and cap > 0 else None

    async def _bounded(
        batch_text: str,
        batch_classes: list[ExtractedClass],
        batch_idx: int,
    ) -> list[str]:
        if sem is None:
            return await _map_single_batch(llm, batch_text, batch_classes, batch_idx)
        async with sem:
            return await _map_single_batch(llm, batch_text, batch_classes, batch_idx)

    tasks = []
    for batch_idx, batch_text in enumerate(batch_texts):
        start = batch_idx * batch_size
        batch_chunk_indices = list(range(start, min(start + batch_size, len(chunks))))
        batch_classes = _classes_for_batch(classes, batch_chunk_indices, chunks)
        tasks.append(_bounded(batch_text, batch_classes, batch_idx))

    results = await asyncio.gather(*tasks)
    all_observations: list[str] = []
    for obs_list in results:
        all_observations.extend(obs_list)
    return all_observations


# ---------------------------------------------------------------------------
# Phase 2 — REDUCE: synthesise observations into final evaluation
# ---------------------------------------------------------------------------


async def _reduce_phase(
    llm: Any,
    observations: list[str],
) -> dict[str, list[str]]:
    """Synthesise per-batch observations into final strengths/weaknesses."""
    from app.extraction.prompts import render_prompt

    numbered_obs = "\n".join(f"{i + 1}. {obs}" for i, obs in enumerate(observations))
    _, prompt = render_prompt(
        "judge_qualitative_reduce",
        extra_vars={
            "observation_count": len(observations),
            "numbered_observations": numbered_obs,
        },
    )

    result = await _invoke_llm_json(
        llm,
        [HumanMessage(content=prompt)],
        _RESPONSE_SCHEMA,
    )
    return {
        "strengths": result.get("strengths", []),
        "weaknesses": result.get("weaknesses", []),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_qualitative_evaluation(
    classes: list[ExtractedClass],
    chunks: list[dict[str, Any]],
    batch_size: int = 5,
    model_name: str | None = None,
) -> dict[str, list[str]]:
    """Produce a strengths/weaknesses evaluation using map-reduce over source text.

    Parameters
    ----------
    classes:
        The extracted (post-filter) ontology classes.
    chunks:
        The original document chunks (source text).
    batch_size:
        Number of chunks per map-phase batch (reuses extraction batch size).
    model_name:
        LLM model to use. Defaults to configured extraction model.
    """
    if not classes:
        return {"strengths": [], "weaknesses": ["No classes extracted"]}

    resolved_model = model_name or effective_extraction_model_name()
    llm = _get_llm(resolved_model)

    try:
        # Phase 1: map — per-batch observations grounded in source text
        observations = await _map_phase(llm, classes, chunks, batch_size)

        if not observations:
            return {
                "strengths": [],
                "weaknesses": ["Could not generate text-grounded observations"],
            }

        # Phase 2: reduce — synthesise into final evaluation
        result = await _reduce_phase(llm, observations)

        log.info(
            "qualitative evaluation completed (map-reduce)",
            extra={
                "class_count": len(classes),
                "batch_count": len(range(0, len(chunks), batch_size)),
                "observation_count": len(observations),
                "strengths": len(result.get("strengths", [])),
                "weaknesses": len(result.get("weaknesses", [])),
            },
        )
        return result

    except Exception:
        log.warning(
            "qualitative evaluation failed, returning empty result",
            exc_info=True,
        )
        return {
            "strengths": [],
            "weaknesses": ["Qualitative evaluation could not be completed"],
        }
