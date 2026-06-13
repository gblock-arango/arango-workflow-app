"""Qualitative evaluation reduce-phase prompt (single user message)."""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = ""

_USER = """\
You are an ontology quality evaluator producing a final assessment.

Below are per-batch observations from reviewers who read the actual \
source text and compared it against extracted ontology classes.

Synthesise these observations into a concise qualitative summary. \
Look for **cross-batch patterns** — recurring strengths or weaknesses \
that appear across multiple batches.

## Per-Batch Reviewer Observations ({observation_count} total)
{numbered_observations}

Return ONLY valid JSON with this exact schema:
{{"strengths": ["point 1", ...], "weaknesses": ["point 1", ...]}}

Each point should be a concise markdown-formatted bullet (1-2 sentences). \
Include specific class names where relevant. \
Aim for 4 points per category."""

register_template(
    PromptTemplate(
        key="judge_qualitative_reduce",
        system_prompt=_SYSTEM,
        user_prompt=_USER,
        description="Qualitative eval — reduce strengths/weaknesses summary",
    )
)
