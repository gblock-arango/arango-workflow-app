"""Extraction Agent — N-pass LLM extraction with Pydantic validation and self-correction.

Batches within each pass and all passes run concurrently, capped by a semaphore.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.extraction.prompts import get_template
from app.extraction.state import ExtractionPipelineState, StepLog, TokenUsage
from app.models.ontology import ExtractionResult

log = logging.getLogger(__name__)

_MAX_RETRIES_PER_BATCH = 5


def _get_llm(model_name: str) -> Any:
    """Instantiate the LLM based on model name.

    Both providers receive ``timeout=settings.llm_request_timeout_seconds``
    so a hung provider connection raises after the configured ceiling
    instead of pinning an asyncio task forever. See
    ``Settings.llm_request_timeout_seconds`` for the rationale and
    incident history.

    On Databricks (``AUTOGRAPH_LLM_PROVIDER=databricks_serving`` or ``auto`` with
    ``AUTOGRAPH_LLM_MODEL_NAME``), uses workspace OAuth and ``/serving-endpoints``.
    """
    from app.llm.databricks_serving import (
        effective_extraction_model_name,
        uses_databricks_serving_for_extraction,
        workspace_openai_client,
    )

    timeout = settings.llm_request_timeout_seconds
    if uses_databricks_serving_for_extraction():
        from app.llm.chat_databricks_serving import DatabricksServingChatOpenAI

        serving_model = effective_extraction_model_name(model_name)
        client = workspace_openai_client()
        return DatabricksServingChatOpenAI(
            model=serving_model,
            api_key=client.api_key,
            base_url=str(client.base_url),
            max_tokens=4096,
            timeout=timeout,
        )

    resolved = model_name
    if "claude" in resolved.lower() or "anthropic" in resolved.lower():
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=resolved,  # type: ignore[call-arg]
            api_key=settings.anthropic_api_key,  # type: ignore[arg-type]
            max_tokens=4096,
            timeout=timeout,
        )
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": resolved,
        "api_key": settings.openai_api_key,
        "max_tokens": 4096,
        "timeout": timeout,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return ChatOpenAI(**kwargs)


def _format_chunk_batch_text(chunks: list[dict[str, Any]], start_index: int = 0) -> str:
    """Render one chunk group as prompt text with stable chunk ids."""
    text_parts = []
    for offset, chunk in enumerate(chunks):
        j = start_index + offset + 1
        chunk_id = chunk.get("_key") or chunk.get("id") or chunk.get("chunk_id") or str(j)
        text_parts.append(f"[Chunk {j} | source_chunk_id={chunk_id}]\n{chunk.get('text', '')}")
    return "\n\n".join(text_parts)


def _batch_chunks(chunks: list[dict[str, Any]], batch_size: int) -> list[str]:
    """Combine chunks into batched text blocks for prompt injection."""
    batches: list[str] = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        batches.append(_format_chunk_batch_text(batch, start_index=i))
    return batches


def _batch_chunk_groups(
    chunks: list[dict[str, Any]],
    batch_size: int,
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Return (batch_text, batch_chunks) pairs for extraction + in-memory RAG."""
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        groups.append((_format_chunk_batch_text(batch, start_index=i), batch))
    return groups


