.DEFAULT_GOAL := help
PY := uv run --frozen
WITHENV := $(PY) python tools/withenv.py --

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## install Python (uv workspace) and frontend (pnpm) dependencies
	uv sync --frozen
	cd frontend && pnpm install --frozen-lockfile

setup: install ## first run: dependencies, local secrets, database, migrations
	$(PY) python tools/gen_env.py
	$(MAKE) db migrate

db: ## start PostgreSQL 18 + pgvector in Docker (127.0.0.1:5434)
	$(WITHENV) docker compose up -d --wait

db-stop: ## stop the database (data is kept)
	$(WITHENV) docker compose stop

db-reset: ## DELETE all local data (database volume and uploaded files) and start empty
	$(WITHENV) docker compose down -v
	rm -rf data/objects
	$(MAKE) db migrate

migrate: ## create roles, apply db/migrations, db/policies and db/roles
	$(PY) python tools/db_migrate.py

doctor: ## check settings, database, Auth0 and Gemini (prints names, never values)
	$(PY) python tools/doctor.py

dev: migrate ## run gateway (:8000) and frontend (:3000) with hot reload (applies migrations first)
	$(PY) python tools/dev.py

build: ## production build of the frontend
	$(WITHENV) pnpm --dir frontend build

start: migrate build ## run gateway and the production frontend (applies migrations first; best for demos)
	$(PY) python tools/dev.py --prod

corpus: ## download the real public corpus and verify every SHA-256
	$(PY) python corpus/fetchers.py

load-corpus: ## index the corpus into an admin's workspace: make load-corpus EMAIL=you@x.com [DOMAIN=legal]
	$(PY) python tools/load_corpus.py --email "$(EMAIL)" --domain "$(or $(DOMAIN),all)"

demo: ## simulate the whole workflow end to end through the API (separate lmqa_demo database, real Gemini)
	$(PY) python tools/demo.py

demo-web: ## simulate signed-in browsers against the built frontend (run `make build` first)
	$(PY) python tools/demo_web.py

lint: ## ruff format check + ruff lint + frontend type check
	$(PY) ruff format --check libs services tools
	$(PY) ruff check libs services tools
	cd frontend && pnpm typecheck

format: ## apply ruff formatting and safe fixes
	$(PY) ruff format libs services tools
	$(PY) ruff check --fix libs services tools

.PHONY: help install setup db db-stop db-reset migrate doctor dev build start corpus load-corpus demo demo-web lint format
