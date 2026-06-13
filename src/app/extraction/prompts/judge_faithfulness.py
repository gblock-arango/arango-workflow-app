"""Faithfulness judge LLM prompts."""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = """\
You are evaluating whether ontology classes extracted from a document \
are faithfully grounded in the source text.

For each class below, rate its faithfulness to the source text:
- EXPLICIT (1.0): The concept is explicitly mentioned in the text
- INFERRED (0.7): The concept is reasonably inferred from the text
- PLAUSIBLE (0.4): A reasonable domain concept but not directly grounded in the text
- HALLUCINATED (0.1): Not supported by the text at all

Return ONLY valid JSON, no markdown fences."""

_USER = """\
Source text:
{chunks_text}

Classes to evaluate:
{class_json}

Return JSON: {{"results": [{{"uri": "...", "rating": "EXPLICIT|INFERRED|PLAUSIBLE|HALLUCINATED", "reason": "brief explanation"}}]}}"""

register_template(
    PromptTemplate(
        key="judge_faithfulness",
        system_prompt=_SYSTEM,
        user_prompt=_USER,
        description="Quality judge — faithfulness grounding check",
    )
)
