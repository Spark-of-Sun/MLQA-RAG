"""Column encryption for content and contact fields (blueprint 12.2; R-51 criteria 3 to 5; DEV-09 columns).

Every encrypted column holds one `lmqa_keys.envelope` value blob:

    b"L1" | key_version (4 bytes) | random 96-bit nonce | AES-256-GCM ciphertext and tag

The key version in the header names the key that sealed the value within its scope, so a rotated key keeps old
values readable (R-53.2). The associated data is `Binding(org_id, workspace_id, object_id, version, purpose)`, so a
ciphertext copied into another row, column, document, workspace or organization fails to decrypt (R-51.4).

Which key seals a field follows from its purpose:

    document key   document.title, document.filename, chunk.text, chunk.section
    workspace key  query.question, query.standalone_question, query.result, segment.text, conversation.title
    platform key   user.email, user.name, user.phone (users belong to no single organization)

`FieldCipher` needs the caller's connection: key rows are read under the caller's row-level security, so a caller
can only unwrap keys of a workspace it may see. Plaintext and key material are never logged; errors name the field
and scope only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lmqa_keys.envelope import Binding, decrypt_text, encrypt_text, key_version_of
from lmqa_keys.keyring import PLATFORM, Conn, KeyRing
from lmqa_keys.providers import KeyUnavailableError

DOCUMENT_PURPOSES = frozenset(
    {"document.title", "document.filename", "chunk.text", "chunk.section"}
)
WORKSPACE_PURPOSES = frozenset(
    {
        "query.question",
        "query.standalone_question",
        "query.result",
        "segment.text",
        "conversation.title",
    }
)
CONTACT_PURPOSES = frozenset({"user.email", "user.name", "user.phone"})

# Called with (org_id, workspace_id) when a workspace has no content key yet; it must create one in its own
# committed transaction (the identity service holds the grants). The cipher then retries once.
Provisioner = Callable[[str, str], None]


@dataclass(frozen=True)
class Field:
    """Where one encrypted value lives. Use the constructors below; they fix the purpose and the binding."""

    purpose: str
    org_id: str | None
    workspace_id: str | None
    object_id: str
    version: int = 1
    document_id: str | None = None

    def binding(self) -> Binding:
        return Binding(
            self.org_id or PLATFORM, self.workspace_id, self.object_id, self.version, self.purpose
        )

    @staticmethod
    def document(purpose: str, org_id: Any, workspace_id: Any, document_id: Any) -> Field:
        """document.title or document.filename of one document."""
        if purpose not in {"document.title", "document.filename"}:
            raise ValueError(f"not a document field: {purpose}")
        doc = str(document_id)
        return Field(purpose, str(org_id), str(workspace_id), doc, 1, doc)

    @staticmethod
    def chunk(  # noqa: PLR0913, PLR0917 - the binding has this many parts
        purpose: str,
        org_id: Any,
        workspace_id: Any,
        document_id: Any,
        chunk_id: Any,
        version: int = 1,
    ) -> Field:
        """chunk.text or chunk.section of one chunk version, sealed with its document's key."""
        if purpose not in {"chunk.text", "chunk.section"}:
            raise ValueError(f"not a chunk field: {purpose}")
        return Field(
            purpose, str(org_id), str(workspace_id), str(chunk_id), int(version), str(document_id)
        )

    @staticmethod
    def workspace(purpose: str, org_id: Any, workspace_id: Any, object_id: Any) -> Field:
        """A query, segment or conversation field, sealed with the workspace content key."""
        if purpose not in WORKSPACE_PURPOSES:
            raise ValueError(f"not a workspace field: {purpose}")
        return Field(purpose, str(org_id), str(workspace_id), str(object_id))

    @staticmethod
    def contact(purpose: str, user_id: Any) -> Field:
        if purpose not in CONTACT_PURPOSES:
            raise ValueError(f"not a contact field: {purpose}")
        return Field(purpose, None, None, str(user_id))


def normalize_email(email: str) -> str:
    return email.strip().lower()


