from __future__ import annotations

from dataclasses import dataclass

from prompt_registry_client import PromptTemplate

from app.schemas.requests import InputChunk


@dataclass
class AssembledPrompt:
    system_prompt: str
    user_prompt: str
    chunk_ids_in_context: list[str]


def _chunk_tag(chunk: InputChunk) -> str:
    """Matches Chunk.to_prompt_tag() in libs/common/models/chunk.py exactly
    — the Citation Validator's parser depends on this format being identical
    across Ingestion-time chunk storage and Generation-time prompt injection.
    """
    section_attr = f' section="{chunk.section}"' if chunk.section else ""
    return f'<chunk id="{chunk.chunk_id}" doc="{chunk.document_id}" page="{chunk.page}"{section_attr}>'


def reorder_for_lost_in_middle(chunks: list[InputChunk]) -> list[InputChunk]:
    """Context reordering, per docs/architecture.md §4 step 5: place the
    most relevant chunks at the start AND end of the prompt, not buried
    in the middle. Input must already be sorted most-relevant-first
    (Retrieval returns chunks in rank order).
    """
    result: list[InputChunk | None] = [None] * len(chunks)
    left, right = 0, len(chunks) - 1
    for i, chunk in enumerate(chunks):
        if i % 2 == 0:
            result[left] = chunk
            left += 1
        else:
            result[right] = chunk
            right -= 1
    return result  # type: ignore[return-value]


def _format_few_shot_examples(examples: list[dict]) -> str:
    blocks = []
    for ex in examples:
        context = ex.get("context", "")
        blocks.append(
            f"Example question: {ex['question']}\n"
            f"Example context: {context}\n"
            f"Example answer: {ex['answer']}"
        )
    return "\n\n".join(blocks)


def assemble_prompt(question: str, chunks: list[InputChunk], template: PromptTemplate) -> AssembledPrompt:
    """Builds the final system/user prompt pair sent to the LLM client.
    Chunk injection format and reordering per docs/architecture.md §5 and
    §4 step 5. `chunks` must be the already-compressed, budget-trimmed set.
    """
    reordered = reorder_for_lost_in_middle(chunks)

    system_prompt = template.system_prompt
    if template.few_shot_examples:
        system_prompt += "\n\n" + _format_few_shot_examples(template.few_shot_examples)

    context_blocks = "\n".join(f"{_chunk_tag(c)}{c.text}</chunk>" for c in reordered)
    user_prompt = f"Question: {question}\n\nDocument excerpts:\n{context_blocks}"

    return AssembledPrompt(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        chunk_ids_in_context=[c.chunk_id for c in reordered],
    )
