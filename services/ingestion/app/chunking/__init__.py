
from common.models import TenantIndustry

from .base import ChunkCandidate, Chunker
from .legal import LegalClauseChunker
from .medical import SoapNoteChunker


def get_chunker(industry: TenantIndustry) -> Chunker:
    if industry == TenantIndustry.LEGAL:
        return LegalClauseChunker()
    if industry == TenantIndustry.MEDICAL:
        return SoapNoteChunker()
    raise ValueError(f"no chunker registered for industry: {industry}")


__all__ = ["Chunker", "ChunkCandidate", "LegalClauseChunker", "SoapNoteChunker", "get_chunker"]
