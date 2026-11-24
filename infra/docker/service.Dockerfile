# One image per service (blueprint 4.2, 18): build with --build-arg SERVICE=<package> --build-arg PORT=<port>.
# Non-root, read-only root filesystem at runtime, no shell tools beyond the base, dependencies from the lockfile.
# Base images are pinned by digest in CI (4.5 adoption policy); the tag here is the starting point.
ARG PYTHON_IMAGE=python:3.14-slim-bookworm

FROM ${PYTHON_IMAGE} AS build
ARG SERVICE
ARG EXTRAS=""
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY services ./services
RUN uv sync --frozen --no-dev --package "${SERVICE}" ${EXTRAS}

FROM ${PYTHON_IMAGE}
ARG SERVICE
ARG PORT=8000
RUN groupadd --system --gid 10001 lmqa && useradd --system --uid 10001 --gid lmqa --no-create-home lmqa \
    && apt-get update && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build --chown=lmqa:lmqa /app/.venv /app/.venv
COPY --chown=lmqa:lmqa contracts ./contracts
COPY --chown=lmqa:lmqa prompts ./prompts
COPY --chown=lmqa:lmqa db ./db
COPY --chown=lmqa:lmqa infra/keyguard ./infra/keyguard
RUN touch /app/Makefile
ENV PATH="/app/.venv/bin:${PATH}" LMQA_ROOT=/app SERVICE=${SERVICE} PORT=${PORT} PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE ${PORT}
CMD ["sh", "-c", "exec uvicorn ${SERVICE}.asgi:app --host 0.0.0.0 --port ${PORT} --proxy-headers --no-server-header"]
