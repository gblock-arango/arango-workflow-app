# db/ — ArangoDB Client & Schema

Database connection management, schema definitions, and query layer.

## What This Is
- `client.py`: ArangoDB client singleton with deployment-mode-aware connection (local/cluster/AMP), auto-database creation, and lifecycle management
- `schema.py`: Collection, edge, graph, and index definitions; idempotent `init_schema()` for bootstrapping

## What This Will Contain
- Repository modules (one per domain): `documents_repo.py`, `ontology_repo.py`, `curation_repo.py`, `temporal_repo.py`
- All AQL queries encapsulated in repository functions — no raw AQL outside this package

## What This Is NOT
- Not a service layer — no business logic, no LLM calls, no orchestration
- Not an ORM — this wraps `python-arango` with typed functions, not abstract models

## Boundaries
- Only this package imports `python-arango` (`arango` module)
- All functions accept and return plain dicts or Pydantic models — never expose `python-arango` cursors or response objects to callers
- Connection settings come from `config.settings` — never read env vars directly
- Schema changes must be reflected in both `schema.py` and `PRD.md` Section 5.1

## Key Invariants
- `get_db()` is the only way to obtain a database handle — all code uses this function
- `_ensure_database_exists()` is skipped on managed platforms (`settings.can_create_databases == False`)
- All versioned collections use `created`/`expired` interval semantics with `NEVER_EXPIRES = sys.maxsize`
- Every write to versioned collections must go through temporal versioning logic (expire old, insert new, re-create edges)
- MDI-prefixed indexes on `[created, expired]` are required on all versioned vertex and edge collections
- TTL indexes on `ttlExpireAt` (sparse) for historical version garbage collection

## PRD Reference
- Collections & data model: PRD Section 5.1
- Temporal versioning: PRD Section 5.3
- Named graphs: PRD Section 5.1 (Named Graphs table)
- Deployment modes: PRD Section 8.6
