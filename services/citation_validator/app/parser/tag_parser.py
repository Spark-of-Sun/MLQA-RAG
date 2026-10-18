from __future__ import annotations

import re
from dataclasses import dataclass

_TAG_PATTERN = re.compile(r"\[([^\[\]\s]+)\]")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ParsedCitation:
    chunk_id: str
    sentence: str  # the sentence the tag appeared in, with the tag itself stripped out


def parse_citations(answer_text: str) -> list[ParsedCitation]:
    """Splits the generated answer into sentences and extracts every
    [chunk_id] citation tag, per docs/architecture.md §5's inline citation
    format. Produces one ParsedCitation per (sentence, chunk_id) pair — a
    sentence citing two chunks produces two entries, each checked
    independently downstream in app/validator.py.

    Known limitation: the trailing structured citation list
    ("Citations:\\n[chunk_1] doc, page, section...") is parsed the same
    way as an inline claim, producing a redundant extra finding for
    chunks already validated inline. Harmless (same chunk, same check
    result) but not deduplicated here — a TODO if findings volume ever
    matters for the audit view.
    """
    sentences = _SENTENCE_SPLIT_PATTERN.split(answer_text.strip())
    results: list[ParsedCitation] = []
    for sentence in sentences:
        tags = _TAG_PATTERN.findall(sentence)
        if not tags:
            continue
        clean_sentence = _TAG_PATTERN.sub("", sentence).strip()
        for chunk_id in tags:
            results.append(ParsedCitation(chunk_id=chunk_id, sentence=clean_sentence))
    return results
