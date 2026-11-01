# Supplier iScan: the four project commands. Paths are relative to this file; nothing here depends
# on the host machine beyond the prerequisites listed in README.md ("Running it").
.DEFAULT_GOAL := help
.PHONY: help install test lint run stop

help: ## List the commands
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies from the lockfiles
	cd backend && uv sync --locked
	cd agent-pack && uv sync --locked
	cd frontend && pnpm install --frozen-lockfile

test: ## Run the backend and frontend tests
	cd backend && uv run --locked pytest
	cd frontend && pnpm test
	cd agent-pack && uv run --locked pytest

lint: ## Run linters, format checks and type checks
	cd backend && uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy
	cd frontend && pnpm lint && pnpm typecheck
	cd agent-pack && uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy

run: ## Start the database, the API and the frontend with Docker Compose
	docker compose up --build

stop: ## Stop the containers started by make run (the database volume is kept)
	docker compose down
