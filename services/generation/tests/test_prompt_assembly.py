from __future__ import annotations

from app.prompt_assembly import DEFAULT_TEMPLATE, assemble_prompt
from app.prompt_assembly.assembler import reorder_for_lost_in_middle
from app.schemas.requests import InputChunk


def test_chunk_tag_format_matches_citation_parser_expectations():
    chunks = [InputChunk(chunk_id="c1", document_id="doc1", text="term is 12 months", page=4, section="4.2")]
    assembled = assemble_prompt("What is the term?", chunks, DEFAULT_TEMPLATE)
    assert '<chunk id="c1" doc="doc1" page="4" section="4.2">' in assembled.user_prompt
    assert "term is 12 months</chunk>" in assembled.user_prompt
    assert assembled.chunk_ids_in_context == ["c1"]


def test_system_prompt_includes_refusal_instruction():
    assembled = assemble_prompt("x", [], DEFAULT_TEMPLATE)
    assert "the provided documents do not address this" in assembled.system_prompt


def test_reorder_puts_most_relevant_first_and_last():
    chunks = [
        InputChunk(chunk_id="c1", document_id="d", text="t1", page=1),  # most relevant
        InputChunk(chunk_id="c2", document_id="d", text="t2", page=2),
        InputChunk(chunk_id="c3", document_id="d", text="t3", page=3),
        InputChunk(chunk_id="c4", document_id="d", text="t4", page=4),  # least relevant
    ]
    reordered = reorder_for_lost_in_middle(chunks)
    assert reordered[0].chunk_id == "c1"   # most relevant -> start
    assert reordered[-1].chunk_id == "c2"  # second-most relevant -> end
    assert {c.chunk_id for c in reordered} == {"c1", "c2", "c3", "c4"}
