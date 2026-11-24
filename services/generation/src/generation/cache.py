"""Scoped answer cache (blueprint 10.7, 11.4, D12, G6.5).

Key = SHA-256 over (workspace, scope_hash, chunk-set hash, prompt version hash, model, normalized question), so a
cached answer can only be replayed to a caller who sees exactly the same chunks through exactly the same scope.
Any permission change moves `scope_hash`; any document change moves the chunk-set hash (it covers each chunk's
content hash). Values are encrypted with the workspace's daily cache key (AES-256-GCM with associated data naming
the cache entry), so Valkey never holds plaintext answers. Off by default for medical and mixed organizations.

A cached answer is still validated again before release: the cache saves the model call, never the validator.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import valkey

from lmqa_keys.envelope import Binding, DecryptionError, decrypt_value, encrypt_value
from lmqa_models.rag import Source

DEFAULT_TTL = 6 * 3600


def chunk_set_hash(sources: list[Source]) -> str:
    items = sorted(f"{s.chunk_id}:{s.sha256}" for s in sources)
    return hashlib.sha256("\n".join(items).encode()).hexdigest()


def cache_key(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
    *,
    workspace_id: str,
    scope_hash: str,
    sources: list[Source],
    prompt_sha256: str,
    model: str,
    question: str,
) -> str:
    norm = " ".join(question.lower().split())
    material = "|".join(
        [workspace_id, scope_hash, chunk_set_hash(sources), prompt_sha256, model, norm]
    )
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass
class AnswerCache:
    client: valkey.Valkey | None
    enabled_for_org_kind: frozenset[str] = frozenset({"legal"})
    ttl: int = DEFAULT_TTL

    def enabled(self, org_kind: str) -> bool:
        return self.client is not None and org_kind in self.enabled_for_org_kind

    def get(
        self,
        *,
        org_id: str,
        workspace_id: str,
        key: str,
        cache_key_material: bytes,
        key_version: int,
    ) -> dict[str, Any] | None:
        if self.client is None:
            return None
        try:
            blob = self.client.get(f"cache:{workspace_id}:{key}")
        except valkey.exceptions.ValkeyError:
            return None  # the cache is an optimization; failure means a normal model call
        if not blob:
            return None
        try:
            plain = decrypt_value(
                cache_key_material,
                bytes(blob),
                Binding(org_id, workspace_id, key, key_version, "answer_cache"),
            )
        except DecryptionError:
            return None  # rotated cache key: the entry expired with it
        return json.loads(plain)

    def put(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        *,
        org_id: str,
        workspace_id: str,
        key: str,
        value: dict[str, Any],
        cache_key_material: bytes,
        key_version: int,
    ) -> None:
        if self.client is None:
            return
        blob = encrypt_value(
            cache_key_material,
            key_version,
            json.dumps(value).encode(),
            Binding(org_id, workspace_id, key, key_version, "answer_cache"),
        )
        try:
            self.client.set(f"cache:{workspace_id}:{key}", blob, ex=self.ttl)
        except valkey.exceptions.ValkeyError:
            return

    def invalidate_workspace(self, workspace_id: str) -> int:
        if self.client is None:
            return 0
        n = 0
        for k in self.client.scan_iter(match=f"cache:{workspace_id}:*", count=500):
            n += int(self.client.delete(k))
        return n
