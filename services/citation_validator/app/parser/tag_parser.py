from __future__ import annotations

import re
from dataclasses import dataclass

_TAG_PATTERN = re.compile(r"\[([^\[\]\s]+)\]")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
# Matches the trailing structured citation list the system prompt asks
# for (docs/architecture.md §5: "Citations:\n[chunk_1] doc, page, section").
_TRAILING_CITATIONS_BLOCK_PATTERN = re.compile(r"\n\s*Citations:\s*\n.*", re.IGNORECASE | re.DOTALL)


@dataclass
class ParsedCitation:
    chunk_id: str
    sentence: str  # the sentence the tag appeared in, with the tag itself stripped out


def parse_citations(answer_text: str) -> list[ParsedCitation]:
    """Splits the generated answer into sentences and extracts every
    [chunk_id] citation tag, per docs/architecture.md §5's inline citation
    format. Produces one ParsedCitation per (sentence, chunk_id) pair.

    The trailing structured citation list the system prompt asks the
    model to append is NOT itself a claim needing an entailment check —
    it's citation-resolution metadata (filename/page/section), not
    natural-language text grounded in the source chunk. Treating it as a
    claim is actively harmful, not just redundant: that line shares
    almost no words with the source chunk, so it always fails entailment
    — and because the validator stores one outcome per chunk_id, that
    failure can silently overwrite a well-supported inline citation's
    passing result, flipping a correct answer to stripped_unverified.
    So this block is stripped before parsing; only inline claims count.
    """
    body = _TRAILING_CITATIONS_BLOCK_PATTERN.sub("", answer_text).strip()
    sentences = _SENTENCE_SPLIT_PATTERN.split(body)
    results: list[ParsedCitation] = []
    for sentence in sentences:
        tags = _TAG_PATTERN.findall(sentence)
        if not tags:
            continue
        clean_sentence = _TAG_PATTERN.sub("", sentence).strip()
        for chunk_id in tags:
            results.append(ParsedCitation(chunk_id=chunk_id, sentence=clean_sentence))
    return results