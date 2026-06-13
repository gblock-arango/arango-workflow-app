"""UC entity anchor text injected into extraction domain context."""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = ""

_USER = """\
Unity Catalog entities selected for this workflow (use as domain context for \
entity resolution and alignment with document chunks):

{entities_block}"""

register_template(
    PromptTemplate(
        key="UC_anchor_prompt",
        system_prompt=_SYSTEM,
        user_prompt=_USER,
        description="Unity Catalog table/column anchor block for domain context",
    )
)
