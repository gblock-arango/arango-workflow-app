# extraction/ — LLM Extraction Pipeline

LangGraph-orchestrated agentic pipeline for ontology extraction from documents.

## What This Is
The LLM-powered extraction engine: prompt construction, multi-pass extraction, self-correction, consistency checking, and pre-curation filtering. Orchestrated as a LangGraph StateGraph.

## What This Will Contain
- `pipeline.py`: LangGraph StateGraph definition with agent nodes and conditional edges
- `state.py`: `ExtractionPipelineState` TypedDict (LangGraph state schema)
- `agents/strategy.py`: Strategy Selector agent — picks model, prompt, chunking strategy
- `agents/extractor.py`: Extraction Agent — N-pass LLM extraction with Pydantic validation and self-correction
- `agents/consistency.py`: Consistency Checker — cross-pass agreement filtering
- `agents/er_agent.py`: Entity Resolution Agent — wraps `arango-entity-resolution` for cross-tier matching
- `agents/filter.py`: Pre-Curation Filter — removes noise, annotates confidence tiers
- `prompts/`: Prompt templates per document type and extraction tier

## What This Is NOT
- Not the API layer — extraction is triggered via `services/`, not called from routes
- Not the database layer — extraction results are persisted by services, not by agents
- Not entity resolution itself — the ER agent delegates to `arango-entity-resolution` via `services/er.py`

## Boundaries
- LLM provider calls (LangChain) are only made in this package
- Agents read from and write to the LangGraph state object — never to the database directly
- The final pipeline output is a structured `ExtractionResult` that `services/` persists
- Prompt templates are stored as separate files, not hardcoded in agent code

## Key Invariants
- All LLM outputs must validate against Pydantic models (`ExtractedClass`, `ExtractionResult`)
- Failed validation triggers self-correction retry (up to 3 attempts) with the error message fed back
- Multi-pass results are only merged by the Consistency Checker — never by individual agents
- Pipeline state is checkpointed via LangGraph persistence — must be resumable after failure
- Every agent step emits structured logs with `run_id`, step name, duration, and token usage

## PRD Reference
- Agentic pipeline architecture: PRD Section 6.11
- LangGraph state schema: PRD Section 6.11 (ExtractionPipelineState)
- Extraction requirements: PRD Section 6.2 (Tier 1), 6.3 (Tier 2)
- Agent descriptions: PRD Section 6.11 (Agents table)
