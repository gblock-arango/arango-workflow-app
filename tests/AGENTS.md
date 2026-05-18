# tests/ — Test Suite

pytest-based tests for the AOE backend.

## What This Is
All backend tests: unit, integration, and end-to-end. Organized to mirror the application structure.

## Structure
```
tests/
├── conftest.py          # Shared fixtures (test_db, mock_settings, etc.)
├── fixtures/            # Static test data
│   ├── llm_responses/   # Recorded LLM outputs for deterministic extraction tests
│   ├── ontologies/      # Sample OWL/TTL files (from aws_ontology)
│   ├── sample_documents/# Test PDFs, DOCX, Markdown files
│   └── embeddings/      # Pre-computed vector embeddings
├── unit/                # Fast, isolated, mocked dependencies
├── integration/         # Real ArangoDB + Redis via Docker
└── e2e/                 # Full workflow tests (upload → extract → curate → promote)
```

## What This Is NOT
- Not frontend tests (those are in `frontend/e2e/` and `frontend/src/**/__tests__/`)
- Not load/performance tests

## Boundaries
- Unit tests mock all external dependencies (ArangoDB, Redis, LLM providers)
- Integration tests use a real ArangoDB instance via Docker (auto-created, auto-dropped per session)
- E2E tests run against the full FastAPI app via `httpx.AsyncClient`
- LLM responses are always mocked with recorded fixtures — never call real LLM APIs in tests

## Key Invariants
- Tests never mutate shared state — each test gets isolated fixtures
- Integration test databases use unique names (`aoe_test_{uuid}`) and are dropped after the session
- Coverage thresholds: ≥ 80% overall, ≥ 90% for `services/` and `db/`, ≥ 85% for `api/`
- Every new service/model file must have a corresponding unit test file
- Every new API endpoint must have an integration test

## PRD Reference
- Testing strategy: PRD Section 8.9
- Coverage targets: PRD Section 8.9 (Coverage Targets table)
- Mock strategy: PRD Section 8.9 (Mock Strategy table)
- CI pipeline: PRD Section 8.9 (CI Pipeline Test Requirements)
