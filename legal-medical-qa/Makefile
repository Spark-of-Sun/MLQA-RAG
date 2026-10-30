.DEFAULT_GOAL := help
PY := uv run
STAGE ?= $(shell cat STAGE)

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

sync: ## install the whole workspace from the lockfile (Python 3.14)
	uv sync --frozen --all-packages

env: ## fill .env with strong random LOCAL secrets (FORCE=1 overwrites; HOSTS=compose for container host names)
	$(PY) python tools/gen_env.py $(if $(FORCE),--force,) $(if $(HOSTS),--hosts $(HOSTS),)

doctor: ## check every real dependency is reachable and configured
	$(PY) python tools/doctor.py

up: ## start the full stack (needs Docker)
	docker compose up -d --build

down: ## stop the stack
	docker compose down

infra-test: ## start only the infrastructure the test suite needs
	docker compose -f compose.test.yaml up -d

migrate: ## create roles and the database, then run migrations (host to localhost:5432)
	$(PY) python tools/db_migrate.py

lint: ## ruff format check + ruff check + pyright + import boundaries
	$(PY) ruff format --check
	$(PY) ruff check
	$(PY) pyright
	$(PY) lint-imports

test: ## every test that needs no ML model and no AWS credentials
	$(PY) pytest -m "not live_models and not live_aws"

test-models: ## tests that load real ML models (needs ~8 GB RAM)
	$(PY) pytest -m live_models

test-aws: ## tests against real AWS KMS (needs credentials)
	$(PY) pytest -m live_aws

isolation: ## the cross-scope suite (merge gate)
	$(PY) pytest -m isolation

gate: ## the cumulative stage gate (see docs in stages.toml)
	$(PY) python tools/gatekeeper.py $(STAGE)

load-corpus: ## fetch the real public corpus and verify hashes
	$(PY) python corpus/fetchers.py
	$(PY) python corpus/fetchers.py --verify

frontend: ## install, type-check and build the frontend
	cd frontend && pnpm install --frozen-lockfile && pnpm typecheck && pnpm build

.PHONY: help sync env doctor up down infra-test migrate lint test test-models test-aws isolation gate load-corpus frontend
