# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM base AS deps
# tesseract-ocr + poppler-utils (pdf2image's pdftoppm) for the real OCR backend
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY libs/common /app/libs/common
COPY services/ingestion /app/services/ingestion
RUN pip install -e /app/libs/common \
 && pip install -e "/app/services/ingestion[real]"
WORKDIR /app/services/ingestion

FROM deps AS dev
RUN pip install debugpy
EXPOSE 8001 5678
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

FROM deps AS prod
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
