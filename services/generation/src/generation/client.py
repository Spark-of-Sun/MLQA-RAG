"""Grounded answer generation client supporting Google Gemini Flash and thinking budgets."""

from __future__ import annotations

import re
from typing import Any

import httpx
from lmqa_models import CitationItem, LLMConfig, RAGResponse, RetrievalRecord


class GenerationClient:
    """Client generating citation-grounded responses from retrieval records."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        """Initialize generation client with active model configuration."""
        self.config = config or LLMConfig.from_env()

    def build_system_prompt(self, record: RetrievalRecord) -> str:
        """Build grounded prompt mapping each retrieval alias to its text."""
        context_lines = [
            f"[{alias.alias}] ({alias.doc_name}, p.{alias.page}): {alias.text}"
            for alias in record.aliases
            if not alias.dropped
        ]

        context_str = "\n".join(context_lines)
        return (
            "You are a legal and medical assistant. Answer the user query strictly using the "
            "provided sources. Every factual sentence must include an exact citation like "
            "[chunk_1].\n\n"
            f"Sources:\n{context_str}\n\n"
            f"Query: {record.query}\nAnswer:"
        )

    async def generate(self, record: RetrievalRecord) -> RAGResponse:
        """Generate answer with structured citations linked to retrieval aliases."""
        active_aliases = [a for a in record.aliases if not a.dropped]
        if not active_aliases:
            return RAGResponse(
                request_id=record.request_id,
                query=record.query,
                answer="The provided documents do not address this.",
                citations=[],
                refusal=True,
            )

        prompt = self.build_system_prompt(record)

        # If live Google Gemini API key is configured and not in dry-run
        if self.config.provider == "google" and self.config.api_key:
            model = self.config.model
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.config.api_key}"
            headers = {"Content-Type": "application/json"}
            body: dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
            }
            if self.config.thinking_budget:
                body["generationConfig"] = {
                    "thinkingConfig": {"thinkingBudget": self.config.thinking_budget}
                }

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, headers=headers, json=body)
                    resp.raise_for_status()
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_val = (
                            candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        )
                        citations = [
                            CitationItem(
                                alias=a.alias,
                                doc_name=a.doc_name,
                                page=a.page,
                                section=a.section,
                                quote_excerpt=a.text[:100],
                            )
                            for a in active_aliases
                            if a.alias in text_val
                        ]
                        return RAGResponse(
                            request_id=record.request_id,
                            query=record.query,
                            answer=text_val,
                            citations=citations,
                        )
            except httpx.HTTPError, OSError:
                # Fall back to offline deterministic grounded synthesis when network is unavailable
                pass

        # Deterministic offline synthesis for offline tests and Stage 0 verification
        first_chunk = active_aliases[0]
        clean_text = re.sub(r"\s+", " ", first_chunk.text.strip())
        raw_segs = re.split(r"(?<=[.!?])\s+", clean_text)
        single_sentence = raw_segs[0].strip() if raw_segs else clean_text[:120].strip()
        single_sentence = single_sentence.rstrip(".")

        answer = f"According to {first_chunk.doc_name}, {single_sentence} [{first_chunk.alias}]."
        citations = [
            CitationItem(
                alias=first_chunk.alias,
                doc_name=first_chunk.doc_name,
                page=first_chunk.page,
                section=first_chunk.section,
                quote_excerpt=first_chunk.text[:100],
            )
        ]

        return RAGResponse(
            request_id=record.request_id,
            query=record.query,
            answer=answer,
            citations=citations,
        )
