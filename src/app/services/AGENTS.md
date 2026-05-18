# services/ — Business Logic Layer

Domain services that implement the core AOE workflows.

## What This Is
The middle layer between API routes and database/external calls. Each service encapsulates a complete business capability.

## What This Will Contain
- `ingestion.py`: Document parsing (PDF/DOCX/Markdown), semantic chunking, vector embedding
- `ontology.py`: Ontology CRUD with temporal versioning, staging/promotion, import/export via ArangoRDF
- `curation.py`: Decision recording, batch operations, provenance tracking
- `temporal.py`: Point-in-time snapshots, version history, temporal diffs, revert
- `er.py`: Entity resolution pipeline configuration and execution via `arango-entity-resolution`
- `schema_extraction.py`: Schema extraction from external ArangoDB via `arango-schema-mapper`
- `notification.py`: Event emission to WebSocket and notification queue

## What This Is NOT
- Not API routing logic (that's `api/`)
- Not raw database queries (those go in `db/` repositories)
- Not LLM prompt engineering (that's `extraction/`)

## Boundaries
- Services call `db/` repositories for all database access
- Services call `extraction/` for LLM operations
- Services are called by `api/` routes — never imported by `db/` or `models/`
- Services may call other services (e.g., `curation` calls `temporal` for versioning)
- External library calls (`arango-entity-resolution`, `arango-schema-mapper`, `ArangoRDF`) are wrapped here, not scattered across the codebase

## Key Invariants
- Every ontology mutation must go through temporal versioning (expire + insert + edge re-creation)
- All tenant-scoped operations must filter by `org_id`
- Service functions are stateless — all state lives in the database or is passed as arguments
- Errors are raised as typed exceptions, not returned as dicts

## PRD Reference
- Feature logic: PRD Section 6 (all subsections)
- Temporal versioning rules: PRD Section 5.3
- Entity resolution integration: PRD Section 6.7, 9.4
- Schema extraction: PRD Section 6.9, 9.1
