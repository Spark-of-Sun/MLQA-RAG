"""The key hierarchy in use (blueprint 12.1, 12.2, 12.4, 12.6, 12.9, 22; R-51, R-53):

    organization CMK (KMS)  ->  workspace content key (workspace_keys, versioned, wrapped by the CMK)
                                    ->  document key (doc_keys, wrapped by a workspace content key version)
                                            ->  titles, file names, chunk text and sections, objects
                                    ->  questions, answers, answer segments, chat titles
                                    ->  daily cache key (cache_keys, wrapped by the workspace content key)
                            ->  workspace-month audit key pair (audit_keys, X25519, private half wrapped by the CMK;
                                workspace_id null = the organization control chain)
    platform CMK (KMS)      ->  contact key (platform_keys, user email, name and phone)
                            ->  blind-index key (platform_keys, HMAC-SHA256 equality lookups on email)

Every key is independent random material, so each level can be destroyed on its own (DEF-03). Unwrapped workspace,
document and platform keys are cached per process for 15 minutes (`DekCache`): KMS calls are about (instances x
active workspaces) per TTL, well inside the regional quota (G1.10, G10.8). A cached key never outlives the
workspace's sealing: sealing calls `KeyRing.forget(workspace)`, and the revocation consumer does the same on every
instance.

Rotation (R-53.2): `rotate_workspace_key` adds a version; new values use the newest active version and every older
version stays readable, because each ciphertext names its key version in its header. `rewrap_document_keys` moves
document keys to the newest version without changing them, so no content is rewritten.

`conn` is any object with `execute(sql, params)` returning rows as mappings: an `lmqa_db.Scope`, a scoped
`ServiceDatabase` transaction, or a psycopg connection with a dict row factory. RLS decides which key rows the
caller sees; this module adds no authority of its own.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from lmqa_keys.envelope import Binding, unwrap_key, wrap_key
from lmqa_keys.providers import KeyProvider, KeyUnavailableError

WORKSPACE_KEY_TTL_SECONDS = 15 * 60
PLATFORM = "platform"  # the encryption-context org of platform keys (users belong to no single organization)
PLATFORM_KEY_ALIAS = "lmqa-platform"
PLATFORM_PURPOSES = ("contact", "blind_index")


class _Conn(Protocol):
    def execute(self, query: Any, params: Any = None) -> Any: ...


Conn = _Conn  # any connection-like object with execute(); see the module docstring


@dataclass(frozen=True)
class OrgKey:
    org_id: str
    version: int
    key_ref: str


@dataclass(frozen=True)
class AuditKey:
    """One workspace-month audit key pair (KD-10). `workspace_id` None is the organization control chain."""

    org_id: str
    workspace_id: str | None
    month: date
    public_key: bytes  # raw X25519, 32 bytes; writers seal to it (HPKE, lmqa_security.sealing)

    def __repr__(self) -> str:
        return f"AuditKey(org={self.org_id}, workspace={self.workspace_id}, month={self.month})"


class DekCache:
    """A small TTL cache with single-flight loading: concurrent misses for one key make one provider call."""

    def __init__(
        self,
        ttl_seconds: float = WORKSPACE_KEY_TTL_SECONDS,
        max_entries: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._items: OrderedDict[tuple[str, int], tuple[float, bytes]] = OrderedDict()
        self._locks: dict[tuple[str, int], threading.Lock] = {}
        self._guard = threading.Lock()
        self.loads = 0

    def get(self, key: tuple[str, int], load: Callable[[], bytes]) -> bytes:
        now = self._clock()
        with self._guard:
            hit = self._items.get(key)
            if hit and hit[0] > now:
                self._items.move_to_end(key)
                return hit[1]
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            with self._guard:
                hit = self._items.get(key)
                if hit and hit[0] > self._clock():
                    return hit[1]
            value = load()
            with self._guard:
                self.loads += 1
                self._items[key] = (self._clock() + self._ttl, value)
                self._items.move_to_end(key)
                while len(self._items) > self._max:
                    self._items.popitem(last=False)
            return value

    def forget(self, prefix: str) -> None:
        with self._guard:
            for key in [k for k in self._items if k[0] == prefix]:
                del self._items[key]

    def clear(self) -> None:
        with self._guard:
            self._items.clear()


def encryption_context(org_id: str, workspace_id: str | None, purpose: str) -> dict[str, str]:
    ctx = {"org_id": org_id, "purpose": purpose}
    if workspace_id:
        ctx["workspace_id"] = workspace_id
    return ctx


def audit_key_context(org_id: str, workspace_id: str | None, month: date) -> dict[str, str]:
    return encryption_context(org_id, workspace_id, f"audit_key:{month.isoformat()}")


def _month(value: date) -> date:
    return date(value.year, value.month, 1)


def generate_audit_keypair() -> tuple[bytes, bytes]:
    """(raw private key, raw public key) of a fresh X25519 pair, 32 bytes each (the HPKE suite of
    lmqa_security.sealing)."""
    private = X25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return raw_private, raw_public


def _alias(provider: KeyProvider, name: str) -> str:
    return f"alias/{name}" if provider.name == "aws_kms" else name


class KeyRing:
    def __init__(self, provider: KeyProvider, cache: DekCache | None = None) -> None:
        self.provider = provider
        self.cache = cache or DekCache()

    # --- organization CMK ---------------------------------------------------------------------------------

    @staticmethod
    def org_key(conn: _Conn, org_id: UUID | str) -> OrgKey:
        row = conn.execute(
            "select key_version, key_ref, state from org_keys where org_id = %s order by key_version desc limit 1",
            [str(org_id)],
        ).fetchone()
        if not row:
            raise KeyUnavailableError(f"organization {org_id} has no key")
        if row["state"] != "enabled":
            raise KeyUnavailableError(f"organization {org_id} key is {row['state']}")
        return OrgKey(str(org_id), int(row["key_version"]), str(row["key_ref"]))

    def ensure_org_key(self, conn: _Conn, org_id: UUID | str) -> OrgKey:
        """The organization's CMK, created in the provider and recorded in `org_keys` on first use. Idempotent: the
        provider key is named after the organization, so a retry after a failure finds the same key."""
        row = conn.execute(
            "select 1 from org_keys where org_id = %s limit 1", [str(org_id)]
        ).fetchone()
        if not row:
            ref = self.provider.create_key(
                alias=_alias(self.provider, f"lmqa-org-{org_id}"),
                tags={"org_id": str(org_id), "project": "lmqa"},
            )
            conn.execute(
                "insert into org_keys (org_id, key_version, provider, key_ref) values (%s, 1, %s, %s)"
                " on conflict do nothing",
                [str(org_id), self.provider.name, ref],
            )
        return self.org_key(conn, org_id)

    # --- workspace content keys ---------------------------------------------------------------------------

    def create_workspace_key(
        self,
        conn: _Conn,
        org_id: UUID | str,
        workspace_id: UUID | str,
        escrow: tuple[KeyProvider, str] | None = None,
    ) -> int:
        """Add the next workspace content key version (also the rotation step, R-53.2). Older versions stay
        readable; new values use this one. Returns the version now newest (another writer's on a race)."""
        org = self.org_key(conn, org_id)
        current = conn.execute(
            "select coalesce(max(key_version), 0) as v from workspace_keys where workspace_id = %s",
            [str(workspace_id)],
        ).fetchone()
        version = int(current["v"]) + 1
        material = secrets.token_bytes(32)
        ctx = encryption_context(org.org_id, str(workspace_id), "workspace_key")
        wrapped = self.provider.wrap(org.key_ref, material, ctx)
        escrowed = (
            escrow[0].wrap(escrow[1], material, {**ctx, "purpose": "escrow"}) if escrow else None
        )
        conn.execute(
            "insert into workspace_keys (org_id, workspace_id, key_version, wrapped_key, wrapped_by, escrow_wrapped)"
            " values (%s, %s, %s, %s, %s, %s) on conflict do nothing",
            [org.org_id, str(workspace_id), version, wrapped, org.version, escrowed],
        )
        return version

    def ensure_workspace_key(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str
    ) -> int:
        """The newest active workspace content key version, creating the organization CMK and version 1 if needed."""
        row = conn.execute(
            "select max(key_version) as v from workspace_keys where workspace_id = %s and state = 'active'",
            [str(workspace_id)],
        ).fetchone()
        if row and row["v"] is not None:
            return int(row["v"])
        self.ensure_org_key(conn, org_id)
        return self.create_workspace_key(conn, org_id, workspace_id)

    def rotate_workspace_key(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str
    ) -> int:
        """Routine rotation (R-53.2): a new version for new values; no data is rewritten. Follow with
        `rewrap_document_keys` (lazily, in batches) to move document keys under the new version."""
        return self.create_workspace_key(conn, org_id, workspace_id)

    def workspace_key(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str, version: int | None = None
    ) -> tuple[int, bytes]:
        if version is None:
            row = conn.execute(
                "select key_version from workspace_keys where workspace_id = %s and state = 'active'"
                " order by key_version desc limit 1",
                [str(workspace_id)],
            ).fetchone()
            if not row:
                raise KeyUnavailableError(
                    f"workspace {workspace_id} has no active key (sealed or destroyed)"
                )
            version = int(row["key_version"])

        def load() -> bytes:
            row = conn.execute(
                "select k.wrapped_key, o.key_ref from workspace_keys k"
                " join org_keys o on o.org_id = k.org_id and o.key_version = k.wrapped_by"
                " where k.workspace_id = %s and k.key_version = %s and k.state <> 'destroyed'",
                [str(workspace_id), version],
            ).fetchone()
            if not row:
                raise KeyUnavailableError(f"workspace {workspace_id} key v{version} is unavailable")
            return self.provider.unwrap(
                str(row["key_ref"]),
                bytes(row["wrapped_key"]),
                encryption_context(str(org_id), str(workspace_id), "workspace_key"),
            )

        return version, self.cache.get((str(workspace_id), version), load)

    def forget(self, workspace_id: UUID | str) -> None:
        self.cache.forget(str(workspace_id))

    # --- document keys ------------------------------------------------------------------------------------

    def create_document_key(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str, document_id: UUID | str
    ) -> tuple[int, bytes]:
        """Document key version 1 under the newest workspace key version. Idempotent: an existing key is returned."""
        ws_version, ws_key = self.workspace_key(conn, org_id, workspace_id)
        material = secrets.token_bytes(32)
        binding = Binding(org_id, workspace_id, document_id, 1, "doc_key")
        created = conn.execute(
            "insert into doc_keys (org_id, workspace_id, document_id, key_version, wrapped_key, wrapped_by)"
            " values (%s, %s, %s, 1, %s, %s) on conflict do nothing returning key_version",
            [
                str(org_id),
                str(workspace_id),
                str(document_id),
                wrap_key(ws_key, ws_version, material, binding),
                ws_version,
            ],
        ).fetchone()
        if created is None:
            return 1, self.document_key(conn, org_id, workspace_id, document_id, 1)
        return 1, material

    def document_key(
        self,
        conn: _Conn,
        org_id: UUID | str,
        workspace_id: UUID | str,
        document_id: UUID | str,
        version: int = 1,
    ) -> bytes:
        def load() -> bytes:
            row = conn.execute(
                "select wrapped_key, wrapped_by, state from doc_keys where document_id = %s and key_version = %s",
                [str(document_id), version],
            ).fetchone()
            if not row or row["state"] != "active":
                raise KeyUnavailableError(f"document {document_id} key is unavailable")
            _, ws_key = self.workspace_key(conn, org_id, workspace_id, int(row["wrapped_by"]))
            return unwrap_key(
                ws_key,
                bytes(row["wrapped_key"]),
                Binding(org_id, workspace_id, document_id, version, "doc_key"),
            )

        return self.cache.get((f"doc:{document_id}", version), load)

    def forget_document(self, document_id: UUID | str) -> None:
        self.cache.forget(f"doc:{document_id}")

    def rewrap_document_keys(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str, *, limit: int = 500
    ) -> int:
        """Re-wrap up to `limit` document keys still under an older workspace key version (R-53.2, lazy). The
        document keys themselves do not change, so no content is re-encrypted. Returns the number re-wrapped."""
        newest, new_key = self.workspace_key(conn, org_id, workspace_id)
        rows = conn.execute(
            "select document_id, key_version, wrapped_key, wrapped_by from doc_keys"
            " where workspace_id = %s and state = 'active' and wrapped_by < %s limit %s",
            [str(workspace_id), newest, limit],
        ).fetchall()
        for row in rows:
            binding = Binding(
                org_id, workspace_id, row["document_id"], int(row["key_version"]), "doc_key"
            )
            _, old_key = self.workspace_key(conn, org_id, workspace_id, int(row["wrapped_by"]))
            material = unwrap_key(old_key, bytes(row["wrapped_key"]), binding)
            conn.execute(
                "update doc_keys set wrapped_key = %s, wrapped_by = %s"
                " where document_id = %s and key_version = %s",
                [
                    wrap_key(new_key, newest, material, binding),
                    newest,
                    str(row["document_id"]),
                    row["key_version"],
                ],
            )
        return len(rows)

    # --- platform keys (user contact fields, blind index) -------------------------------------------------

    def _platform_ref(self, conn: _Conn) -> str:
        row = conn.execute(
            "select key_ref from platform_keys where purpose = 'contact' order by key_version limit 1"
        ).fetchone()
        if row:
            return str(row["key_ref"])
        return self.provider.create_key(
            alias=_alias(self.provider, PLATFORM_KEY_ALIAS), tags={"project": "lmqa"}
        )

    def ensure_platform_key(self, conn: _Conn, purpose: str) -> int:
        """The newest platform key version for `purpose` ('contact' or 'blind_index'), created on first use."""
        if purpose not in PLATFORM_PURPOSES:
            raise ValueError(f"unknown platform key purpose {purpose!r}")
        row = conn.execute(
            "select max(key_version) as v from platform_keys where purpose = %s and state = 'active'",
            [purpose],
        ).fetchone()
        if row and row["v"] is not None:
            return int(row["v"])
        ref = self._platform_ref(conn)
        wrapped = self.provider.wrap(
            ref, secrets.token_bytes(32), encryption_context(PLATFORM, None, f"platform:{purpose}")
        )
        conn.execute(
            "insert into platform_keys (purpose, key_version, provider, key_ref, wrapped_key)"
            " values (%s, 1, %s, %s, %s) on conflict do nothing",
            [purpose, self.provider.name, ref, wrapped],
        )
        return 1

    def platform_key(
        self, conn: _Conn, purpose: str, version: int | None = None
    ) -> tuple[int, bytes]:
        if version is None:
            row = conn.execute(
                "select max(key_version) as v from platform_keys where purpose = %s and state = 'active'",
                [purpose],
            ).fetchone()
            if not row or row["v"] is None:
                raise KeyUnavailableError(f"no active platform {purpose} key")
            version = int(row["v"])

        def load() -> bytes:
            row = conn.execute(
                "select key_ref, wrapped_key from platform_keys"
                " where purpose = %s and key_version = %s and state <> 'destroyed'",
                [purpose, version],
            ).fetchone()
            if not row:
                raise KeyUnavailableError(f"platform {purpose} key v{version} is unavailable")
            return self.provider.unwrap(
                str(row["key_ref"]),
                bytes(row["wrapped_key"]),
                encryption_context(PLATFORM, None, f"platform:{purpose}"),
            )

        return version, self.cache.get((f"platform:{purpose}", version), load)

    # --- daily cache keys ---------------------------------------------------------------------------------

    def cache_key(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str, day: date
    ) -> tuple[int, bytes]:
        """The workspace's cache key for `day` (independent random material wrapped by the workspace content key,
        R-51.2), created on first use. Returns (key_version, key): the version is the day as YYYYMMDD, so an
        entry written under yesterday's key no longer decrypts and expires with it."""
        version = int(day.strftime("%Y%m%d"))

        def load() -> bytes:
            row = conn.execute(
                "select wrapped_key, wrapped_by from cache_keys where workspace_id = %s and day = %s",
                [str(workspace_id), day],
            ).fetchone()
            binding = Binding(org_id, workspace_id, f"cache:{day.isoformat()}", 1, "cache_key")
            if row is None:
                ws_version, ws_key = self.workspace_key(conn, org_id, workspace_id)
                material = secrets.token_bytes(32)
                created = conn.execute(
                    "insert into cache_keys (org_id, workspace_id, day, wrapped_key, wrapped_by)"
                    " values (%s, %s, %s, %s, %s) on conflict do nothing returning day",
                    [
                        str(org_id),
                        str(workspace_id),
                        day,
                        wrap_key(ws_key, ws_version, material, binding),
                        ws_version,
                    ],
                ).fetchone()
                if created is not None:
                    return material
                row = conn.execute(
                    "select wrapped_key, wrapped_by from cache_keys where workspace_id = %s and day = %s",
                    [str(workspace_id), day],
                ).fetchone()
                if row is None:
                    raise KeyUnavailableError(
                        f"cache key for workspace {workspace_id} is unavailable"
                    )
            _, ws_key = self.workspace_key(conn, org_id, workspace_id, int(row["wrapped_by"]))
            return unwrap_key(ws_key, bytes(row["wrapped_key"]), binding)

        return version, self.cache.get((f"cache:{workspace_id}", version), load)

    # --- workspace-month audit keys (KD-10; used by lmqa_audit, task 3.8) --------------------------------

    def ensure_audit_key(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str | None, month: date
    ) -> AuditKey:
        """The X25519 audit key pair of one workspace (or, with workspace_id None, the organization control chain)
        for one calendar month, created on first use: the private half is wrapped by the organization CMK with an
        encryption context naming the organization, workspace and month."""
        month = _month(month)
        existing = self._audit_row(conn, org_id, workspace_id, month)
        if existing is not None:
            return existing
        org = self.ensure_org_key(conn, org_id)
        private, public = generate_audit_keypair()
        wrapped = self.provider.wrap(
            org.key_ref,
            private,
            audit_key_context(str(org_id), str(workspace_id) if workspace_id else None, month),
        )
        conn.execute(
            "insert into audit_keys (org_id, workspace_id, month, public_key, wrapped_private_key, wrapped_by)"
            " values (%s, %s, %s, %s, %s, %s) on conflict do nothing",
            [
                str(org_id),
                str(workspace_id) if workspace_id else None,
                month,
                public,
                wrapped,
                org.version,
            ],
        )
        created = self._audit_row(conn, org_id, workspace_id, month)
        if created is None:
            raise KeyUnavailableError(
                f"audit key for {org_id}/{workspace_id}/{month} is unavailable"
            )
        return created

    @staticmethod
    def _audit_row(
        conn: _Conn, org_id: UUID | str, workspace_id: UUID | str | None, month: date
    ) -> AuditKey | None:
        row = conn.execute(
            "select public_key from audit_keys where org_id = %s and workspace_id is not distinct from %s"
            " and month = %s and state = 'active'",
            [str(org_id), str(workspace_id) if workspace_id else None, _month(month)],
        ).fetchone()
        if row is None:
            return None
        return AuditKey(
            str(org_id),
            str(workspace_id) if workspace_id else None,
            _month(month),
            bytes(row["public_key"]),
        )

    def audit_public_key(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str | None, month: date
    ) -> AuditKey:
        """The active public key writers seal to. Raises KeyUnavailableError when the month has no active key
        (the writer must fail closed); provisioning creates the current and next month ahead of time."""
        key = self._audit_row(conn, org_id, workspace_id, month)
        if key is None:
            raise KeyUnavailableError(
                f"no active audit key for {org_id}/{workspace_id or 'control'}/{_month(month)}"
            )
        return key

    def audit_private_key(
        self, conn: _Conn, org_id: UUID | str, workspace_id: UUID | str | None, month: date
    ) -> bytes | None:
        """The raw X25519 private key for opening sealed payloads (audit service only). None once the month is
        shredded: the payloads are gone, the chain still verifies."""
        month = _month(month)
        row = conn.execute(
            "select k.wrapped_private_key, k.state, o.key_ref from audit_keys k"
            " join org_keys o on o.org_id = k.org_id and o.key_version = k.wrapped_by"
            " where k.org_id = %s and k.workspace_id is not distinct from %s and k.month = %s",
            [str(org_id), str(workspace_id) if workspace_id else None, month],
        ).fetchone()
        if not row or row["state"] == "destroyed" or not row["wrapped_private_key"]:
            return None
        return self.provider.unwrap(
            str(row["key_ref"]),
            bytes(row["wrapped_private_key"]),
            audit_key_context(str(org_id), str(workspace_id) if workspace_id else None, month),
        )

    @staticmethod
    def shred_document(
        conn: _Conn,
        org_id: UUID | str,
        workspace_id: UUID | str,
        document_id: UUID | str,
        approvers: list[str] | None = None,
    ) -> None:
        """Crypto-erase: overwrite the wrapped key and record a tombstone in the same transaction (12.9).
        Restores replay tombstones before accepting traffic, so a restored backup's wrapped key is shredded again."""
        conn.execute(
            "update doc_keys set wrapped_key = '\\x00'::bytea, state = 'destroyed', destroyed_at = now()"
            " where document_id = %s",
            [str(document_id)],
        )
        conn.execute(
            "insert into deletion_tombstones (org_id, workspace_id, scope, target_id, approver_refs)"
            " values (%s, %s, 'document', %s, %s::uuid[])",
            [str(org_id), str(workspace_id), str(document_id), approvers or []],
        )

    # --- sealing ------------------------------------------------------------------------------------------

    def seal_workspace(self, conn: _Conn, workspace_id: UUID | str) -> None:
        """Remove the CMK-wrapped copies (12.6): only the escrow copy (two custodians) can bring them back."""
        conn.execute(
            "update workspace_keys set wrapped_key = '\\x00'::bytea, state = 'retired' where workspace_id = %s",
            [str(workspace_id)],
        )
        self.forget(workspace_id)

    def unseal_workspace(
        self,
        conn: _Conn,
        org_id: UUID | str,
        workspace_id: UUID | str,
        escrow: tuple[KeyProvider, str],
    ) -> int:
        """Release the escrow copies (the escrow CMK's key policy requires two custodians) and re-wrap them under
        the organization CMK. Returns the number of key versions restored."""
        org = self.org_key(conn, org_id)
        rows = conn.execute(
            "select key_version, escrow_wrapped from workspace_keys where workspace_id = %s and state = 'retired'"
            " and escrow_wrapped is not null",
            [str(workspace_id)],
        ).fetchall()
        ctx = encryption_context(str(org_id), str(workspace_id), "workspace_key")
        for row in rows:
            material = escrow[0].unwrap(
                escrow[1], bytes(row["escrow_wrapped"]), {**ctx, "purpose": "escrow"}
            )
            conn.execute(
                "update workspace_keys set wrapped_key = %s, wrapped_by = %s, state = 'active'"
                " where workspace_id = %s and key_version = %s",
                [
                    self.provider.wrap(org.key_ref, material, ctx),
                    org.version,
                    str(workspace_id),
                    row["key_version"],
                ],
            )
        return len(rows)
