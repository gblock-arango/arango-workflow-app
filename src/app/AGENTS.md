# app/ — Application Root

FastAPI application entry point and top-level wiring.

## What This Is
- `main.py`: FastAPI app factory, middleware, router registration, lifespan hooks
- `config.py`: Pydantic settings with deployment-mode-aware configuration

## What This Is NOT
- Not where business logic lives (that's `services/`)
- Not where database queries live (that's `db/`)

## Boundaries
- `main.py` only wires routers and middleware — no business logic, no DB queries
- `config.py` is the single source for all configuration — other modules import `settings` from here
- New routers must be registered in `main.py` via `app.include_router()`

## Key Invariants
- `settings` is a module-level singleton — never instantiate `Settings()` elsewhere
- `DeploymentMode` enum drives all capability flags (`has_gae`, `is_cluster`, `can_create_databases`)
- Lifespan hook must call `close_db()` on shutdown
- CORS origins must be explicitly listed (no wildcards in production)

## PRD Reference
- Deployment modes: PRD Section 8.6 (ArangoDB Deployment Modes)
- App architecture: PRD Section 4.1
