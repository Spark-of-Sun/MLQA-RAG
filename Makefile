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
	@echo "=== MLQA-RAG Environment Doctor ==="
	@echo -n "git: " && (command -v git >/dev/null 2>&1 && git --version || echo "NOT CONFIGURED")
	@echo -n "gh: " && (command -v gh >/dev/null 2>&1 && gh --version | head -n1 || echo "NOT CONFIGURED")
	@echo -n "python: " && (command -v python3.14 >/dev/null 2>&1 && python3.14 --version || (python3 --version 2>&1 | grep "3.14") || echo "NOT CONFIGURED")
	@echo -n "uv: " && (command -v uv >/dev/null 2>&1 && uv --version || echo "NOT CONFIGURED")
	@echo -n "node: " && (command -v node >/dev/null 2>&1 && node --version || echo "NOT CONFIGURED")
	@echo -n "pnpm: " && (command -v pnpm >/dev/null 2>&1 && pnpm --version || echo "NOT CONFIGURED")
	@echo -n "docker: " && (command -v docker >/dev/null 2>&1 && docker --version || echo "NOT CONFIGURED")
	@echo -n "opentofu: " && (command -v tofu >/dev/null 2>&1 && tofu --version | head -n1 || echo "NOT CONFIGURED")
	@echo -n "aws-cli: " && (command -v aws >/dev/null 2>&1 && aws --version || echo "NOT CONFIGURED")
	@echo -n "gitleaks: " && (command -v gitleaks >/dev/null 2>&1 && gitleaks version || echo "NOT CONFIGURED")
	@echo -n "pre-commit: " && (command -v pre-commit >/dev/null 2>&1 && pre-commit --version || echo "NOT CONFIGURED")
	@echo -n "pip-audit: " && (command -v pip-audit >/dev/null 2>&1 && pip-audit --version || echo "NOT CONFIGURED")
	@echo -n "trivy: " && (command -v trivy >/dev/null 2>&1 && trivy --version | head -n1 || echo "NOT CONFIGURED")
	@echo -n "cosign: " && (command -v cosign >/dev/null 2>&1 && cosign version 2>&1 | grep "GitVersion" || echo "NOT CONFIGURED")
	@echo "--- Configuration ---"
	@if [ -f .env ]; then echo ".env: present"; else echo ".env: NOT CONFIGURED (missing)"; fi

gate:
	@if [ ! -d "tools/gatekeeper" ] || [ ! -f "tools/gatekeeper/main.py" ]; then \
		echo "ERROR: tools/gatekeeper is not yet implemented"; \
		exit 1; \
	fi
	uv run python -m tools.gatekeeper.main --stage $(STAGE) --profile $(PROFILE)

isolation:
	@if [ ! -d "tests/isolation" ]; then \
		echo "ERROR: tests/isolation suite is not yet implemented"; \
		exit 1; \
	fi
	@echo "Running isolation suite..."

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
	uv run pytest -m "stage0"
