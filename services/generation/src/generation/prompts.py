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


@dataclass(frozen=True)
class PromptSet:
    answer_system: str
    verify_system: str
    sha256: str
    versions: dict[str, int]


@cache
def load_prompts() -> PromptSet:
    registry = tomllib.loads((PROMPTS / "registry.toml").read_text(encoding="utf-8"))
    answer = (PROMPTS / registry["answer"]["system"]).read_text(encoding="utf-8").strip()
    answer = answer.replace("{refusal}", CANONICAL_REFUSAL)
    if few_shot := registry["answer"].get("few_shot"):
        answer += "\n\n" + (PROMPTS / few_shot).read_text(encoding="utf-8").strip()
    verify = (PROMPTS / registry["verify"]["system"]).read_text(encoding="utf-8").strip()
    digest = hashlib.sha256(f"{answer}\x00{verify}".encode()).hexdigest()
    return PromptSet(answer, verify, digest, {k: int(v["version"]) for k, v in registry.items()})


def _source_block(s: Source) -> str:
    attrs = f'id="{s.alias}" document="{escape(s.document_title)}"'
    if s.pages():
        attrs += f' pages="{s.pages()}"'
    if s.section:
        attrs += f' section="{escape(s.section)}"'
    body = s.text.replace("</source", "</ source")  # a document cannot close its own delimiter
    return f"<source {attrs}>\n{body}\n</source>"


def reorder(items: list[Source]) -> list[Source]:
    """Most relevant at the start and the end, least relevant in the middle (blueprint 11.4 step 5)."""
    return items[0::2] + items[1::2][::-1]


def answer_user_prompt(question: str, sources: list[Source]) -> str:
    blocks = "\n".join(_source_block(s) for s in reorder(sources))
    return f"<sources>\n{blocks}\n</sources>\n\nQuestion: {question.strip()}"


def verify_user_prompt(claims: list[tuple[int, str, list[str]]], sources: dict[str, Source]) -> str:
    used = sorted({a for _, _, aliases in claims for a in aliases}, key=lambda a: int(a[1:]))
    blocks = "\n".join(_source_block(sources[a]) for a in used)
    lines = "\n".join(f"Claim {n} (cites {', '.join(aliases)}): {text}" for n, text, aliases in claims)
    return f"<sources>\n{blocks}\n</sources>\n\nClaims:\n{lines}"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