def _parse_llm_response(raw_text: str, pass_number: int, model_name: str) -> ExtractionResult:
    """Parse LLM response text into ExtractionResult.

    Strips markdown fences and validates against Pydantic.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_fence = text.rfind("```")
        text = text[first_newline + 1 : last_fence].strip()

    data = json.loads(text)

    if "pass_number" not in data:
        data["pass_number"] = pass_number
    if "model" not in data:
        data["model"] = model_name

    for cls in data.get("classes", []):
        if "properties" not in cls:
            cls["properties"] = []
        if "attributes" not in cls:
            cls["attributes"] = []
        if "relationships" not in cls:
            cls["relationships"] = []
        if "evidence" not in cls:
            cls["evidence"] = []
        if "parent_evidence" not in cls:
            cls["parent_evidence"] = []
        if "confidence" in cls:
            cls["confidence"] = max(0.0, min(1.0, float(cls["confidence"])))
        for prop in cls.get("properties", []):
            if "confidence" not in prop:
                prop["confidence"] = 0.5
            else:
                prop["confidence"] = max(0.0, min(1.0, float(prop["confidence"])))
            if "evidence" not in prop:
                prop["evidence"] = []
        for attr in cls.get("attributes", []):
            if "confidence" not in attr:
                attr["confidence"] = 0.5
            else:
                attr["confidence"] = max(0.0, min(1.0, float(attr["confidence"])))
            if "evidence" not in attr:
                attr["evidence"] = []
        for rel in cls.get("relationships", []):
            if "confidence" not in rel:
                rel["confidence"] = 0.5
            else:
                rel["confidence"] = max(0.0, min(1.0, float(rel["confidence"])))
            if "evidence" not in rel:
                rel["evidence"] = []

    return ExtractionResult.model_validate(data)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a**0.5) * (norm_b**0.5))


def _mean_embedding(chunks: list[dict[str, Any]]) -> list[float] | None:
    embeddings = [c["embedding"] for c in chunks if isinstance(c.get("embedding"), list)]
    if not embeddings:
        return None
    dim = len(embeddings[0])
    if dim == 0 or any(len(emb) != dim for emb in embeddings):
        return None
    totals = [0.0] * dim
    for emb in embeddings:
        for idx, value in enumerate(emb):
            totals[idx] += float(value)
    count = float(len(embeddings))
    return [value / count for value in totals]


def _retrieve_relevant_chunks(
    all_chunks: list[dict[str, Any]],
    batch_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """In-memory RAG: cosine similarity over UC-loaded embeddings (no Arango)."""
    if not settings.extraction_rag_enabled:
        return batch_chunks

    query_embedding = _mean_embedding(batch_chunks)
    if query_embedding is None:
        return batch_chunks

    min_similarity = settings.extraction_rag_min_similarity
    top_k = settings.extraction_rag_top_k
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in all_chunks:
        embedding = chunk.get("embedding")
        if not isinstance(embedding, list) or len(embedding) != len(query_embedding):
            continue
        similarity = _cosine_similarity(query_embedding, embedding)
        if similarity >= min_similarity:
            scored.append((similarity, chunk))

    if not scored:
        return batch_chunks

    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


async def _extract_batch(
    llm: Any,
    template: Any,
    batch_idx: int,
    batch_text: str,
    pass_num: int,
    model_name: str,
    domain_context: str,
    all_chunks: list[dict[str, Any]],
    batch_chunks: list[dict[str, Any]],
    run_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[list[Any], list[str], dict[str, int]]:
    """Extract ontology classes from a single batch. Returns (classes, errors, token_counts)."""
    async with semaphore:
        relevant_chunks = _retrieve_relevant_chunks(all_chunks, batch_chunks)
        if relevant_chunks and relevant_chunks is not batch_chunks:
            rag_text = "\n\n".join(c.get("text", "") for c in relevant_chunks[:5])
            batch_text = f"{batch_text}\n\n--- RELATED CONTEXT ---\n{rag_text}"

        extra_vars = {"pass_number": pass_num, "model_name": model_name}
        system_msg, user_msg = template.render(
            chunks_text=batch_text,
            domain_context=domain_context,
            extra_vars=extra_vars,
        )

        tokens = {"prompt_tokens": 0, "completion_tokens": 0}
        last_error: str | None = None
        result: ExtractionResult | None = None
        errors: list[str] = []

        for retry in range(_MAX_RETRIES_PER_BATCH):
            try:
                messages = [SystemMessage(content=system_msg), HumanMessage(content=user_msg)]
                if last_error and "Expecting value" not in last_error:
                    messages.append(
                        HumanMessage(
                            content=(
                                f"Your previous response failed validation: {last_error}\n"
                                "Please fix the JSON and try again."
                            )
                        )
                    )

                response = await llm.ainvoke(messages)
                raw_text = (
                    response.content if isinstance(response.content, str) else str(response.content)
                )

                if not raw_text or not raw_text.strip():
                    raise ValueError("LLM returned empty response")

                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    usage = response.usage_metadata
                    tokens["prompt_tokens"] += usage.get("input_tokens", 0)
                    tokens["completion_tokens"] += usage.get("output_tokens", 0)

                result = _parse_llm_response(raw_text, pass_num, model_name)
                break

            except Exception as exc:
                last_error = str(exc)
                log.warning(
                    "extractor parse error, retrying",
                    extra={
                        "run_id": run_id,
                        "pass": pass_num,
                        "batch": batch_idx,
                        "retry": retry + 1,
                        "error": last_error,
                    },
                )
                if "empty response" in last_error.lower() or "Expecting value" in last_error:
                    await asyncio.sleep(2 * (retry + 1))
                if retry == _MAX_RETRIES_PER_BATCH - 1:
                    errors.append(
                        f"Pass {pass_num} batch {batch_idx}: "
                        f"failed after {_MAX_RETRIES_PER_BATCH} retries: {last_error}"
                    )

        classes = list(result.classes) if result else []
        return classes, errors, tokens


async def _run_single_pass(
    pass_num: int,
    llm: Any,
    template: Any,
    batch_groups: list[tuple[str, list[dict[str, Any]]]],
    model_name: str,
    domain_context: str,
    all_chunks: list[dict[str, Any]],
    run_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[ExtractionResult, list[str], dict[str, int]]:
    """Run one extraction pass with all batches concurrent."""
    log.info("extractor pass %d started (%d batches)", pass_num, len(batch_groups))

    tasks = [
        _extract_batch(
            llm=llm,
            template=template,
            batch_idx=idx,
            batch_text=batch_text,
            pass_num=pass_num,
            model_name=model_name,
            domain_context=domain_context,
            all_chunks=all_chunks,
            batch_chunks=batch_chunks,
            run_id=run_id,
            semaphore=semaphore,
        )
        for idx, (batch_text, batch_chunks) in enumerate(batch_groups)
    ]

    results = await asyncio.gather(*tasks)

    all_classes = []
    all_errors = []
    pass_tokens = {"prompt_tokens": 0, "completion_tokens": 0}

    for classes, errors, tokens in results:
        all_classes.extend(classes)
        all_errors.extend(errors)
        pass_tokens["prompt_tokens"] += tokens["prompt_tokens"]
        pass_tokens["completion_tokens"] += tokens["completion_tokens"]

    pass_result = ExtractionResult(
        classes=all_classes,
        pass_number=pass_num,
        model=model_name,
        token_usage=(pass_tokens["prompt_tokens"] + pass_tokens["completion_tokens"]) or None,
    )

    log.info(
        "extractor pass %d completed: %d classes, %d errors",
        pass_num,
        len(all_classes),
        len(all_errors),
    )

    return pass_result, all_errors, pass_tokens


async def extractor_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """LangGraph node: run N-pass extraction concurrently with self-correction."""
    start = time.time()
    run_id = state.get("run_id", "unknown")
    document_id = state.get("document_id", "")
    chunks = state.get("document_chunks", [])
    config = state.get("strategy_config", {})
    errors = list(state.get("errors", []))

    model_name = config.get("model_name", settings.llm_extraction_model)
    template_key = config.get("prompt_template_key", "tier1_standard")
    batch_size = config.get("chunk_batch_size", 5)
    num_passes = config.get("num_passes", settings.extraction_passes)
    domain_context = state.get("domain_context", "")

    log.info(
        "extractor started",
        extra={
            "run_id": run_id,
            "model": model_name,
            "num_passes": num_passes,
            "chunk_count": len(chunks),
            "batch_size": batch_size,
        },
    )

    llm = _get_llm(model_name)
    template = get_template(template_key)
    total_tokens = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    batch_groups = _batch_chunk_groups(chunks, batch_size)
    semaphore = asyncio.Semaphore(settings.llm_extraction_max_concurrency)

    # Run all passes concurrently — each pass runs its batches concurrently too
    pass_tasks = [
        _run_single_pass(
            pass_num=p,
            llm=llm,
            template=template,
            batch_groups=batch_groups,
            model_name=model_name,
            domain_context=domain_context,
            all_chunks=chunks,
            run_id=run_id,
            semaphore=semaphore,
        )
        for p in range(1, num_passes + 1)
    ]

    pass_outputs = await asyncio.gather(*pass_tasks)

    pass_results: list[ExtractionResult] = []
    for pass_result, pass_errors, pass_tokens in pass_outputs:
        pass_results.append(pass_result)
        errors.extend(pass_errors)
        total_tokens["prompt_tokens"] = (
            total_tokens.get("prompt_tokens", 0) + pass_tokens["prompt_tokens"]
        )
        total_tokens["completion_tokens"] = (
            total_tokens.get("completion_tokens", 0) + pass_tokens["completion_tokens"]
        )

    total_tokens["total_tokens"] = total_tokens.get("prompt_tokens", 0) + total_tokens.get(
        "completion_tokens", 0
    )

    duration = time.time() - start
    step_log = StepLog(
        step="extractor",
        status="completed" if pass_results else "failed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        tokens=total_tokens,
        error=errors[-1] if errors else None,
        metadata={
            "num_passes": len(pass_results),
            "total_classes": sum(len(r.classes) for r in pass_results),
        },
    )

    log.info(
        "extractor completed: %d passes, %d total classes, %.1fs",
        len(pass_results),
        sum(len(r.classes) for r in pass_results),
        duration,
    )

    return {
        "extraction_passes": pass_results,
        "errors": errors,
        "token_usage": total_tokens,
        "step_logs": [step_log],
    }
