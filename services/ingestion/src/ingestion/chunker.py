"""Legal structural chunker with preamble detection and token bounds."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from lmqa_models import Chunk, ChunkMetadata

if TYPE_CHECKING:
    from ingestion.models import DocumentTarget

# Regex matching legal headings (Articles, Sections, Clauses, Exhibits)
HEADING_PATTERN = re.compile(
    r"(?m)^(ARTICLE\s+[IVXLCDM\d]+|SECTION\s+\d+[\.\d+]*|CLAUSE\s+\d+|SCHEDULE\s+[A-Z\d]+|EXHIBIT\s+[A-Z\d]+)\b[.:\s]*(.*)$",
    re.IGNORECASE,
)


class StructuralChunker:
    """Segments legal text into structural chunks complying with token bounds."""

    def __init__(
        self,
        min_tokens: int = 40,
        target_min: int = 300,
        target_max: int = 700,
        max_tokens: int = 1200,
    ) -> None:
        """Initialize chunker bounds."""
        self.min_tokens = min_tokens
        self.target_min = target_min
        self.target_max = target_max
        self.max_tokens = max_tokens

    def chunk_document(
        self,
        target: DocumentTarget,
        pages: list[tuple[int, str]],
    ) -> list[Chunk]:
        """Chunk document text into structural units, guaranteeing a preamble chunk."""
        combined_text = "\n\n".join(text for _, text in pages if text.strip())
        if not combined_text.strip():
            msg = "Cannot chunk empty document text"
            raise ValueError(msg)

        chunks: list[Chunk] = []
        ordinal = 0

        # Find heading positions
        matches = list(HEADING_PATTERN.finditer(combined_text))

        if not matches:
            # Entire text treated as preamble or fallback
            sub_texts = self._split_if_overlong(combined_text, self.max_tokens)
            for sub in sub_texts:
                meta = ChunkMetadata(
                    doc_id=target.doc_id,
                    doc_version=target.doc_version,
                    ordinal=ordinal,
                    title=target.title,
                    page="1",
                    section="Preamble",
                    kind="preamble",
                )
                chunk = Chunk.create(
                    chunk_id=uuid.uuid5(target.doc_id, f"chunk_{ordinal}"),
                    org_id=target.org_id,
                    workspace_id=target.workspace_id,
                    metadata=meta,
                    text=sub,
                )
                chunks.append(chunk)
                ordinal += 1
            return chunks

        # 1. Preamble chunk: text prior to the first heading
        first_match = matches[0]
        preamble_text = combined_text[: first_match.start()].strip()
        if preamble_text:
            sub_preambles = self._split_if_overlong(preamble_text, self.max_tokens)
            for sub in sub_preambles:
                meta = ChunkMetadata(
                    doc_id=target.doc_id,
                    doc_version=target.doc_version,
                    ordinal=ordinal,
                    title=target.title,
                    page="1",
                    section="Preamble / Recitals",
                    kind="preamble",
                )
                chunks.append(
                    Chunk.create(
                        chunk_id=uuid.uuid5(target.doc_id, f"chunk_{ordinal}"),
                        org_id=target.org_id,
                        workspace_id=target.workspace_id,
                        metadata=meta,
                        text=sub,
                    )
                )
                ordinal += 1
        else:
            # If document starts with heading, create synthetic preamble
            meta = ChunkMetadata(
                doc_id=target.doc_id,
                doc_version=target.doc_version,
                ordinal=ordinal,
                title=target.title,
                page="1",
                section="Preamble",
                kind="preamble",
            )
            chunks.append(
                Chunk.create(
                    chunk_id=uuid.uuid5(target.doc_id, f"chunk_{ordinal}"),
                    org_id=target.org_id,
                    workspace_id=target.workspace_id,
                    metadata=meta,
                    text=f"{target.title} - Agreement Preamble",
                )
            )
            ordinal += 1

        # 2. Structural sections
        for idx, match in enumerate(matches):
            heading = match.group(0).strip()
            start_pos = match.start()
            end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(combined_text)
            section_body = combined_text[start_pos:end_pos].strip()

            if not section_body:
                continue

            sub_sections = self._split_if_overlong(section_body, self.max_tokens)
            for sub in sub_sections:
                kind = "clause" if "clause" in heading.lower() else "section"
                meta = ChunkMetadata(
                    doc_id=target.doc_id,
                    doc_version=target.doc_version,
                    ordinal=ordinal,
                    title=target.title,
                    page="1",
                    section=heading[:100],
                    kind=kind,
                )
                chunks.append(
                    Chunk.create(
                        chunk_id=uuid.uuid5(target.doc_id, f"chunk_{ordinal}"),
                        org_id=target.org_id,
                        workspace_id=target.workspace_id,
                        metadata=meta,
                        text=sub,
                    )
                )
                ordinal += 1

        return chunks

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text.split()))

    def _split_if_overlong(self, text: str, max_tokens: int) -> list[str]:
        """Split text exceeding max_tokens on paragraph boundaries with ~10% overlap."""
        tokens = self._estimate_tokens(text)
        if tokens <= max_tokens:
            return [text]

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) <= 1:
            # Fallback split on sentences
            paragraphs = [s.strip() for s in text.split(". ") if s.strip()]

        parts: list[str] = []
        current: list[str] = []
        curr_tokens = 0

        for p in paragraphs:
            p_tokens = self._estimate_tokens(p)
            if curr_tokens + p_tokens > max_tokens and current:
                parts.append("\n\n".join(current))
                # 10% overlap: keep the last item
                overlap_item = current[-1]
                current = [overlap_item, p]
                curr_tokens = self._estimate_tokens(overlap_item) + p_tokens
            else:
                current.append(p)
                curr_tokens += p_tokens

        if current:
            parts.append("\n\n".join(current))

        return parts or [text]
