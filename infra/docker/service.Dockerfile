# One image recipe for every Python service (doc section 18): build with
#   docker build -f infra/docker/service.Dockerfile --build-arg SERVICE=gateway --build-arg PORT=8000 .
# SERVICE is the uv workspace package and the import name; EXTRAS adds optional dependencies
# (citation_validator: EXTRAS="--extra nli" for the NLI model runtime).
# NOT built in the authoring sandbox (no Docker there): build it in CI before first use.

FROM python:3.14-slim AS build
ARG SERVICE
ARG EXTRAS=""
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY libs ./libs
COPY services ./services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ${SERVICE} ${EXTRAS}

FROM python:3.14-slim
ARG SERVICE
ARG PORT=8000
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    SERVICE=${SERVICE} PORT=${PORT} CONTRACTS_DIR=/app/contracts PROMPTS_DIR=/app/prompts
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY contracts ./contracts
COPY prompts ./prompts
USER 10001
EXPOSE ${PORT}
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/%s' % (os.environ['PORT'], 'v1/health' if os.environ['SERVICE']=='gateway' else 'internal/v1/health'))"
CMD ["sh", "-c", "exec uvicorn ${SERVICE}.main:app --host 0.0.0.0 --port ${PORT} --no-server-header --proxy-headers"]
