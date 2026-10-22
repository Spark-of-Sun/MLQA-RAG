#!/usr/bin/env bash
# setup_venvs.sh — creates one isolated virtualenv per service, each
# installed from that service's OWN pyproject.toml (the single source of
# truth for its dependencies — see docs/adr/0001-service-split.md). No
# shared requirements file: bare-metal venvs stay as isolated from each
# other as each service's own Docker image already is.
#
# Layout: .gitignore ignores both ".venv-*/" (repo root) and ".venv/"
# (nested per-service) — this defaults to the repo-root ".venv-<service>"
# convention. Set VENV_LAYOUT=nested to use services/<name>/.venv instead
# (launcher.py checks both automatically either way).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_LAYOUT="${VENV_LAYOUT:-root}"   # "root" | "nested"
PY="${PYTHON_BIN:-python3}"
WITH_REAL="${WITH_REAL:-0}"          # 1 = also install each service's [real] extra

declare -A SERVICE_DIRS=(
  [gateway]="services/gateway"
  [ingestion]="services/ingestion"
  [retrieval]="services/retrieval"
  [generation]="services/generation"
  [citation-validator]="services/citation_validator"
)

venv_path_for() {
  local name="$1" dir="$2"
  if [[ "$VENV_LAYOUT" == "nested" ]]; then
    echo "$REPO_ROOT/$dir/.venv"
  else
    echo "$REPO_ROOT/.venv-$name"
  fi
}

echo "[setup_venvs] layout: $VENV_LAYOUT   real extras: $WITH_REAL"

for name in "${!SERVICE_DIRS[@]}"; do
  dir="${SERVICE_DIRS[$name]}"
  venv="$(venv_path_for "$name" "$dir")"

  echo ""
  echo "=== $name ==="
  echo "  pyproject : $dir/pyproject.toml"
  echo "  venv      : $venv"

  if [[ -d "$venv" ]]; then
    echo "  venv already exists — skipping creation (delete it to rebuild)"
  else
    "$PY" -m venv "$venv"
  fi

  # shellcheck disable=SC1091
  source "$venv/bin/activate"
  pip install --upgrade pip -q

  # Shared libs first, editable — installed into EVERY service's venv
  # (same source, separate installs — no cross-venv collision possible).
  pip install -e "$REPO_ROOT/libs/common" -q
  if grep -q "legalmed-prompt-registry-client" "$REPO_ROOT/$dir/pyproject.toml" 2>/dev/null; then
    pip install -e "$REPO_ROOT/libs/prompt_registry_client" -q
  fi

  # The service itself: base deps + [dev] (pytest/ruff/mypy — matches
  # `make lint` / `make test` in the Makefile, minus Docker).
  pip install -e "$REPO_ROOT/$dir[dev]" -q

  # Optional: [real] extra too — tesseract/pdf2image, sentence-transformers,
  # tiktoken, llmlingua, anthropic/google-genai SDKs. Needed if you flip
  # .env.local away from the fake/approx backends toward the real
  # CPU-friendly checkpoints docs/architecture.md §6 describes for the
  # docker-compose local run. Note: tesseract-ocr + poppler-utils are
  # SYSTEM packages (see services/ingestion/Dockerfile's apt-get line) —
  # installing [real] here does NOT install those; apt/brew install them
  # yourself if you flip OCR_ENGINE=tesseract.
  if [[ "$WITH_REAL" == "1" ]] && grep -q '\[project.optional-dependencies\]' "$REPO_ROOT/$dir/pyproject.toml" 2>/dev/null; then
    pip install -e "$REPO_ROOT/$dir[real]" -q || echo "  (no [real] extra for $name, or install failed — continuing)"
  fi

  deactivate
  echo "  done."
done

echo ""
echo "All venvs ready. Run 'python launcher.py list' to confirm what each service will use."
echo "Re-run with WITH_REAL=1 ./setup_venvs.sh to add the real OCR/embedding/reranker/LLM SDKs."
