# ADR 0012: Toolchain

- Status: Accepted (date 2026-11-22)
- Blueprint: sections 4.5, 4.8, 18, 19 (19.2 to 19.6); decisions D20, D21, D22; gates G0.1, G0.2, G0.3,
  G0.5, G0.11

## Context

Every stage is proven by mechanical gates, so the tools are part of the product's safety argument. A tool
upgrade that silently changes what is checked would weaken a gate without anyone deciding it. `ruff` 0.16
enables 413 rules by default and formats Python code blocks in Markdown, so relying on defaults makes the gate
move with every release. The stack also has to support the newest Python while ML libraries may lag on wheels.

## Decision

- D21: Python 3.14, `uv` workspace with one lockfile (`uv sync --frozen` in CI), `ruff` for lint and format,
  `pytest` as the runner, `pyright` blocking (strict on `libs/` and security-critical services), `ty`
  informational only.
- `ruff` (19.3): explicit configuration with `select = ["ALL"]`, `line-length = 100`, `target-version =
  "py314"`, a short ignore list (formatter conflicts, conflicting docstring styles, `CPY`, `FIX`, `TD`), Google
  docstrings, and the banned-API list for R1, R2, R7, Pydantic v1 and connection ownership (ADR 0007). CI runs
  `ruff format --check` and `ruff check` with no `--fix`, and fails on unused suppressions. The config hash is
  recorded in every gate attestation. `docs/` is excluded from the format check.
- `pytest` (19.4): `--strict-markers --strict-config --import-mode=importlib`, `xfail_strict`, `asyncio_mode =
  "strict"`, `timeout = 180`, `filterwarnings = ["error"]`, one stage marker and one kind marker per test, no
  rerun plugin.
- `import-linter` contracts for the 4.7 boundaries (ADR 0001); ESLint, `tsc --noEmit` and Vitest for the frontend.
- D22: PostgreSQL 18; adopt 19 after GA plus its first minor. D20: Valkey instead of Redis 8 (AGPL).
- Adoption policy (4.5): new majors after GA, first patch, wheels and a full cumulative gate run; critical
  security fixes within 72 hours, high within 7 days; other updates after a 7 to 14 day cooldown; images pinned
  by digest.
- `docs/versions.md` records resolved versions; G0.1 fails on drift. `make gate STAGE=n` runs the sequence in
  19.6 and writes a signed `gates/stage-{n}.json`.

## Alternatives considered

- `ruff` defaults or a small curated rule set: rejected for the gate; defaults move with releases, and a small
  set leaves out security, async and datetime rules that `ALL` includes.
- Poetry or pip-tools: rejected; `uv` gives one workspace lockfile across all services and libraries.
- `mypy` as the blocking checker: not chosen; one blocking type checker is enough, and the blueprint picks
  `pyright` with strict mode on `libs/`. `ty` stays informational while it is 0.0.x.
- Redis 8: rejected (licence review, D20).

## Consequences

- Positive: a gate result names the exact tool versions and config hash; upgrades are deliberate.
- Negative: `select = ["ALL"]` produces many findings to fix or justify; Python 3.14 may force model-serving
  images to pin Python 3.13 (recorded in `docs/versions.md`, 4.8).
- Proven by G0.1 (frozen sync, versions equal the ledger), G0.2 (zero `ruff` findings under the pinned version
  and config hash), G0.3 (`pyright` clean), G0.5 (import boundaries) and G0.11 (no-mocks control).

## Current state

Versions in use, from [docs/versions.md](../versions.md): Python 3.14.4, `uv` 0.13.9, `ruff` 0.17.6,
`pyright` 1.1.414, `pytest` 9.2.0, Node 24.21.0, pnpm 10.34.9, PostgreSQL 18.7, Qdrant 1.20.0, Valkey 9.2.0,
OpenBao 2.7.2, PgBouncer 1.26.1. These are newer than the blueprint's October 2026 baseline, under the
adoption policy above.

The `pytest` settings in `pyproject.toml` match 19.4, and the banned-API list matches 19.3.

Open items, to close within Stage 0:

- G0.2: the repository's `ruff` configuration uses an explicit but smaller rule set (`E`, `F`, `W`, `I`, `B`,
  `UP`, `S`, `SIM`, `RUF`, `TID`) at `line-length = 120`, not the blueprint's `select = ["ALL"]` at 100. Moving
  to `ALL` at 100 and fixing or justifying the findings closes this.
- G0.3: `pyright` is a dependency but has no configuration and is not run by the `Makefile`.
- G0.1 and 19.6: there is no `make gate` target or signed gate attestation yet; gate suites are replaced for
  now by `make demo`, `make demo-web` and `make eval` (deviation 13 in [docs/mvp.md](../mvp.md)).