class FieldCipher:
    """Seal and open column values. One instance per process; it shares the key ring's 15-minute key cache."""

    def __init__(self, ring: KeyRing, provision: Provisioner | None = None) -> None:
        self.ring = ring
        self._provision = provision

    def set_provisioner(self, provision: Provisioner) -> None:
        self._provision = provision

    # --- keys ---------------------------------------------------------------------------------------------

    def _workspace_key(
        self, conn: Conn, org_id: str, workspace_id: str, version: int | None
    ) -> tuple[int, bytes]:
        try:
            return self.ring.workspace_key(conn, org_id, workspace_id, version)
        except KeyUnavailableError:
            if version is not None or self._provision is None:
                raise
            self._provision(org_id, workspace_id)
            return self.ring.workspace_key(conn, org_id, workspace_id, version)

    def new_document(self, conn: Conn, org_id: Any, workspace_id: Any, document_id: Any) -> None:
        """Create the document key; call in the transaction that inserts the document row."""
        self._workspace_key(conn, str(org_id), str(workspace_id), None)  # provisions if needed
        self.ring.create_document_key(conn, org_id, workspace_id, document_id)

    def _key(self, conn: Conn, field: Field, version: int | None) -> tuple[int, bytes]:
        if field.purpose in DOCUMENT_PURPOSES:
            assert field.org_id and field.workspace_id and field.document_id
            v = version or 1
            return v, self.ring.document_key(
                conn, field.org_id, field.workspace_id, field.document_id, v
            )
        if field.purpose in WORKSPACE_PURPOSES:
            assert field.org_id and field.workspace_id
            return self._workspace_key(conn, field.org_id, field.workspace_id, version)
        if field.purpose in CONTACT_PURPOSES:
            return self._platform_key(conn, "contact", version)
        raise ValueError(f"unknown field purpose {field.purpose!r}")

    def _platform_key(self, conn: Conn, purpose: str, version: int | None) -> tuple[int, bytes]:
        """A platform key; sealing on a new deployment creates version 1 first (the writer is identity)."""
        try:
            return self.ring.platform_key(conn, purpose, version)
        except KeyUnavailableError:
            if version is not None:
                raise
            self.ring.ensure_platform_key(conn, purpose)
            return self.ring.platform_key(conn, purpose, version)

    # --- values -------------------------------------------------------------------------------------------

    def seal(self, conn: Conn, field: Field, value: str | None) -> bytes | None:
        """AES-256-GCM under the field's key; None stays None (an absent value is not encrypted)."""
        if value is None:
            return None
        version, key = self._key(conn, field, None)
        return encrypt_text(key, version, value, field.binding())

    def open(self, conn: Conn, field: Field, blob: bytes | memoryview | None) -> str | None:
        """The plaintext, or DecryptionError if the blob was moved, tampered with or sealed for another scope."""
        if blob is None:
            return None
        data = bytes(blob)
        _, key = self._key(conn, field, key_version_of(data))
        return decrypt_text(key, data, field.binding())

    def seal_json(self, conn: Conn, field: Field, value: Any) -> bytes | None:
        return self.seal(
            conn, field, None if value is None else json.dumps(value, separators=(",", ":"))
        )

    def open_json(self, conn: Conn, field: Field, blob: bytes | memoryview | None) -> Any:
        text = self.open(conn, field, blob)
        return None if text is None else json.loads(text)

    def blind_index(self, conn: Conn, email: str | None) -> bytes | None:
        """HMAC-SHA256 of the normalized email under the platform blind-index key (R-51.5): equality lookups
        without a plaintext column. Rotating the blind-index key means recomputing every index."""
        if not email:
            return None
        _, key = self._platform_key(conn, "blind_index", None)
        return hmac.new(
            key, b"user.email|" + normalize_email(email).encode("utf-8"), hashlib.sha256
        ).digest()

    # --- row helpers for the services ---------------------------------------------------------------------

    def open_chunk_row(self, conn: Conn, row: dict[str, Any]) -> dict[str, Any]:
        """Fill `text`, `section` (and `title` when `title_ct` was selected) in a chunk row selected with
        id, org_id, workspace_id, document_id, version, text_ct, section_ct."""
        args = (row["org_id"], row["workspace_id"], row["document_id"], row["id"])
        version = int(row.get("version") or 1)
        row["text"] = self.open(conn, Field.chunk("chunk.text", *args, version), row["text_ct"])
        row["section"] = self.open(
            conn, Field.chunk("chunk.section", *args, version), row.get("section_ct")
        )
        if "title_ct" in row:
            row["title"] = self.open(
                conn,
                Field.document(
                    "document.title", row["org_id"], row["workspace_id"], row["document_id"]
                ),
                row["title_ct"],
            )
        return row

    def open_contact_row(
        self, conn: Conn, row: dict[str, Any], *, user_key: str = "id"
    ) -> dict[str, Any]:
        """Fill `email`, `name` and `phone` from whichever of email_ct, name_ct, phone_ct the row has."""
        user_id = row[user_key]
        for name in ("email", "name", "phone"):
            if f"{name}_ct" in row:
                row[name] = self.open(
                    conn, Field.contact(f"user.{name}", user_id), row[f"{name}_ct"]
                )
        return row
