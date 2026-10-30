"""The eight deterministic validator checks (doc 11.6). No generative model is involved.

Order, cheapest and most decisive first; the first failure stops the sentence:

V1 tag grammar            tags match ``[chunk_N]`` exactly; anything tag-like but malformed fails
V7 refusal consistency    the canonical refusal is exact, untagged, and says nothing else
V4 citation required      every sentence except headings and the canonical refusal carries a tag
V2 alias membership       every alias exists in this request's retrieval ledger
V3 chunk integrity        the chunk's current content hash equals the ledger hash
V5 critical tokens        numbers, dates, amounts, dosages and references appear in the cited text
V6 entailment             a pinned NLI model scores the sentence against the cited windows
V8 resolution             each tag resolves to document, pages, section and a highlighted span

The result for the same input is the same on every run and after every restart: V1-V5, V7 and V8
are pure functions, and V6 uses a pinned model on CPU with fixed thresholds.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol

from citation_validator.critical import missing_tokens
from citation_validator.segmenter import split

if TYPE_CHECKING:
    from collections.abc import Mapping

CANONICAL_REFUSAL: Final = "The provided documents do not address this."
_TAG: Final = re.compile(r"\[chunk_([1-9]\d*)\]")
_TAG_LIKE: Final = re.compile(r"\[\s*chunk[^\]]*\]", re.IGNORECASE)
_WORDS: Final = re.compile(r"[a-z0-9]+")
CHECK_ORDER: Final = ("V1", "V7", "V4", "V2", "V3", "V5", "V6", "V8")
WINDOW_SENTENCES: Final = 3
MAX_WINDOWS: Final = 2
PREMISE_WORD_LIMIT: Final = 320


class NliScorer(Protocol):
    """A pinned entailment model: probability that the premise entails the hypothesis."""

    model_id: str

    def entailment(self, premise: str, hypothesis: str) -> float:
        """Return a probability in [0, 1]."""
        ...


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One retrieved chunk as recorded by retrieval: the alias and the hash it must still match."""

    alias: str
    chunk_id: str
    version: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ChunkView:
    """The chunk as it is now in PostgreSQL (decrypted under RLS) plus its citation metadata."""

    alias: str
    text: str
    doc_title: str
    doc_version: int
    page_start: int
    page_end: int
    section_path: str
    clause_no: str | None


@dataclass(frozen=True, slots=True)
class Citation:
    """V8: a tag resolved to something a lawyer or clinician can verify."""

    alias: str
    doc_title: str
    doc_version: int
    page_start: int
    page_end: int
    section_path: str
    clause_no: str | None
    span_start: int
    span_end: int


@dataclass(slots=True)
class SentenceCheck:
    """The outcome for one sentence."""

    passed: bool
    checks: dict[str, bool] = field(default_factory=dict[str, bool])
    failed: str | None = None
    detail: str | None = None
    aliases: list[str] = field(default_factory=list[str])
    citations: list[Citation] = field(default_factory=list[Citation])
    refusal: bool = False
    entailment: float | None = None


def strip_tags(sentence: str) -> str:
    """The sentence with citation tags removed (what the entailment model judges)."""
    return " ".join(_TAG.sub("", sentence).split())


def sha256_hex(text: str) -> str:
    """SHA-256 of UTF-8 text."""
    return hashlib.sha256(text.encode()).hexdigest()


def is_heading(sentence: str) -> bool:
    """A markdown-style heading carries no factual claim."""
    return sentence.lstrip().startswith("#")


def _words(text: str) -> set[str]:
    return set(_WORDS.findall(text.lower()))


