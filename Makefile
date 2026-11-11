# Supplier iScan: the four project commands. Paths are relative to this file; nothing here depends
# on the host machine beyond the prerequisites listed in README.md ("Running it").
.DEFAULT_GOAL := help
.PHONY: help install fetch-model test test-model eval provider-shape provider-check lint run stop alert-apply approve-dependency

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-12s %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies from the lockfiles, and fetch the model
	cd backend && uv sync --locked
	$(MAKE) fetch-model
	cd agent-pack && uv sync --locked
	cd frontend && pnpm install --frozen-lockfile

fetch-model: ## Fetch the name-detection model (pinned, sha256-checked) into ~/.cache/supplier-iscan
	cd backend && uv run --locked python scripts/fetch_model.py

test: ## Run the backend and frontend tests
	cd backend && uv run --locked pytest
	cd frontend && pnpm test
	cd agent-pack && uv run --locked pytest

test-model: ## Run the tests that use the real name-detection model (needs make fetch-model)
	cd backend && uv run --locked pytest -m model

eval: ## Evaluate the LLM features: CONFIG=<approved id>|fake [PROMPTS=<path>] [RATINGS=<csv>]; live runs stay local
	cd backend && PYTHONPATH=.. uv run --locked python -m eval --config "$(CONFIG)" --prompts "$(PROMPTS)" --ratings "$(RATINGS)"

provider-shape: ## One live retrieval call on a synthetic query; writes the response SHAPE to diagnostics/: CONFIG=<id>
	cd backend && PYTHONPATH=.. PROVIDER_SHAPE_DIR="$(CURDIR)/diagnostics" uv run --locked python -m eval.provider_shape --config "$(CONFIG)"

provider-check: ## One tiny live structured call; prints OK or the provider's error type and message: CONFIG=<id>
	cd backend && PYTHONPATH=.. uv run --locked python -m eval.provider_check --config "$(CONFIG)"

lint: ## Run linters, format checks and type checks
	cd backend && uv run --locked ruff check . ../eval ../deploy ../ops && uv run --locked ruff format --check . ../eval ../deploy ../ops && uv run --locked mypy
	cd frontend && pnpm lint && pnpm typecheck
	cd agent-pack && uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy
	cd agent-pack && uv run --locked python scripts/check_dependencies.py
	python3 deploy/check_workflows.py

run: ## Start the database, the API and the frontend with Docker Compose
	docker compose up --build

stop: ## Stop the containers started by make run (the database volume is kept)
	docker compose down

alert-apply: ## Create or update the failure-rate alert policy (#53): ENV=dev, GCP_PROJECT_ID set; idempotent
	python3 deploy/monitoring/alert_policy.py apply "$(or $(ENV),dev)"

approve-dependency: ## Owner only: PACKAGE=name VERSION=x.y.z SCOPE=runtime|dev NOTE="why"
	cd agent-pack && python3 scripts/approve_dependency.py --package "$(PACKAGE)" --version "$(VERSION)" --scope "$(SCOPE)" --note "$(NOTE)"
