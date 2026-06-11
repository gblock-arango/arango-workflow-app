"""Extract partial run metrics from LangGraph node outputs for live UI polls."""

from __future__ import annotations

from typing import Any


def _step_log_dict(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        return entry
    if hasattr(entry, "model_dump"):
        return entry.model_dump()
    return {}


def live_metrics_from_node(node_name: str, node_output: dict[str, Any] | None) -> dict[str, Any]:
    """Return a stats patch for the progress cache after a pipeline node completes."""
    if not isinstance(node_output, dict):
        return {}

    patch: dict[str, Any] = {}

    if node_name == "prepare_arango":
        prep = node_output.get("prepare_arango_result")
        if isinstance(prep, dict) and prep.get("chunk_count") is not None:
            patch["prepare_chunk_count"] = prep["chunk_count"]

    if node_name == "consistency_checker":
        consistency = node_output.get("consistency_result")
        classes = getattr(consistency, "classes", None) if consistency is not None else None
        if classes is not None:
            from app.services.extraction import _count_class_properties

            patch["classes_extracted"] = len(classes)
            patch["properties_extracted"] = sum(_count_class_properties(c) for c in classes)

        for entry in node_output.get("step_logs") or []:
            metadata = _step_log_dict(entry).get("metadata") or {}
            rates = metadata.get("agreement_rates") or {}
            if isinstance(rates, dict) and rates:
                patch["pass_agreement_rate"] = sum(rates.values()) / len(rates)
                break

    elif node_name == "er_agent":
        merge_candidates = node_output.get("merge_candidates")
        if isinstance(merge_candidates, list):
            patch["merge_candidates_found"] = len(merge_candidates)
        for entry in node_output.get("step_logs") or []:
            metadata = _step_log_dict(entry).get("metadata") or {}
            found = metadata.get("merge_candidates_found")
            if found is not None:
                patch["merge_candidates_found"] = int(found)
                break

    elif node_name == "belief_revision":
        summary = node_output.get("belief_revision_summary")
        if isinstance(summary, dict):
            patch["belief_revision"] = summary

    elif node_name == "finalize_graph":
        result = node_output.get("finalize_graph_result") if isinstance(node_output, dict) else None
        if isinstance(result, dict):
            patch["classes_written"] = result.get("classes_written")
            if result.get("ontology_id"):
                patch["ontology_id"] = result["ontology_id"]

    return patch
