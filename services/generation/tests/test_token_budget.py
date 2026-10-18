from __future__ import annotations

from app.schemas.requests import InputChunk
from app.token_budget import trim_chunks_by_budget
from app.token_budget.counter import ApproxTokenCounter


def test_trim_keeps_chunks_within_budget():
    chunks = [
        InputChunk(chunk_id="c1", document_id="d1", text="short text", page=1),
        InputChunk(chunk_id="c2", document_id="d1", text="also short", page=2),
    ]
    result = trim_chunks_by_budget(chunks, max_prompt_tokens=1000, counter=ApproxTokenCounter())
    assert [c.chunk_id for c in result.kept] == ["c1", "c2"]
    assert result.dropped_chunk_ids == []


def test_trim_drops_chunks_entirely_when_over_budget():
    big_text = "word " * 2000  # ~2500 approx tokens
    chunks = [
        InputChunk(chunk_id="c1", document_id="d1", text="short", page=1),
        InputChunk(chunk_id="c2", document_id="d1", text=big_text, page=2),
        InputChunk(chunk_id="c3", document_id="d1", text="short too", page=3),
    ]
    result = trim_chunks_by_budget(chunks, max_prompt_tokens=400, counter=ApproxTokenCounter())
    kept_ids = [c.chunk_id for c in result.kept]
    assert "c2" in result.dropped_chunk_ids
    assert "c2" not in kept_ids
    # c2 is dropped ENTIRELY, never truncated — no partial c2 text anywhere in kept
    assert all(c.chunk_id != "c2" for c in result.kept)
