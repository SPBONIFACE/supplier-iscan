# Supplier iScan: the four project commands. Paths are relative to this file; nothing here depends
# on the host machine beyond the prerequisites listed in README.md ("Running it").
.DEFAULT_GOAL := help
.PHONY: help install fetch-model test test-model lint run stop

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

lint: ## Run linters, format checks and type checks
	cd backend && uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy
	cd frontend && pnpm lint && pnpm typecheck
	cd agent-pack && uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy

run: ## Start the database, the API and the frontend with Docker Compose
	docker compose up --build

stop: ## Stop the containers started by make run (the database volume is kept)
	docker compose down
