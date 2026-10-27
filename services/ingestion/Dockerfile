FROM python:3.14-alpine@sha256:d8b74619d084eeeb518349d970e5b7223b5d2c41680d7d91eeb1ea9dc6dcfb43 AS base

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv

RUN addgroup -S -g 10001 lmqa && \
    adduser -S -u 10001 -G lmqa -h /home/lmqa -s /sbin/nologin lmqa

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/ libs/
COPY services/ingestion/ services/ingestion/
RUN uv sync --frozen --no-dev --package ingestion

USER lmqa:lmqa
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "ingestion.api:app", "--host", "0.0.0.0", "--port", "8000"]
