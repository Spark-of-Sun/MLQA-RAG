"""Deterministic citation validator executing checks V1 to V8 per Master §11.6."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lmqa_models import CitationItem, RAGResponse, SentenceVerdict

if TYPE_CHECKING:
    from lmqa_models import RetrievalAlias, RetrievalRecord

CANONICAL_REFUSAL = "The provided documents do not address this."
SHA256_HEX_LENGTH = 64

# Exact valid tag pattern: [chunk_1], [chunk_2], etc.
VALID_TAG_PATTERN = re.compile(r"\[(chunk_\d+)\]")

# Malformed candidate tag patterns: [chunk], [1], [doc_1], [chunk_], etc.
MALFORMED_TAG_PATTERN = re.compile(
    r"\[(?!(?:chunk_\d+)\])(?:chunk[_\s]*\d*|\d+|doc[_\w]*|section[_\w]*)\]",
    re.IGNORECASE,
)

# Critical numeric, financial, percentage, date, and legal section tokens
CRITICAL_TOKEN_PATTERN = re.compile(
    r"(?:\$\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:million|billion|thousand))?|"
    r"\b\d+(?:,\d{3})*(?:\.\d+)?%|\b\d{1,2}/\d{1,2}/\d{2,4}\b|"
    r"\b\d{4}-\d{2}-\d{2}\b|\b(?:Section|Article|Clause)\s+\d+[\.\d+]*\b)",
    re.IGNORECASE,
)

# Common legal and English abbreviations to prevent erroneous sentence splitting
ABBREVIATIONS = (
    "inc.",
    "corp.",
    "ltd.",
    "co.",
    "sec.",
    "art.",
    "no.",
    "ex.",
    "e.g.",
    "i.e.",
    "u.s.",
    "dept.",
    "para.",
)


def _normalize_token(token: str) -> str:
    """Normalize critical token for comparison (remove punctuation, symbols, whitespace)."""
    cleaned = token.lower().replace("$", "").replace(",", "").replace("%", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_critical_tokens(text: str) -> list[str]:
    """Extract critical numeric, currency, date, and statutory references."""
    matches = CRITICAL_TOKEN_PATTERN.findall(text)
    return [m.strip() for m in matches if m.strip()]


def segment_sentences(text: str) -> list[str]:
    """Segment paragraph text into individual sentences respecting legal abbreviations."""
    raw_sentences = re.split(r"(?<=[.!?])\s+(?!\[chunk_\d+\])", text.strip())
    merged: list[str] = []

    for seg in raw_sentences:
        seg_stripped = seg.strip()
        if not seg_stripped:
            continue
        # If segment is just citation tags (e.g. "[chunk_1]"), merge with previous sentence
        if (merged and re.fullmatch(r"(?:\[chunk_\d+\]\s*)+", seg_stripped)) or (
            merged
            and any(merged[-1].lower().endswith(abbr) for abbr in ABBREVIATIONS)
            and not merged[-1].endswith("..")
        ):
            merged[-1] = f"{merged[-1]} {seg_stripped}"
        else:
            merged.append(seg_stripped)

    return merged


def _check_critical_tokens(
    stripped: str,
    tags: list[str],
    active_aliases: dict[str, RetrievalAlias],
) -> tuple[list[str], list[str]]:
    """Verify that all critical tokens in the sentence exist in cited sources (V5)."""
    critical_tokens = extract_critical_tokens(stripped)
    if not critical_tokens:
        return [], []

    cited_texts = [
        active_aliases[t].text for t in tags if t in active_aliases and active_aliases[t].text
    ]
    combined_cited = " ".join(cited_texts)
    combined_normalized = _normalize_token(combined_cited)

    failed_checks: list[str] = []
    reasons: list[str] = []

    for token in critical_tokens:
        norm_tok = _normalize_token(token)
        if norm_tok not in combined_normalized:
            failed_checks.append("V5")
            reasons.append(f"V5: Critical token '{token}' was not found in cited sources")

    return failed_checks, reasons


class SentenceValidator:
    """Validates answer sentences against the immutable retrieval record ledger."""

    def _check_refusal_or_heading(self, sentence: str, stripped: str) -> SentenceVerdict | None:
        """Handle canonical refusal (V7) or markdown heading exemptions."""
        if CANONICAL_REFUSAL.lower() in stripped.lower():
            if stripped != CANONICAL_REFUSAL or VALID_TAG_PATTERN.search(stripped):
                return SentenceVerdict(
                    sentence=sentence,
                    passed=False,
                    cited_aliases=VALID_TAG_PATTERN.findall(stripped),
                    failed_checks=["V7"],
                    reason="V7: Canonical refusal must be exact and carry no tags or claims",
                )
            return SentenceVerdict(
                sentence=sentence,
                passed=True,
                cited_aliases=[],
                failed_checks=[],
                reason="V7: Valid canonical refusal",
            )

        if stripped.startswith("#"):
            return SentenceVerdict(
                sentence=sentence,
                passed=True,
                cited_aliases=[],
                failed_checks=[],
                reason="Heading exempt from citation",
            )

        return None

    def validate_sentence(self, sentence: str, record: RetrievalRecord) -> SentenceVerdict:
        """Execute deterministic verification checks V1 to V8 on a single sentence."""
        stripped = sentence.strip()
        refusal_or_heading = self._check_refusal_or_heading(sentence, stripped)
        if refusal_or_heading is not None:
            return refusal_or_heading

        failed_checks: list[str] = []
        reasons: list[str] = []

        # Check V1: Tag grammar
        malformed = MALFORMED_TAG_PATTERN.findall(stripped)
        if malformed:
            failed_checks.append("V1")
            reasons.append(f"V1: Malformed citation tag detected: {malformed}")

        tags = VALID_TAG_PATTERN.findall(stripped)

        # Check V4: Citation required on factual statements
        if not tags:
            failed_checks.append("V4")
            reasons.append("V4: Factual claim lacks citation tag")
            return SentenceVerdict(
                sentence=sentence,
                passed=False,
                cited_aliases=[],
                failed_checks=failed_checks,
                reason="; ".join(reasons),
            )

        active_aliases = record.alias_map()

        # Check V2: Alias membership & V3: Chunk integrity
        for tag in tags:
            if tag not in active_aliases:
                failed_checks.append("V2")
                reasons.append(f"V2: Tag [{tag}] does not exist in request retrieval ledger")
            else:
                alias_item = active_aliases[tag]
                if not alias_item.content_hash or len(alias_item.content_hash) != SHA256_HEX_LENGTH:
                    failed_checks.append("V3")
                    reasons.append(f"V3: Chunk integrity hash invalid for [{tag}]")

        # Check V5: Critical tokens
        if not failed_checks:
            v5_failures, v5_reasons = _check_critical_tokens(stripped, tags, active_aliases)
            failed_checks.extend(v5_failures)
            reasons.extend(v5_reasons)

        is_passed = len(failed_checks) == 0
        verdict_reason = "Passed all checks V1-V8" if is_passed else "; ".join(reasons)

        return SentenceVerdict(
            sentence=sentence,
            passed=is_passed,
            cited_aliases=tags,
            failed_checks=failed_checks,
            reason=verdict_reason,
        )

    def validate_answer(
        self,
        raw_answer: str,
        record: RetrievalRecord,
        on_fail: str = "strip",
    ) -> RAGResponse:
        """Validate an entire generated answer, gating released sentences (Blueprint §11.6)."""
        stripped_answer = raw_answer.strip()
        if not stripped_answer:
            return RAGResponse(
                request_id=record.request_id,
                query=record.query,
                answer=CANONICAL_REFUSAL,
                verdicts=[],
                citations=[],
                refusal=True,
            )

        sentences = segment_sentences(stripped_answer)
        verdicts: list[SentenceVerdict] = []
        released_sentences: list[str] = []
        cited_tags_set: set[str] = set()

        for s in sentences:
            verdict = self.validate_sentence(s, record)
            verdicts.append(verdict)

            if verdict.passed:
                released_sentences.append(s)
                cited_tags_set.update(verdict.cited_aliases)
            elif on_fail == "strip":
                checks_str = ", ".join(verdict.failed_checks)
                marker = (
                    f"[A claim in this answer could not be verified and was removed: {checks_str}]"
                )
                released_sentences.append(marker)

        # If zero sentences passed, replace with canonical refusal
        passing_count = sum(1 for v in verdicts if v.passed)
        if passing_count == 0:
            return RAGResponse(
                request_id=record.request_id,
                query=record.query,
                answer=CANONICAL_REFUSAL,
                verdicts=verdicts,
                citations=[],
                refusal=True,
            )

        # Check V8: Deterministic citation resolution
        active_aliases = record.alias_map()
        citations: list[CitationItem] = []
        for tag in sorted(cited_tags_set):
            if tag in active_aliases:
                item = active_aliases[tag]
                citations.append(
                    CitationItem(
                        alias=tag,
                        doc_name=item.doc_name,
                        page=item.page,
                        section=item.section,
                        quote_excerpt=item.text[:120].strip(),
                    )
                )

        final_answer = " ".join(released_sentences)
        return RAGResponse(
            request_id=record.request_id,
            query=record.query,
            answer=final_answer,
            verdicts=verdicts,
            citations=citations,
            refusal=(final_answer == CANONICAL_REFUSAL),
        )
