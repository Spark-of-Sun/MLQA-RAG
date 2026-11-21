"""Audit client: sealed payloads and the monthly key pair (doc 13.2, 13.3, G9.2).

* Writers hold only the **public** half of the workspace-month key, so they can seal a payload
  but never read one. The hash chain commits to the ciphertext hash, so destroying a month's
  private key never breaks chain verification.
* If the month's public key is missing or an audit write fails, the caller must stop (fail closed):
  nothing proceeds unaudited (principle 10).
* Only the audit service unwraps the private key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from lmqa_security.sealing import generate_keypair, open_sealed, seal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from lmqa_keys import KeyProvider


class AuditKeyMissingError(RuntimeError):
    """No public key exists for this workspace-month; the write must not proceed."""


class AuditKeyDestroyedError(RuntimeError):
    """The month's private key was destroyed (crypto-shred): the payload is unreadable by design."""


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One event. IDs only in the metadata; any content goes in ``payload`` and is sealed."""

    action: str
    outcome: str
    scope: str  # 'org', 'admin', 'workspace' or 'tenant'
    actor_id: UUID | None = None
    actor_role: str | None = None
    target: str | None = None
    reason: str | None = None
    request_id: UUID | None = None
    ip: str | None = None
    user_agent: str | None = None
    payload: dict[str, Any] | None = None


def month_start(moment: datetime | None = None) -> date:
    """The first day of the (UTC) month a key belongs to."""
    now = moment or datetime.now(UTC)
    return date(now.year, now.month, 1)


def seal_aad(org_id: UUID, workspace_id: UUID, month: date, request_id: UUID | None) -> bytes:
    """Associated data binding a payload to its organization, workspace, month and request."""
    return f"lmqa/audit/v1|{org_id}|{workspace_id}|{month.isoformat()}|{request_id or ''}".encode()


def key_context(org_id: UUID, workspace_id: UUID, month: date) -> dict[str, str]:
    """The KMS encryption context under which a month's private key is wrapped."""
    return {
        "org_id": str(org_id),
        "workspace_id": str(workspace_id),
        "month": month.isoformat(),
        "purpose": "audit-private-key",
    }


class AuditWriter:
    """Appends events through the ``audit_append`` database function (the only writer)."""

    async def append(
        self,
        session: AsyncSession,
        org_id: UUID,
        workspace_id: UUID | None,
        event: AuditEvent,
        *,
        moment: datetime | None = None,
    ) -> UUID:
        """Seal the payload (if any) and append the event to the workspace or organization chain."""
        sealed: bytes | None = None
        key_id: str | None = None
        if event.payload is not None:
            if workspace_id is None:
                msg = "sealed payloads belong to a workspace"
                raise AuditKeyMissingError(msg)
            month = month_start(moment)
            row = (
                await session.execute(
                    text(
                        "SELECT public_key FROM audit_keys WHERE workspace_id = :w AND month = :m"
                    ),
                    {"w": workspace_id, "m": month},
                )
            ).first()
            if row is None:
                msg = f"no audit key for workspace {workspace_id} month {month}"
                raise AuditKeyMissingError(msg)
            body = json.dumps(event.payload, sort_keys=True, separators=(",", ":")).encode()
            sealed = seal(
                bytes(row[0]), body, seal_aad(org_id, workspace_id, month, event.request_id)
            )
            key_id = f"{workspace_id}:{month.isoformat()}"
        chain = f"ws:{workspace_id}" if workspace_id else f"org:{org_id}"
        result = await session.execute(
            text(
                "SELECT audit_append(:chain, :org, :ws, :actor, :role, :action, :target, "
                ":outcome, :reason,"
                " :req, CAST(:ip AS inet), :ua, :scope, :payload, :key_id)"
            ),
            {
                "chain": chain,
                "org": org_id,
                "ws": workspace_id,
                "actor": event.actor_id,
                "role": event.actor_role,
                "action": event.action,
                "target": event.target,
                "outcome": event.outcome,
                "reason": event.reason,
                "req": event.request_id,
                "ip": event.ip,
                "ua": event.user_agent,
                "scope": event.scope,
                "payload": sealed,
                "key_id": key_id,
            },
        )
        return UUID(str(result.scalar_one()))


class AuditKeyManager:
    """Creates a workspace-month key pair; the private half is stored only wrapped by the CMK."""

    async def ensure_month_key(  # noqa: PLR0913, PLR0917 - session, provider and key scope
        self,
        session: AsyncSession,
        provider: KeyProvider,
        cmk_id: str,
        org_id: UUID,
        workspace_id: UUID,
        month: date,
    ) -> bool:
        """Create the key pair if missing. Returns True when a new pair was created."""
        exists = (
            await session.execute(
                text("SELECT 1 FROM audit_keys WHERE workspace_id = :w AND month = :m"),
                {"w": workspace_id, "m": month},
            )
        ).first()
        if exists:
            return False
        pair = generate_keypair()
        wrapped = await provider.wrap(
            cmk_id, pair.private, key_context(org_id, workspace_id, month)
        )
        await session.execute(
            text(
                "INSERT INTO audit_keys (org_id, workspace_id, month, public_key, "
                "wrapped_private_key)"
                " VALUES (:o, :w, :m, :pub, :wrapped)"
            ),
            {"o": org_id, "w": workspace_id, "m": month, "pub": pair.public, "wrapped": wrapped},
        )
        return True


class AuditReader:
    """The audit service: the only code that unwraps a private key and opens payloads."""

    async def read_payload(
        self,
        session: AsyncSession,
        provider: KeyProvider,
        cmk_id: str,
        org_id: UUID,
        event_id: UUID,
    ) -> dict[str, Any]:
        """Decrypt one event's payload. Raises ``AuditKeyDestroyedError`` after a crypto-shred."""
        row = (
            await session.execute(
                text(
                    "SELECT p.ciphertext, p.workspace_id, p.key_id, e.request_id FROM "
                    "audit_payload p"
                    " JOIN audit_event e ON e.id = p.event_id WHERE p.event_id = :e"
                ),
                {"e": event_id},
            )
        ).first()
        if row is None:
            msg = "payload not found or not readable by this principal"
            raise LookupError(msg)
        ciphertext, workspace_id, key_id, request_id = bytes(row[0]), row[1], str(row[2]), row[3]
        month = date.fromisoformat(key_id.rsplit(":", 1)[1])
        key = (
            await session.execute(
                text(
                    "SELECT wrapped_private_key FROM audit_keys WHERE workspace_id = :w AND "
                    "month = :m"
                ),
                {"w": workspace_id, "m": month},
            )
        ).first()
        if key is None or key[0] is None:
            msg = f"the audit key for {month} was destroyed"
            raise AuditKeyDestroyedError(msg)
        private = await provider.unwrap(
            cmk_id, bytes(key[0]), key_context(org_id, workspace_id, month)
        )
        plain = open_sealed(private, ciphertext, seal_aad(org_id, workspace_id, month, request_id))
        return dict(json.loads(plain))

    async def destroy_month_key(
        self, session: AsyncSession, workspace_id: UUID, month: date
    ) -> None:
        """Crypto-shred a month's payloads (end of retention). Requires the system context."""
        await session.execute(
            text(
                "UPDATE audit_keys SET wrapped_private_key = NULL WHERE workspace_id = :w AND "
                "month = :m"
            ),
            {"w": workspace_id, "m": month},
        )
