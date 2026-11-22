"""Citation validator (blueprint 11.6). Deterministic: the same input yields the same verdict on every run.

Per sentence of the model's draft:
  V7 refusal            the refusal uses the exact canonical wording, alone, with no citation; or a scoped
                        refusal naming one detail the documents do not address ("The provided documents do not
                        address <detail>."): one plain clause, no citation, no commas or linking words, so it
                        cannot carry a claim
  V4 citation required  every other sentence cites at least one source
  V1 tag grammar        every cited id matches S<n>
  V2 alias membership   every cited id is in this request's retrieval ledger
  V3 chunk integrity    the chunk text still hashes to the ledger hash (re-checked against the database at release)
  Q  quote match        each citation's quote occurs in the cited chunk (whitespace, case, quotes, dashes
                        normalized); the matched span is the highlight shown in the citation panel
  V5 critical tokens    every number in the sentence (amounts, dates, dosages, section numbers) occurs in the
                        cited chunks after normalization
  L  lexical support    at least half of the sentence's key terms occur in the cited chunks (light stemming;
                        words that describe the document, such as "contains" or "explains", are not key terms).
                        With entailment on, a paraphrase between 25% and 50% is passed to V6 to judge its meaning
                        instead of being removed; below 25% it is removed either way.
  V8 resolution         each citation resolves to a document, pages, section and a highlighted span
  V6 entailment         applied afterwards from the generation service's check; it can only remove sentences

The citation list is built here from validated sentences, never by the model (DEF-35).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from lmqa_models.rag import CANONICAL_REFUSAL, Source

ALIAS = re.compile(r"^S([1-9]\d?)$")
_SCOPED_REFUSAL = re.compile(r"^The provided documents do not address [^.,;:!?()\[\]\n]{3,140}\.$")
_SCOPED_LINKS = re.compile(r"\b(?:but|however|although|though|because|since|instead|whereas|while|yet|so|is)\b")
_INLINE_TAG = re.compile(r"\s*[\[(](?:S\d+(?:\s*[,;]\s*S\d+)*)[\])]")
_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[a-z][a-z'-]{3,}")
_ESCAPE = re.compile(r"\\[ntrfv]")  # literal \n, \t ... in code and data files
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_SUFFIXES = (
    "izations",
    "ization",
    "ations",
    "ation",
    "ments",
    "ment",
    "ings",
    "ing",
    "ies",
    "ied",
    "ers",
    "er",
    "ed",
    "es",
    "s",
    "ly",
)
LEXICAL_MIN = 0.5  # below this share of key terms, the wording is not supported
LEXICAL_FLOOR = 0.25  # below this, removed even when entailment would judge it
# Words that describe the document or the answer rather than state a fact from it.
_META = frozenset(
    [
        "contain",
        "contains",
        "contained",
        "containing",
        "include",
        "includes",
        "included",
        "including",
        "describe",
        "describes",
        "described",
        "describing",
        "discuss",
        "discusses",
        "discussed",
        "discussing",
        "mention",
        "mentions",
        "mentioned",
        "mentioning",
        "explain",
        "explains",
        "explained",
        "explaining",
        "show",
        "shows",
        "showed",
        "shown",
        "showing",
        "demonstrate",
        "demonstrates",
        "demonstrated",
        "demonstrating",
        "illustrate",
        "illustrates",
        "illustrated",
        "provide",
        "provides",
        "providing",
        "outline",
        "outlines",
        "outlined",
        "perform",
        "performs",
        "performed",
        "performing",
        "use",
        "uses",
        "used",
        "using",
        "utilize",
        "utilizes",
        "utilized",
        "utilizing",
        "employ",
        "employs",
        "employed",
        "file",
        "files",
        "text",
        "texts",
        "code",
        "codes",
        "script",
        "scripts",
        "snippet",
        "snippets",
        "example",
        "examples",
        "part",
        "parts",
        "section",
        "sections",
        "page",
        "pages",
        "content",
        "contents",
        "discussion",
        "overview",
        "details",
        "detail",
        "various",
        "several",
        "following",
        "specifically",
        "particular",
        "called",
        "named",
    ]
)
_STOP = frozenset(
    [
        "also",
        "among",
        "another",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "does",
        "done",
        "each",
        "either",
        "from",
        "further",
        "have",
        "having",
        "here",
        "into",
        "itself",
        "just",
        "more",
        "most",
        "must",
        "other",
        "over",
        "same",
        "shall",
        "should",
        "some",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "until",
        "upon",
        "very",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "whom",
        "will",
        "with",
        "within",
        "without",
        "would",
        "your",
        "about",
        "above",
        "after",
        "again",
        "against",
        "below",
        "could",
        "during",
        "only",
        "own",
        "provided",
        "documents",
        "document",
        "source",
        "sources",
        "states",
        "stated",
        "according",
    ]
)

LABELS = {
    "V1": "Citation format",
    "V2": "Source was retrieved for this question",
    "V3": "Source unchanged since retrieval",
    "V4": "Sentence is cited",
    "Q": "Quoted text found in source",
    "V5": "Numbers and dates match the source",
    "L": "Wording supported by the source",
    "V6": "Source entails the claim",
    "V7": "Refusal wording",
    "V8": "Citation resolves to a page and section",
}


@dataclass
class Check:
    code: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "label": LABELS[self.code], "ok": self.ok, "detail": self.detail}


@dataclass
class Verdict:
    index: int
    text: str
    aliases: list[str] = field(default_factory=list)
    refusal: bool = False
    checks: list[Check] = field(default_factory=list)
    spans: dict[str, list[tuple[int, int]]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def fail(self, code: str, detail: str) -> None:
        self.checks.append(Check(code, False, detail))

    def passed(self, code: str, detail: str = "") -> None:
        self.checks.append(Check(code, True, detail))

    @property
    def first_failure(self) -> str:
        return next((c.detail or LABELS[c.code] for c in self.checks if not c.ok), "")


# ---------------------------------------------------------------------------- normalization
_CHAR_MAP = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u2032": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2033": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u00a0": " ",
    "\u2009": " ",
    "\u202f": " ",
}
_TRANSLATE = str.maketrans(_CHAR_MAP)


def _normalize_with_map(text: str, *, alnum_only: bool) -> tuple[str, list[int]]:
    """Normalized text plus, for each output character, its index in the original text."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        c = _CHAR_MAP.get(ch, ch).lower()
        if alnum_only and not c.isalnum():
            c = " "
        if c.isspace():
            if prev_space:
                continue
            c = " "
            prev_space = True
        else:
            prev_space = False
        out.append(c)
        index.append(i)
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def find_quote(quote: str, text: str) -> tuple[int, int] | None:
    """Locate a quote in source text; return its (start, end) span in the original text."""
    for alnum_only in (False, True):
        q, _ = _normalize_with_map(quote, alnum_only=alnum_only)
        q = q.strip(" .,;:'\"")
        if len(q) < 8:
            return None
        t, idx = _normalize_with_map(text, alnum_only=alnum_only)
        pos = t.find(q)
        if pos >= 0:
            return idx[pos], idx[pos + len(q) - 1] + 1
    # Near-verbatim: one contiguous block covering at least 90% of the quote.
    q, _ = _normalize_with_map(quote, alnum_only=True)
    t, idx = _normalize_with_map(text, alnum_only=True)
    if len(q) < 20:
        return None
    m = SequenceMatcher(None, t, q, autojunk=False).find_longest_match(0, len(t), 0, len(q))
    if m.size >= 0.9 * len(q):
        return idx[m.a], idx[m.a + m.size - 1] + 1
    return None


