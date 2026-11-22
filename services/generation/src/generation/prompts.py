"""Prompt registry (blueprint 11.5, 11.7): templates are files under `prompts/`, hashed with SHA-256."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from functools import cache
from html import escape

from lmqa_models.envfile import ROOT
from lmqa_models.rag import CANONICAL_REFUSAL, Source

PROMPTS = ROOT / "prompts"

ANSWER_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "answerable": {"type": "BOOLEAN"},
        "sentences": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "citations": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {"source": {"type": "STRING"}, "quote": {"type": "STRING"}},
                            "required": ["source", "quote"],
                        },
                    },
                },
                "required": ["text", "citations"],
            },
        },
    },
    "required": ["answerable", "sentences"],
    "propertyOrdering": ["answerable", "sentences"],
}

VERIFY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "verdicts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "claim": {"type": "INTEGER"},
                    "supported": {"type": "BOOLEAN"},
                    "reason": {"type": "STRING"},
                },
                "required": ["claim", "supported", "reason"],
            },
        }
    },
    "required": ["verdicts"],
}


QUERY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "corrected_question": {"type": "STRING"},
        "queries": {"type": "ARRAY", "items": {"type": "STRING"}},
        "keep_detail_note": {"type": "STRING"},
    },
    "required": ["corrected_question", "queries", "keep_detail_note"],
    "propertyOrdering": ["corrected_question", "queries", "keep_detail_note"],
}


RERANK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "scores": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"id": {"type": "STRING"}, "score": {"type": "INTEGER"}},
                "required": ["id", "score"],
                "propertyOrdering": ["id", "score"],
            },
        }
    },
    "required": ["scores"],
}


@dataclass(frozen=True)
class Turn:
    """One earlier exchange: the user's question and the released (verified) answer text."""

    question: str
    answer: str


@dataclass(frozen=True)
class PromptSet:
    answer_system: str
    verify_system: str
    query_system: str
    sha256: str  # of the answer, verify and query prompts (recorded with every query)
    versions: dict[str, int]
    rerank_system: str = ""  # chooses passages only; not part of `sha256`, so earlier answers keep their hash


@cache
def load_prompts() -> PromptSet:
    registry = tomllib.loads((PROMPTS / "registry.toml").read_text(encoding="utf-8"))
    answer = (PROMPTS / registry["answer"]["system"]).read_text(encoding="utf-8").strip()
    answer = answer.replace("{refusal}", CANONICAL_REFUSAL)
    if few_shot := registry["answer"].get("few_shot"):
        answer += "\n\n" + (PROMPTS / few_shot).read_text(encoding="utf-8").strip()
    verify = (PROMPTS / registry["verify"]["system"]).read_text(encoding="utf-8").strip()
    query = (PROMPTS / registry["query"]["system"]).read_text(encoding="utf-8").strip()
    digest = hashlib.sha256(f"{answer}\x00{verify}\x00{query}".encode()).hexdigest()
    rerank = (PROMPTS / registry["rerank"]["system"]).read_text(encoding="utf-8").strip()
    return PromptSet(answer, verify, query, digest, {k: int(v["version"]) for k, v in registry.items()}, rerank)


def _source_block(s: Source) -> str:
    attrs = f'id="{s.alias}" document="{escape(s.document_title)}"'
    if s.pages():
        attrs += f' pages="{s.pages()}"'
    if s.section:
        attrs += f' section="{escape(s.section)}"'
    body = s.text.replace("</source", "</ source")  # a document cannot close its own delimiter
    return f"<source {attrs}>\n{body}\n</source>"


def _conversation_block(history: list[Turn]) -> str:
    def clean(text: str, limit: int) -> str:
        text = " ".join(text.split()).replace("</conversation", "</ conversation")
        return text if len(text) <= limit else text[: limit - 1] + "…"

    lines = []
    for turn in history:
        lines.append(f"User: {clean(turn.question, 500)}")
        lines.append(f"Assistant: {clean(turn.answer, 900) or '(no verified answer)'}")
    return "<conversation>\n" + "\n".join(lines) + "\n</conversation>"


def reorder(items: list[Source]) -> list[Source]:
    """Most relevant at the start and the end, least relevant in the middle (blueprint 11.4 step 5)."""
    return items[0::2] + items[1::2][::-1]


def query_user_prompt(history: list[Turn], question: str) -> str:
    message = question.strip().replace("</conversation", "</ conversation")
    if not history:
        return f"Latest message: {message}"
    return f"{_conversation_block(history)}\n\nLatest message: {message}"


def answer_user_prompt(
    question: str,
    sources: list[Source],
    history: list[Turn] | None = None,
    standalone: str | None = None,
    detail_note: str = "",
) -> str:
    blocks = "\n".join(_source_block(s) for s in reorder(sources))
    parts = []
    if history:
        parts.append(_conversation_block(history))
    parts.append(f"<sources>\n{blocks}\n</sources>")
    asked = f"Question: {question.strip()}"
    if standalone and standalone.strip().lower() != question.strip().lower():
        asked += f"\n(Standalone form of the question: {standalone.strip()})"
    if note := " ".join(detail_note.split()).replace("</source", "</ source")[:300]:
        asked += f"\nNote from the search step: {note}"
    parts.append(asked)
    return "\n\n".join(parts)


def verify_user_prompt(claims: list[tuple[int, str, list[str]]], sources: dict[str, Source]) -> str:
    used = sorted({a for _, _, aliases in claims for a in aliases}, key=lambda a: int(a[1:]))
    blocks = "\n".join(_source_block(sources[a]) for a in used)
    lines = "\n".join(f"Claim {n} (cites {', '.join(aliases)}): {text}" for n, text, aliases in claims)
    return f"<sources>\n{blocks}\n</sources>\n\nClaims:\n{lines}"


def rerank_user_prompt(question: str, passages: list[str]) -> str:
    """Passages get request-local ids P1, P2, ...; a passage cannot close its own delimiter."""
    blocks = "\n".join(
        f'<passage id="P{i}">\n{p.replace("</passage", "</ passage")}\n</passage>' for i, p in enumerate(passages, 1)
    )
    q = " ".join(question.split()).replace("</passages", "</ passages")
    return f"Question: {q}\n\n<passages>\n{blocks}\n</passages>"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
