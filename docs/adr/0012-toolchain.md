# ADR 0012: Toolchain

**Status:** Accepted

## Decision
Python 3.14, uv workspace, ruff (explicit `select = ALL`), pytest 9, pyright (strict on libs); Next.js 16, pnpm, TypeScript 6.0 (pinned below 7 because typescript-eslint does not yet support TS 7), Vitest, ESLint 10; OpenTofu for IaC.

## Why
Versions were the latest verified at build time; the lockfiles are the authority. Revisit the TypeScript pin when typescript-eslint supports TS >= 7.1.