def numbers(text: str) -> set[str]:
    found: set[str] = set()
    for raw in _NUMBER.findall(text):
        value = raw.replace(",", "")
        if value.isdigit():
            value = str(int(value))
        elif "." in value:
            value = value.rstrip("0").rstrip(".")
        found.add(value)
    return found


def _stem(word: str) -> str:
    """Crude, deterministic stemming: 'trains', 'training', 'trained' -> 'train'; then the first 6 letters."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    return word[:6]


def content_words(text: str) -> set[str]:
    """Key terms of a text. Splits identifiers (camelCase, snake_case, word2vec) so code and data match prose."""
    text = _CAMEL.sub(" ", _ESCAPE.sub(" ", text.translate(_TRANSLATE)))
    text = re.sub(r"[_\d]+", " ", text).lower()
    words = (w.strip("'-") for w in _WORD.findall(text))
    return {_stem(w) for w in words if w not in _STOP and w not in _META and len(w) >= 4}


def clean_sentence(text: str) -> str:
    return " ".join(_INLINE_TAG.sub("", text).split())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------- validation
def validate(
    draft: dict[str, Any], ledger: dict[str, Source], *, entailment: bool = False
) -> tuple[bool, list[Verdict]]:
    """Check a model draft against the ledger. Returns (answerable flag, verdict per sentence).

    `entailment` says V6 will run afterwards; then a paraphrase with moderate wording overlap is left for V6 to
    judge on meaning, rather than removed on wording alone."""
    answerable = bool(draft.get("answerable"))
    raw_sentences = draft.get("sentences")
    verdicts: list[Verdict] = []
    for i, raw in enumerate(raw_sentences if isinstance(raw_sentences, list) else []):
        if not isinstance(raw, dict):
            continue
        text = clean_sentence(str(raw.get("text", "")))
        if not text:
            continue
        cites = [c for c in raw.get("citations") or [] if isinstance(c, dict)]
        aliases = [str(c.get("source", "")).strip() for c in cites]
        v = Verdict(index=i, text=text)
        verdicts.append(v)

        detail = text.removeprefix("The provided documents do not address ").lower()
        if text != CANONICAL_REFUSAL and _SCOPED_REFUSAL.match(text) and not _SCOPED_LINKS.search(detail):  # V7
            v.refusal = True
            if cites:
                v.fail("V7", "A refusal must not cite a source")
            else:
                v.passed("V7")
            continue

        if CANONICAL_REFUSAL.lower().rstrip(".") in text.lower():  # V7
            v.refusal = True
            if text == CANONICAL_REFUSAL and not cites:
                v.passed("V7")
            else:
                v.fail("V7", "Refusal combined with another claim or a citation")
            continue

        if not cites:  # V4
            v.fail("V4", "Sentence has no citation")
            continue
        v.passed("V4")

        bad = [a for a in aliases if not ALIAS.match(a)]  # V1
        if bad:
            v.fail("V1", f"Malformed citation id {bad[0]!r}")
            continue
        v.passed("V1")

        unknown = [a for a in aliases if a not in ledger]  # V2
        if unknown:
            v.fail("V2", f"Cites {unknown[0]}, which was not retrieved for this question")
            continue
        v.passed("V2")
        v.aliases = list(dict.fromkeys(aliases))

        changed = [a for a in v.aliases if sha256_text(ledger[a].text) != ledger[a].sha256]  # V3
        if changed:
            v.fail("V3", f"Source {changed[0]} changed after retrieval")
            continue
        v.passed("V3")

        missing: list[str] = []  # Q
        for cite in cites:
            alias = str(cite.get("source", "")).strip()
            span = find_quote(str(cite.get("quote", "")), ledger[alias].text)
            if span is None:
                missing.append(alias)
            else:
                v.spans.setdefault(alias, []).append(span)
        if missing:
            v.fail("Q", f"Quoted text not found in {missing[0]}")
            continue
        v.passed("Q")

        cited_text = "\n".join(ledger[a].text for a in v.aliases)
        absent = sorted(numbers(text) - numbers(cited_text))  # V5
        if absent:
            v.fail("V5", f"Number {absent[0]} does not appear in the cited source")
            continue
        v.passed("V5")

        words = content_words(text)  # L
        share = len(words & content_words(cited_text)) / len(words) if words else 1.0
        if share >= LEXICAL_MIN:
            v.passed("L")
        elif entailment and share >= LEXICAL_FLOOR:
            v.passed("L", f"Paraphrased: {share:.0%} of the key terms match; meaning checked by entailment (V6)")
        else:
            v.fail("L", f"Only {share:.0%} of the sentence's key terms appear in the cited source")
            continue

        unresolved = [a for a in v.aliases if not ledger[a].document_title or a not in v.spans]  # V8
        if unresolved:
            v.fail("V8", f"Citation {unresolved[0]} does not resolve")
            continue
        v.passed("V8")
    return answerable, verdicts


def entailment_claims(verdicts: list[Verdict]) -> list[tuple[int, str, list[str]]]:
    """Claims for V6: only sentences that passed every deterministic check, numbered from 1."""
    return [(n, v.text, v.aliases) for n, v in enumerate((v for v in verdicts if v.ok and not v.refusal), start=1)]


def apply_entailment(verdicts: list[Verdict], results: dict[int, tuple[bool, str]]) -> None:
    for n, v in enumerate((v for v in verdicts if v.ok and not v.refusal), start=1):
        supported, reason = results.get(n, (False, "No entailment verdict was returned"))
        if supported:
            v.passed("V6", reason)
        else:
            v.fail("V6", f"Not supported by the source: {reason}" if reason else "Not supported by the source")


def recheck_integrity(verdicts: list[Verdict], ledger: dict[str, Source], current: dict[str, str]) -> None:
    """V3 at release: `current` maps chunk_id -> sha256 re-read under RLS immediately before release."""
    for v in verdicts:
        if v.ok and not v.refusal:
            for alias in v.aliases:
                if current.get(ledger[alias].chunk_id) != ledger[alias].sha256:
                    v.fail("V3", f"Source {alias} was changed or is no longer visible")
                    break


def build_result(answerable: bool, verdicts: list[Verdict], ledger: dict[str, Source]) -> dict[str, Any]:
    """The released answer: verified sentences, visible markers for removed ones, deterministic citations."""
    numbers_by_alias: dict[str, int] = {}
    highlights: dict[str, set[tuple[int, int]]] = {}
    segments: list[dict[str, Any]] = []
    for v in verdicts:
        checks = [c.as_dict() for c in v.checks]
        if v.refusal and v.ok:
            segments.append({"type": "refusal", "text": v.text})  # the canonical or a scoped refusal
        elif v.ok:
            for alias in v.aliases:
                numbers_by_alias.setdefault(alias, len(numbers_by_alias) + 1)
                highlights.setdefault(alias, set()).update(v.spans.get(alias, []))
            segments.append(
                {
                    "type": "sentence",
                    "text": v.text,
                    "citations": [numbers_by_alias[a] for a in v.aliases],
                    "checks": checks,
                }
            )
        else:
            segments.append({"type": "removed", "reason": v.first_failure, "checks": checks})
    verified = sum(1 for s in segments if s["type"] == "sentence")
    removed = sum(1 for s in segments if s["type"] == "removed")
    if verified == 0:  # V7: every content sentence failed -> canonical refusal
        outcome = "refused"
        segments = [{"type": "refusal", "text": CANONICAL_REFUSAL}] + [s for s in segments if s["type"] == "removed"]
    elif removed or any(s["type"] == "refusal" for s in segments):
        outcome = "partial"
    else:
        outcome = "answered"
    citations = [
        {
            "n": n,
            "chunk_id": ledger[a].chunk_id,
            "chunk_sha256": ledger[a].sha256,
            "document_id": ledger[a].document_id,
            "document_title": ledger[a].document_title,
            "section": ledger[a].section,
            "page_start": ledger[a].page_start,
            "page_end": ledger[a].page_end,
            "highlights": [list(s) for s in sorted(highlights.get(a, set()))],
        }
        for a, n in numbers_by_alias.items()
    ]
    return {
        "outcome": outcome,
        "answerable": answerable,
        "segments": segments,
        "citations": citations,
        "stats": {"verified": verified, "removed": removed},
    }
