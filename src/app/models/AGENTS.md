# models/ — Pydantic Models

Data validation models for API requests/responses and LLM extraction outputs.

## What This Is
Pydantic `BaseModel` subclasses organized by domain:
- `documents.py`: Document upload, chunk, and status models
- `ontology.py`: Ontology classes, properties, extraction results, and LLM output schemas
- `curation.py`: Curation decisions, merge candidates

## What This Will Contain
- `temporal.py`: Temporal versioning models (snapshot, diff, timeline event responses)
- `er.py`: Entity resolution pipeline config, candidate pair, cluster models
- `common.py`: Shared pagination envelope, error response schema

## What This Is NOT
- Not database schemas — these are API/serialization contracts, not collection definitions
- Not service logic — models validate and serialize, never query or mutate

## Boundaries
- Models must not import from `db/`, `services/`, or `api/`
- LLM extraction output models (e.g., `ExtractedClass`, `ExtractionResult`) define the JSON schema that LLM structured outputs must conform to
- Response models use `Field(alias="_key")` for ArangoDB document keys
- All enums use `StrEnum` for JSON serialization

## Key Invariants
- Every API endpoint must use a Pydantic model for request body validation
- LLM output models must be strict enough to catch malformed extractions but flexible enough to allow self-correction retries
- `confidence` fields are always `float` constrained to `[0.0, 1.0]`
- Temporal fields (`created`, `expired`, `version`) must use consistent types across all models

## PRD Reference
- Ontology data model: PRD Section 5.1 (collection field definitions)
- Temporal versioning fields: PRD Section 5.3
- LLM extraction schema: PRD Section 6.2 (FR-2.1)
- API response format: PRD Section 7.8
