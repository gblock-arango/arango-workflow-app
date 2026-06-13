"""Qualitative evaluation map-phase prompt (single user message)."""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = ""

_USER = """\
You are an ontology extraction quality reviewer. Below is a batch of \
source text chunks followed by the ontology classes that were extracted \
from them.

Compare the extracted classes against the actual source text and produce \
**evidence-grounded** observations about extraction quality.

Consider:
- Are the extracted classes actually present in or supported by the text?
- Were important concepts in the text missed by the extraction?
- Are class descriptions accurate reflections of what the text says?
- Are there hallucinated classes with no textual support?
- Are properties and relationships grounded in the source?

## Source Text (Batch {batch_number})
{batch_text}

## Extracted Classes ({class_count} classes)
{class_json}

Return ONLY valid JSON with this schema:
{{"observations": ["observation 1", ...]}}

Each observation should be 1-2 sentences, referencing specific class names \
and quoting or paraphrasing the source text where relevant. \
Aim for 3-6 observations per batch."""

register_template(
    PromptTemplate(
        key="judge_qualitative_map",
        system_prompt=_SYSTEM,
        user_prompt=_USER,
        description="Qualitative eval — per-batch map observations",
    )
)
