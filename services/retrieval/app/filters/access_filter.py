from __future__ import annotations

from common.models import Chunk, ConfidentialityTier


def apply_access_filter(
    chunks: list[Chunk],
    tenant_id: str,
    matter_or_patient_id: str,
    confidentiality_tiers_allowed: list[ConfidentialityTier],
) -> tuple[list[Chunk], int]:
    """Metadata filtering applied BEFORE ranking, per docs/architecture.md §4:
    tenant isolation, matter/patient scoping, confidentiality tier — a user
    can never retrieve chunks outside their access grant, regardless of
    semantic similarity. This is enforced here even though the Gateway
    already checked role scope — defense in depth (docs/architecture.md §7).

    Returns (allowed_chunks, dropped_count) so the dropped count can be
    surfaced in SearchResponse.dropped_chunk_count for audit purposes.
    """
    allowed: list[Chunk] = []
    dropped = 0
    for chunk in chunks:
        if chunk.tenant_id != tenant_id:
            dropped += 1
            continue
        if chunk.matter_or_patient_id != matter_or_patient_id:
            dropped += 1
            continue
        if chunk.confidentiality_tier not in confidentiality_tiers_allowed:
            dropped += 1
            continue
        allowed.append(chunk)
    return allowed, dropped
