"""Prompt assembly and the prompt registry (doc 11.5, 10.9).

* The model sees **request-local aliases** (``chunk_1`` ...) and never a global chunk ID, so it
  cannot cite an identifier it recalls from anywhere else.
* Chunks are delimited blocks with an explicit instruction hierarchy in the system prompt. Text is
  escaped so a chunk cannot close its own block or open a fake one (``<`` becomes ``&lt;``); the
  validator always checks against the ORIGINAL text, never the escaped text.
* Every prompt version has a content hash recorded in the audit payload of every query, and the
  registry refuses a template whose bytes no longer match the recorded hash.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from generation.budget import (
    DEFAULT_CONTEXT_BUDGET,
    DEFAULT_MAX_OUTPUT,
    Candidate,
    TokenCounter,
    fit,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

MAX_QUESTION_CHARS: Final = 2_000
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PromptIntegrityError(RuntimeError):
    """A prompt file does not match the hash recorded in the registry."""


@dataclass(frozen=True, slots=True)
class ChunkInfo:
    """A retrieved chunk with the metadata the model needs to cite it."""

    alias: str
    text: str
    rank: int
    doc_title: str
    page_start: int
    page_end: int
    section: str


@dataclass(frozen=True, slots=True)
class Assembled:
    """The final prompt plus everything audit records about it."""

    system: str
    user: str
    prompt_version: str
    prompt_hash: str
    kept: tuple[str, ...]
    dropped: tuple[dict[str, object], ...]
    estimated_tokens: int


def _attr(value: str) -> str:
    """Make a value safe inside a double-quoted attribute."""
    return (
        re.sub(r"[\x00-\x1f]", " ", value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def escape_chunk_text(text: str) -> str:
    """Neutralize markup so chunk text cannot terminate or forge a block."""
    return text.replace("&", "&amp;").replace("<", "&lt;")


def chunk_block(info: ChunkInfo) -> tuple[str, str]:
    """Return ``(opening tag, full block)``; the opening tag is the fixed overhead."""
    pages = (
        str(info.page_start)
        if info.page_start == info.page_end
        else f"{info.page_start}-{info.page_end}"
    )
    doc, section = _attr(info.doc_title), _attr(info.section)
    opening = f'<chunk alias="{info.alias}" doc="{doc}" page="{pages}" section="{section}">'
    return opening, f"{opening}\n{escape_chunk_text(info.text)}\n</chunk>"


def clean_question(question: str) -> str:
    """Strip control characters and cap the length of the user's question."""
    return " ".join(_CONTROL.sub(" ", question).split())[:MAX_QUESTION_CHARS]


def prompt_hash(system: str, few_shot: str) -> str:
    """The content hash of a prompt version (system prompt plus few-shot examples)."""
    return hashlib.sha256((system + "\n--\n" + few_shot).encode()).hexdigest()


class PromptRegistry:
    """Loads versioned templates and verifies each against ``registry.toml``."""

    def __init__(self, root: Path) -> None:
        """``root`` is the repository's ``prompts`` directory."""
        self._root = root
        self._entries = {
            (e["name"], e["version"]): e
            for e in tomllib.loads((root / "registry.toml").read_text(encoding="utf-8"))["prompt"]
        }

    def load(self, name: str, version: str) -> tuple[str, str, str]:
        """Return ``(system, few_shot, sha256)`` after verifying the recorded hash."""
        entry = self._entries[(name, version)]
        system = (self._root / entry["system_file"]).read_text(encoding="utf-8")
        few_shot = (self._root / entry["few_shot_file"]).read_text(encoding="utf-8")
        actual = prompt_hash(system, few_shot)
        if actual != entry["sha256"]:
            msg = f"prompt {name}/{version} does not match its recorded hash"
            raise PromptIntegrityError(msg)
        return system, few_shot, actual


def assemble(  # noqa: PLR0913, PLR0917 - the prompt, the question, the chunks and the budget
    counter: TokenCounter,
    system: str,
    few_shot: str,
    version: str,
    question: str,
    chunks: Sequence[ChunkInfo],
    *,
    budget: int = DEFAULT_CONTEXT_BUDGET,
    max_output: int = DEFAULT_MAX_OUTPUT,
) -> Assembled:
    """Build the system and user messages within the hard token budget."""
    question = clean_question(question)
    blocks = {c.alias: chunk_block(c) for c in chunks}
    fixed = f"{system}\n{few_shot}\nQuestion: {question}"
    fitted = fit(
        counter,
        fixed,
        [Candidate(c.alias, blocks[c.alias][1], c.rank, "") for c in chunks],
        budget=budget,
        max_output=max_output,
    )
    body = "\n\n".join(blocks[c.alias][1] for c in fitted.kept)
    user = (
        f"Examples of the required format:\n{few_shot}\n\nChunks:\n{body}\n\nQuestion: {question}"
    )
    return Assembled(
        system=system,
        user=user,
        prompt_version=version,
        prompt_hash=prompt_hash(system, few_shot),
        kept=tuple(c.alias for c in fitted.kept),
        dropped=tuple(fitted.dropped),
        estimated_tokens=fitted.tokens,
    )
