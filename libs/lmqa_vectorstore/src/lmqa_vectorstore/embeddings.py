"""Embedding utilities for RAG vector representations."""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def compute_deterministic_embedding(text: str, dim: int = 384) -> list[float]:
    """Generate a deterministic normalized dense embedding vector from text.

    Uses multiple salted SHA-256 hashes projected across the requested dimensionality.
    Ensures zero external API dependency during offline testing and initial stages.
    """
    if not text.strip():
        # Zero vector for empty text
        return [0.0] * dim

    vector: list[float] = []
    # Generate vector components via salted sha256 chunks
    salt = 0
    words = text.lower().split()
    word_hashes = [int(hashlib.sha256(w.encode()).hexdigest()[:8], 16) for w in words]

    while len(vector) < dim:
        h = hashlib.sha256(f"{salt}:{text}".encode()).digest()
        # Extract 8 floats from 32-byte digest
        for i in range(0, 32, 4):
            val = int.from_bytes(h[i : i + 4], byteorder="little", signed=True) / (2**31)
            # Add small term frequency signal
            if word_hashes:
                idx = (len(vector) + salt) % len(word_hashes)
                val += (word_hashes[idx] % 100) / 500.0
            vector.append(val)
            if len(vector) >= dim:
                break
        salt += 1

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vector))
    if norm > 0.0:
        return [x / norm for x in vector]
    return vector


def cosine_similarity(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if len(v1) != len(v2):
        msg = f"Vector dimensions do not match: {len(v1)} != {len(v2)}"
        raise ValueError(msg)
    dot = sum(a * b for a, b in zip(v1, v2, strict=True))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)
