"""Live metrics extraction from LangGraph node outputs."""

from __future__ import annotations

from app.extraction.live_metrics import live_metrics_from_node
from app.models.ontology import ExtractedClass


def test_consistency_checker_emits_entity_counts() -> None:
    classes = [
        ExtractedClass(
            uri="http://ex/C1",
            label="C1",
            description="d",
            confidence=0.9,
            properties=[],
            attributes=[{"uri": "http://ex/a1", "label": "a1"}],
            relationships=[],
        ),
    ]
    from app.models.ontology import ExtractionResult

    result = ExtractionResult(classes=classes, pass_number=1, model="test")
    patch = live_metrics_from_node(
        "consistency_checker",
        {
            "consistency_result": result,
            "step_logs": [
                {
                    "step": "consistency_checker",
                    "metadata": {"agreement_rates": {"http://ex/C1": 1.0}},
                }
            ],
        },
    )
    assert patch["classes_extracted"] == 1
    assert patch["properties_extracted"] == 1
    assert patch["pass_agreement_rate"] == 1.0


def test_er_agent_emits_merge_candidates() -> None:
    patch = live_metrics_from_node(
        "er_agent",
        {
            "merge_candidates": [{"a": 1}, {"b": 2}],
            "step_logs": [{"metadata": {"merge_candidates_found": 2}}],
        },
    )
    assert patch["merge_candidates_found"] == 2