def relevant_windows(chunk_text: str, hypothesis: str) -> list[tuple[int, int]]:
    """Character ranges of the chunk windows most relevant to ``hypothesis`` (deterministic).

    Windows are runs of up to three sentences; relevance is word-set Jaccard overlap with the
    hypothesis, ties broken by position, so the same input always selects the same windows.
    """
    sentences, _ = split(chunk_text, final=True)
    spans: list[tuple[int, int]] = []
    cursor = 0
    for s in sentences:
        start = chunk_text.find(s, cursor)
        spans.append((start, start + len(s)))
        cursor = start + len(s)
    if not spans:
        return [(0, len(chunk_text))]
    target = _words(hypothesis)
    scored: list[tuple[float, int, int, int]] = []
    for i in range(len(spans)):
        lo, hi = spans[i][0], spans[min(i + WINDOW_SENTENCES, len(spans)) - 1][1]
        w = _words(chunk_text[lo:hi])
        overlap = len(w & target) / (len(w | target) or 1)
        scored.append((-overlap, i, lo, hi))
    scored.sort()
    return sorted({(lo, hi) for _, _, lo, hi in scored[:MAX_WINDOWS]})


def evaluate_sentence(  # noqa: C901, PLR0911 - eight ordered checks, each may stop the sentence
    sentence: str,
    ledger: Mapping[str, LedgerEntry],
    chunks: Mapping[str, ChunkView | None],
    scorer: NliScorer,
    threshold: float,
) -> SentenceCheck:
    """Run V1 to V8 on one sentence. The first failure stops the sentence and is reported."""
    out = SentenceCheck(passed=False)

    def fail(check: str, detail: str) -> SentenceCheck:
        out.checks[check] = False
        out.failed, out.detail = check, detail
        return out

    text = sentence.strip()
    tags = _TAG.findall(text)
    out.aliases = [f"chunk_{n}" for n in dict.fromkeys(tags)]
    leftover = _TAG_LIKE.sub(lambda m: "" if _TAG.fullmatch(m.group(0)) else m.group(0), text)
    if _TAG_LIKE.search(leftover):
        return fail("V1", "malformed citation tag")
    out.checks["V1"] = True

    body = strip_tags(text)
    if CANONICAL_REFUSAL.lower() in body.lower():
        if text != CANONICAL_REFUSAL:
            return fail(
                "V7",
                "a refusal must be the exact canonical sentence with no tag and no other claim",
            )
        out.checks["V7"] = out.refusal = out.passed = True
        return out
    out.checks["V7"] = True

    if is_heading(text):
        out.passed = True
        return out
    if not tags:
        return fail("V4", "a factual sentence has no citation")
    out.checks["V4"] = True

    unknown = [a for a in out.aliases if a not in ledger]
    if unknown:
        return fail("V2", f"alias not in this request's ledger: {unknown}")
    out.checks["V2"] = True

    views: list[ChunkView] = []
    for alias in out.aliases:
        view = chunks.get(alias)
        if view is None or sha256_hex(view.text) != ledger[alias].sha256:
            return fail("V3", f"{alias} changed or is no longer readable since retrieval")
        views.append(view)
    out.checks["V3"] = True

    lacking = missing_tokens(body, [v.text for v in views])
    if lacking:
        return fail("V5", f"not in the cited text: {sorted(lacking)}")
    out.checks["V5"] = True

    windows = {v.alias: relevant_windows(v.text, body) for v in views}
    premise = " ".join(v.text[lo:hi] for v in views for lo, hi in windows[v.alias])
    premise = " ".join(premise.split()[:PREMISE_WORD_LIMIT])
    out.entailment = scorer.entailment(premise, body)
    if out.entailment < threshold:
        return fail("V6", f"entailment {out.entailment:.3f} is below {threshold}")
    out.checks["V6"] = True

    for v in views:
        lo, hi = windows[v.alias][0]
        out.citations.append(
            Citation(
                v.alias,
                v.doc_title,
                v.doc_version,
                v.page_start,
                v.page_end,
                v.section_path,
                v.clause_no,
                lo,
                hi,
            )
        )
    out.checks["V8"] = True
    out.passed = True
    return out
