.PHONY: up down build restart logs ps seed eval test test-e2e test-load migrate clean lint

COMPOSE := docker compose

## Build and start the full local stack (detached), tailing nothing.
up:
	$(COMPOSE) up -d --build
	@echo "Gateway:   http://localhost:8000"
	@echo "Frontend:  http://localhost:3000"
	@echo "MinIO UI:  http://localhost:9001"
	@echo "Qdrant UI: http://localhost:6333/dashboard"

## Stop the stack, keep volumes (data persists).
down:
	$(COMPOSE) down

## Rebuild all service images without starting them.
build:
	$(COMPOSE) build

## Restart one service, e.g. `make restart s=generation`
restart:
	$(COMPOSE) restart $(s)

## Tail logs for all services, or one: `make logs s=retrieval`
logs:
	$(COMPOSE) logs -f --tail=200 $(s)

## Show running services and health status.
ps:
	$(COMPOSE) ps

## Run Alembic migrations (idempotent; also runs automatically on `make up`).
migrate:
	$(COMPOSE) exec gateway alembic -c /app/db/migrations/alembic.ini upgrade head

## Load a demo tenant + sample legal/medical documents into the running stack.
seed:
	$(COMPOSE) exec gateway python /app/scripts/seed_demo_tenant.py

## Run the citation-validation eval set against the live stack.
## Fails non-zero if the pass rate drops below the configured threshold.
eval:
	$(COMPOSE) exec generation python /app/scripts/run_citation_eval.py

## Run unit tests for every service.
test:
	$(COMPOSE) run --rm gateway pytest
	$(COMPOSE) run --rm ingestion pytest
	$(COMPOSE) run --rm retrieval pytest
	$(COMPOSE) run --rm generation pytest
	$(COMPOSE) run --rm citation-validator pytest

## Run the full query-to-cited-answer e2e flow against the local stack.
test-e2e:
	$(COMPOSE) exec gateway pytest /app/tests/e2e

## Run concurrency/latency load tests against the local stack.
test-load:
	$(COMPOSE) exec gateway pytest /app/tests/load

## Lint/type-check every service (matches .github/workflows/ci.yml).
lint:
	$(COMPOSE) run --rm gateway ruff check . && $(COMPOSE) run --rm gateway mypy app
	$(COMPOSE) run --rm ingestion ruff check . && $(COMPOSE) run --rm ingestion mypy app
	$(COMPOSE) run --rm retrieval ruff check . && $(COMPOSE) run --rm retrieval mypy app
	$(COMPOSE) run --rm generation ruff check . && $(COMPOSE) run --rm generation mypy app
	$(COMPOSE) run --rm citation-validator ruff check . && $(COMPOSE) run --rm citation-validator mypy app

## Stop the stack and remove volumes — full reset, including Postgres/Qdrant/MinIO data.
clean:
	$(COMPOSE) down -v