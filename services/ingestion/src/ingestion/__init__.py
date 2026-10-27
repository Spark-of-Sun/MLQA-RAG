"""LMQA Ingestion service: uploads, scan, parse, chunk, store, and index."""

from __future__ import annotations

from ingestion.api import app
from ingestion.chunker import StructuralChunker
from ingestion.config import IngestionConfig
from ingestion.models import DocumentTarget, IngestionRequest
from ingestion.parser import DocumentParser, OcrDisabledError, PageText, ParseError
from ingestion.pipeline import IngestionPipeline
from ingestion.scanner import DocumentScanner, ScanValidationError

__all__ = [
    "DocumentParser",
    "DocumentScanner",
    "DocumentTarget",
    "IngestionConfig",
    "IngestionPipeline",
    "IngestionRequest",
    "OcrDisabledError",
    "PageText",
    "ParseError",
    "ScanValidationError",
    "StructuralChunker",
    "app",
]
