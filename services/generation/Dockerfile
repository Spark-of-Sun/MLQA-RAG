# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM base AS deps
COPY libs/common /app/libs/common
COPY libs/prompt_registry_client /app/libs/prompt_registry_client
COPY services/generation /app/services/generation
RUN pip install -e /app/libs/common \
 && pip install -e /app/libs/prompt_registry_client \
 && pip install -e "/app/services/generation[real]"
WORKDIR /app/services/generation

FROM deps AS dev
RUN pip install debugpy
EXPOSE 8003 5678
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--reload"]

FROM deps AS prod
EXPOSE 8003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "2"]

