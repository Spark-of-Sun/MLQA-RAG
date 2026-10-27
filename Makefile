.PHONY: up down doctor gate isolation load-corpus eval precheck

SHELL := /bin/bash
PROFILE ?= mvp-a
STAGE ?= 0

up:
	@if command -v docker >/dev/null 2>&1; then \
		docker compose up -d; \
	else \
		echo "ERROR: docker is not installed or not available in PATH"; \
		exit 1; \
	fi

down:
	@if command -v docker >/dev/null 2>&1; then \
		docker compose down; \
	else \
		echo "ERROR: docker is not installed or not available in PATH"; \
		exit 1; \
	fi

doctor:
	uv run python -m tools.doctor.main

migrate:
	uv run python -m tools.migrate.main

gate:
	@if [ ! -d "tools/gatekeeper" ] || [ ! -f "tools/gatekeeper/main.py" ]; then \
		echo "ERROR: tools/gatekeeper is not yet implemented"; \
		exit 1; \
	fi
	uv run python -m tools.gatekeeper.main --stage $(STAGE) --profile $(PROFILE)

isolation:
	uv run pytest libs/lmqa_db/tests/test_rls_live.py libs/lmqa_vectorstore/tests/test_vectorstore.py services/retrieval/tests/test_retrieval.py tools/state_machine_gen/tests/test_state_machines.py libs/lmqa_audit/tests/test_chain.py -v

load-corpus:
	@if [ ! -d "tools/load_corpus" ] || [ ! -f "tools/load_corpus/main.py" ]; then \
		echo "ERROR: tools/load_corpus is not yet implemented"; \
		exit 1; \
	fi
	@echo "Loading corpus..."

eval:
	@if [ ! -d "eval" ] || [ ! -f "eval/run.py" ]; then \
		echo "ERROR: eval harness is not yet implemented"; \
		exit 1; \
	fi
	@echo "Running evaluation..."

precheck:
	@if [ -n "$(OWNER)" ]; then \
		echo "Running precheck for owner: $(OWNER)"; \
	else \
		echo "Running precheck..."; \
	fi
	uv run ruff format --check .
	uv run ruff check .
	uv run pyright
	uv run lint-imports
	uv run python -m tools.ownership_check --check-all
	gitleaks detect --source . --no-banner
	uv run pytest -v
