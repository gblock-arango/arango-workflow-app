.PHONY: help setup dev infra infra-down infra-reset backend frontend ui migrate test lint format type-check clean

# Optional repo-root .env (BACKEND_PORT, etc.). Safe if missing.
-include .env

# Default 8010 (matches src/frontend/.env.development). Override: make backend BACKEND_PORT=8000
BACKEND_PORT ?= 8010
BACKEND_PROXY_URL ?= http://127.0.0.1:$(BACKEND_PORT)
export PYTHONPATH := src
export BACKEND_PROXY_URL
export BACKEND_PORT

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## First-time setup (venv + npm + .env template)
	@test -f .env || cp .env.example .env && echo "==> Created .env from .env.example"
	@$(MAKE) ensure-deps
	@echo "==> Done. Run 'make infra' to start ArangoDB + Redis."

.PHONY: ensure-deps
ensure-deps:
	@echo "==> Ensuring Python venv + dev deps..."
	@bash scripts/ensure-backend-deps.sh
	@echo "==> Ensuring frontend deps..."
	cd src/frontend && npm install

dev: ## API + Next in one terminal (Ctrl+C stops both). Uses BACKEND_PORT (default 8010).
	@BACKEND_PORT=$(BACKEND_PORT) bash scripts/dev-local.sh

infra: ## Start ArangoDB + Redis (docker compose)
	docker compose up -d

infra-down: ## Stop infrastructure
	docker compose down

infra-reset: ## Stop infrastructure and delete volumes
	docker compose down -v

backend: ## Run FastAPI dev server (port BACKEND_PORT, default 8010)
	@echo "==> API http://127.0.0.1:$(BACKEND_PORT)  (frontend proxy: BACKEND_PROXY_URL in .env)"
	.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

frontend: ui ## Run Next.js dev server (hot reload on save)

ui: ## Live UI dev — edit src/frontend, browser updates via Fast Refresh
	@echo "==> UI   http://localhost:3000  (save files → instant refresh)"
	@echo "==> API  proxied to $(BACKEND_PROXY_URL)"
	@echo "==> Edit: src/frontend/src/app/  src/frontend/src/components/"
	cd src/frontend && npm run dev

migrate: ## Apply pending database migrations
	.venv/bin/python -m migrations.runner

test: ## Run backend tests
	.venv/bin/pytest tests/ -v

lint: ## Lint backend code
	.venv/bin/ruff check src/app src/migrations tests/
	.venv/bin/mypy src/app/ --ignore-missing-imports

format: ## Format backend code
	.venv/bin/ruff format src/app src/migrations tests/

type-check: ## Type-check backend + frontend
	.venv/bin/mypy src/app/ --ignore-missing-imports
	cd src/frontend && npm run type-check

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf src/frontend/.next
