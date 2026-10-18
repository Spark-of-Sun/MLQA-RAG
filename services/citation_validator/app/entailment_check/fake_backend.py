from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD_PATTERN.findall(text.lower()))


class WordOverlapEntailmentChecker:
    """Deterministic, dependency-free entailment stand-in for local unit
    tests and offline dev: scores support as the fraction of the claim's
    words that also appear in the chunk text. This is a much cruder check
    than a real NLI model (it has no notion of negation or paraphrase),
    but it's fast, has zero dependencies, and is strict enough to reliably
    catch a citation pointing at an unrelated chunk — the main failure
    mode this gate exists to catch. Never used in the Docker image — see
    CrossEncoderEntailmentChecker for the real model.
    """

    def score(self, claim_sentence: str, chunk_text: str) -> float:
        claim_tokens = _tokenize(claim_sentence)
        if not claim_tokens:
            return 1.0  # an empty claim (e.g. just a bare citation tag) is trivially "supported"
        chunk_tokens = _tokenize(chunk_text)
        overlap = claim_tokens & chunk_tokens
        return len(overlap) / len(claim_tokens)
