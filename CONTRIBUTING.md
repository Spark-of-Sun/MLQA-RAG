# Contributing to MLQA-RAG

## Delivery Model

All code is delivered via patches placed in `patches/`. Pushes to `main` and Pull Requests are disabled for individual contributors. See `PATCH_WORKFLOW.md` for instructions.

## Code Standards

- **Language:** Python 3.14, TypeScript (Next.js 16)
- **Formatting:** `uv run ruff format --check .`
- **Linting:** `uv run ruff check .` (zero findings, no new `# noqa`)
- **Types:** `uv run pyright` (strict mode on `libs/` and security services)
- **Import Rules:** `uv run lint-imports` (.importlinter)
- **No Mocks:** Real systems and containers only.
