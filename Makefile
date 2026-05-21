.PHONY: help test lint format type-check build-static clean

# Databricks deployment: ./deploy_app.sh (config in app.yaml; frontend built by deploy script).
# This Makefile is optional — mainly for unit tests and local static export smoke checks.

export PYTHONPATH := src

help: ## Show targets
	@echo "Primary:  ./deploy_app.sh          # sync, build UI, deploy, UC grants (reads app.yaml)"
	@echo "Optional: make test | lint | build-static"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build-static: ## Next.js static export (same as deploy_app.sh pre-step)
	cd src/frontend && AOE_STATIC_EXPORT=1 npm run build

test: ## Unit tests (no Databricks / Arango required for most tests)
	@test -x .venv/bin/pytest || (echo "run: bash scripts/ensure-backend-deps.sh" >&2; exit 1)
	.venv/bin/pytest tests/unit -v

lint: ## Lint backend
	@test -x .venv/bin/ruff || (echo "run: bash scripts/ensure-backend-deps.sh" >&2; exit 1)
	.venv/bin/ruff check src/app src/migrations tests/
	.venv/bin/mypy src/app/ --ignore-missing-imports

format: ## Format backend
	.venv/bin/ruff format src/app src/migrations tests/

type-check: lint ## Alias for lint + frontend types
	cd src/frontend && npm run type-check

clean: ## Remove caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf src/frontend/.next src/frontend/out
