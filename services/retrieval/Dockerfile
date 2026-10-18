# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM base AS deps
COPY libs/common /app/libs/common
COPY services/retrieval /app/services/retrieval
RUN pip install -e /app/libs/common \
 && pip install -e "/app/services/retrieval[real]"
WORKDIR /app/services/retrieval

FROM deps AS dev
RUN pip install debugpy
EXPOSE 8002 5678
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]

FROM deps AS prod
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "2"]
