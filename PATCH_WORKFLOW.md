# PATCH_WORKFLOW.md

Welcome to the MLQA-RAG project!

Developers do not push directly to `main` or open Pull Requests. Instead, code is delivered via **patches** processed by the Project Manager Agent.

---

## 1. Where to Put Your Patches

Save your patch files in the root `patches/` directory (untracked by git):
```
patches/
  maya_20261026_ci-skeleton.patch
  applied/    (processed and landed commits)
  rejected/   (returned patches requiring changes)
  results/    (detailed check reports for each patch)
```

## 2. Patch File Naming

Name your patch file: `<handle>_<YYYYMMDD>_<topic>.patch`
Example: `priya_20261102_pdf-parser.patch`

## 3. Required Patch Header

Every patch must start with the standard header comment (before the first `diff --git`):

```
# Patch: <topic>
# Owner: <your-handle> (<your-role>)
# Base: main @ <commit sha or snapshot date>
# Phase / gate: <for example P1 / G1.1>
# Files: <every path in the patch>
# Verified: <what you tested locally, or NOT RUN>
# Suggested commit: [<handle>] <area>: <summary>   (trailer: Owner: <name>)
```

## 4. What Happens Next

The Agent processes patches oldest-first in the queue:
1. Verifies ownership against `OWNERSHIP.md`.
2. Validates stage boundaries (`STAGE + 1` in `stages.toml`).
3. Checks clean apply on `main` (`git apply --check`).
4. Runs automated checks: format, lint, types (pyright), import boundaries, secrets (gitleaks), tests.
5. If all checks pass: commits to `main` and pushes to GitHub.
6. The result and logs are saved to `patches/results/<patch-name>.md`.

## 5. Local Pre-check

You can run the same checks locally before submitting:
```bash
make precheck OWNER=<your-handle>
```
