"""Configuration settings for ingestion service."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class IngestionConfig(BaseModel):
    """Ingestion service runtime configuration."""

    max_file_size_bytes: int = Field(
        default=50 * 1024 * 1024, description="Maximum allowed document size (50MB)"
    )
    supported_content_types: set[str] = Field(
        default_factory=lambda: {
            "application/pdf",
            "text/html",
            "text/plain",
            "application/xml",
        }
    )
    quarantine_prefix: str = Field(default="quarantine", description="Storage quarantine prefix")
    clamav_host: str = Field(default="127.0.0.1", description="ClamAV daemon host")
    clamav_port: int = Field(default=3310, description="ClamAV daemon port")
    qdrant_url: str = Field(
        default_factory=lambda: os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    )
    qdrant_collection: str = Field(default="document_chunks")
    ocr_enabled: bool = Field(
        default_factory=lambda: (
            os.getenv("OCR_QUARANTINE_ENABLED", "0").lower() in ("1", "true", "yes")
        )
    )
    min_chunk_tokens: int = Field(default=40)
    target_chunk_tokens_min: int = Field(default=300)
    target_chunk_tokens_max: int = Field(default=700)
    max_chunk_tokens: int = Field(default=1200)
