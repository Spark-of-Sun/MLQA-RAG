.DEFAULT_GOAL := help
PY := uv run --frozen
WITHENV := $(PY) python tools/withenv.py --

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: hooks ## install Python (uv workspace) and frontend (pnpm) dependencies
	uv sync --frozen
	cd frontend && pnpm install --frozen-lockfile

hooks: ## enable the repo's git hooks (blocks commits that contain secrets)
	git config core.hooksPath .githooks

setup: install ## first run: dependencies, local secrets, infrastructure, migrations
	$(PY) python tools/gen_env.py
	$(MAKE) up

infra-config: ## render the credential files compose.yaml mounts (data/infra/, never printed)
	$(PY) python tools/infra_config.py

up: infra-config ## start the local stack: PostgreSQL, PgBouncer, Valkey, Qdrant, SeaweedFS, OpenBao; then migrate
	$(WITHENV) docker compose up -d --wait postgres openbao
	$(MAKE) migrate
	$(WITHENV) docker compose up -d --wait

up-scan: infra-config ## also start ClamAV (profile scan, about 1.2 GB of memory)
	$(WITHENV) docker compose --profile scan up -d --wait clamav

down: ## stop every container (data is kept)
	$(WITHENV) docker compose --profile scan --profile observability stop

db: infra-config ## start PostgreSQL 18 + pgvector alone (127.0.0.1:5434)
	$(WITHENV) docker compose up -d --wait postgres

db-stop: down ## alias of down

db-reset: ## DELETE all local data (database, vectors, objects, keys, uploaded files) and start empty
	$(WITHENV) docker compose --profile scan --profile observability down -v
	rm -rf data/objects
	$(MAKE) up

migrate: ## create roles, alembic upgrade head (db/migrations), re-apply db/policies and db/roles
	$(PY) python tools/db_migrate.py

reencrypt: ## provision keys and encrypt any plaintext content and contact columns (normally run by migrate)
	$(PY) python tools/reencrypt_fields.py

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

demo: ## run the whole workflow end to end through the API as real Auth0 accounts (lmqa_demo database, real Gemini)
	$(PY) python tools/demo.py

eval: ## retrieval metrics on the public corpus vs eval/floors.toml (ARGS="--answers" adds end-to-end answers)
	$(PY) python eval/harness/run.py $(ARGS)

demo-web: ## drive the built frontend as real Auth0 accounts (run `make build` first)
	$(PY) python tools/demo_web.py

PYSRC := libs services tools eval corpus tests conftest.py

lint: ## ruff format check + ruff lint + import contracts + frontend type check
	$(PY) ruff format --check $(PYSRC)
	$(PY) ruff check $(PYSRC)
	$(PY) lint-imports
	cd frontend && pnpm typecheck

format: ## apply ruff formatting and safe fixes
	$(PY) ruff format $(PYSRC)
	$(PY) ruff check --fix $(PYSRC)

STAGE_NOW := $(shell cat STAGE 2>/dev/null || echo 0)
STAGE_MARKS := $(shell for n in $$(seq 0 $(STAGE_NOW)); do printf 'stage%s or ' $$n; done | sed 's/ or $$//')

test: ## pytest for stages 0..STAGE without the live lanes (needs make up)
	$(PY) pytest -m "($(STAGE_MARKS)) and not live_auth0 and not live_kms and not live_llm"

gate: ## run the cumulative gate and write gates/stage-N.json: make gate [STAGE=n] [PROFILE=full]
	$(PY) python tools/gatekeeper.py gate $(if $(STAGE),--stage $(STAGE)) --profile $(or $(PROFILE),full)

advance: ## move STAGE forward; requires a passing full-profile attestation on this exact commit
	$(PY) python tools/gatekeeper.py advance

paths: ## rule 1: changed paths must belong to stages <= STAGE + 1: make paths [BASE=origin/beta]
	$(PY) python tools/gatekeeper.py paths --base $(or $(BASE),origin/beta)

versions: ## regenerate docs/versions.md from the lockfiles and the running servers
	$(PY) python tools/gen_versions.py --servers

contracts: ## regenerate contracts/openapi/gateway.json and the frontend's typed client
	$(PY) python tools/export_openapi.py
	pnpm --dir frontend gen:api


.PHONY: test gate advance paths versions contracts state-machines workers ops

state-machines: ## check the generated transitions revision; REVISION=NNNN_name writes a new one after the head
	$(PY) python tools/state_machine_gen.py $(if $(REVISION),--revision $(REVISION),--check)

workers: ## run the production background processes (identity, audit, ingestion worker, indexer, reconciler)
	$(PY) python tools/dev.py --workers

ops: ## run the operator plane API on 127.0.0.1:8006 (operator ingress only)
	$(PY) uvicorn ops.asgi:app --host 127.0.0.1 --port 8006

# ---- onekami.site server (docs/deploy.md). Settings come from .env.deployed, never .env. --------------------------
DEPLOY_ENV := LMQA_ENV_FILE=.env.deployed
DEPLOY_COMPOSE := docker compose -f compose.yaml -f compose.deployed.yaml

deploy-setup: ## server, first run: Python deps, secrets into .env.deployed, infrastructure, migrations
	uv sync --frozen
	$(DEPLOY_ENV) $(PY) python tools/gen_env.py
	$(DEPLOY_ENV) $(MAKE) up

deploy-up: ## server: build and (re)start the API and the Cloudflare Tunnel, applying migrations first
	$(DEPLOY_ENV) $(PY) python tools/deploy_check.py
	$(DEPLOY_ENV) $(MAKE) up
	$(DEPLOY_ENV) $(WITHENV) $(DEPLOY_COMPOSE) --profile tunnel up -d --build --wait

deploy-update: ## server: pull the deployed branch, then deploy-up
	git pull --ff-only origin deployed
	uv sync --frozen
	$(MAKE) deploy-up

deploy-down: ## server: stop everything (data is kept)
	$(DEPLOY_ENV) $(WITHENV) $(DEPLOY_COMPOSE) --profile tunnel --profile scan --profile observability stop

deploy-ps: ## server: container status and memory use
	$(DEPLOY_ENV) $(WITHENV) $(DEPLOY_COMPOSE) --profile tunnel ps
	docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'

deploy-logs: ## server: follow the API and tunnel logs
	$(DEPLOY_ENV) $(WITHENV) $(DEPLOY_COMPOSE) --profile tunnel logs -f --tail 200 gateway cloudflared

deploy-doctor: ## server: make doctor against .env.deployed
	$(DEPLOY_ENV) $(PY) python tools/doctor.py

.PHONY: deploy-setup deploy-up deploy-update deploy-down deploy-ps deploy-logs deploy-doctor
.PHONY: help install hooks setup infra-config up up-scan down db db-stop db-reset migrate doctor dev build start corpus load-corpus demo demo-web eval lint format
