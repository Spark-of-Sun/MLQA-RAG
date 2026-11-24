"""Organization provisioning saga (blueprint 7.2, G2.1, G2.2).

Steps, each persisted before the next starts, so a crash at any point resumes where it stopped:

  1 org_row        organizations row in state `pending` (invisible: no active membership can reach it)
  2 kms_key        organization CMK (multi-Region, KeyGuard policy) and its replica; org_keys row
  3 audit_key      this month's audit key pair: public key stored, private key wrapped by the CMK
  4 auth0_org      Auth0 Organization with the connection enabled (idempotent by name)
  5 auth0_member   the creator added to the Auth0 Organization with the super_admin role
  6 membership     super_admin membership `active`, approved by the system (16.2 CHECK)
  7 activate       organization `pending` -> `active`, audit event `org.created`

Replaying a request with the same idempotency key returns the existing saga and creates nothing (G2.1). On a
permanent failure the saga compensates in reverse: remove the Auth0 Organization, schedule the CMK's deletion with
the policy window (a key is never destroyed immediately), and leave the organization `pending` (G2.2: the inventory
diff after compensation is empty).
"""

from __future__ import annotations

import contextlib
import re
import secrets
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import lmqa_audit
from identity.auth0_mgmt import Auth0Error, Auth0Management
from lmqa_keys.keyring import encryption_context
from lmqa_keys.providers import KeyProvider, KeyProviderError
from lmqa_security.sealing import generate_keypair

ConnFactory = Callable[[], AbstractContextManager[Any]]
STEPS = ("org_row", "kms_key", "audit_key", "auth0_org", "auth0_member", "membership", "activate")
MAX_ATTEMPTS = 5


class SagaError(RuntimeError):
    pass


@dataclass(frozen=True)
class SagaResult:
    saga_id: str
    org_id: str | None
    state: str
    step: str


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:40] or "org"
    return f"{base}-{secrets.token_hex(3)}"


class OrganizationSaga:
    def __init__(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        conn: ConnFactory,
        provider: KeyProvider,
        auth0: Auth0Management | None,
        *,
        alias_prefix: str = "alias/lmqa-dev-org-",
        key_policy: Callable[[str], str] | None = None,
        replica_region: str | None = None,
    ) -> None:
        self._conn = conn
        self._provider = provider
        self._auth0 = auth0
        self._alias_prefix = alias_prefix
        self._key_policy = key_policy
        self._replica_region = replica_region

    # --- public ---------------------------------------------------------------------------------------------

    def start(
        self, *, user_id: str, user_sub: str, name: str, kind: str, idempotency_key: str
    ) -> SagaResult:
        with self._conn() as conn:
            row = conn.execute(
                "insert into provisioning_sagas (kind, idempotency_key, user_id, input)"
                " values ('organization', %s, %s, jsonb_build_object('name', %s::text, 'kind', %s::text,"
                " 'sub', %s::text))"
                " on conflict (kind, user_id, idempotency_key) do update set updated_at = provisioning_sagas.updated_at"
                " returning id",
                [idempotency_key, user_id, name, kind, user_sub],
            ).fetchone()
        return self.resume(str(row["id"]))

    def resume(self, saga_id: str) -> SagaResult:
        saga = self._load(saga_id)
        if saga["state"] in {"completed", "compensated", "failed"}:
            return self._result(saga)
        try:
            for step in STEPS[STEPS.index(saga["step"]) + 1 if saga["step"] in STEPS else 0 :]:
                getattr(self, f"_step_{step}")(saga)
                saga = self._advance(saga_id, step)
            return self._finish(saga_id, "completed")
        except (Auth0Error, KeyProviderError, SagaError) as exc:
            attempts = self._bump(saga_id, str(exc))
            if attempts >= MAX_ATTEMPTS:
                self.compensate(saga_id)
            return self._result(self._load(saga_id))

    def compensate(self, saga_id: str) -> SagaResult:
        saga = self._load(saga_id)
        self._set(saga_id, state="compensating")
        if saga["auth0_org_id"] and self._auth0:
            self._auth0.delete_organization(saga["auth0_org_id"])
        for ref in (saga["kms_replica_ref"], saga["kms_key_ref"]):
            if ref:
                # already pending deletion: the inventory diff still shows it scheduled
                with contextlib.suppress(KeyProviderError):
                    self._provider.schedule_deletion(ref, window_days=30)
        with self._conn() as conn:
            if saga["org_id"]:
                conn.execute(
                    "update org_keys set state = 'pending_deletion' where org_id = %s",
                    [saga["org_id"]],
                )
                conn.execute("delete from memberships where org_id = %s", [saga["org_id"]])
        return self._finish(saga_id, "compensated")

    # --- steps ----------------------------------------------------------------------------------------------

    def _step_org_row(self, saga: dict[str, Any]) -> None:
        if saga["org_id"]:
            return
        data = saga["input"]
        with self._conn() as conn:
            org = conn.execute(
                "insert into organizations (name, kind, status, created_by) values (%s, %s, 'pending', %s)"
                " returning id",
                [data["name"], data["kind"], saga["user_id"]],
            ).fetchone()
            conn.execute(
                "update provisioning_sagas set org_id = %s where id = %s", [org["id"], saga["id"]]
            )
        saga["org_id"] = str(org["id"])

    def _step_kms_key(self, saga: dict[str, Any]) -> None:
        org_id = str(saga["org_id"])
        if not saga["kms_key_ref"]:
            policy = self._key_policy(org_id) if self._key_policy else None
            ref = self._provider.create_key(
                alias=f"lmqa-org-{org_id}"
                if self._provider.name == "openbao"
                else f"{self._alias_prefix}{org_id}",
                tags={"org_id": org_id, "project": "lmqa"},
                policy=policy,
            )
            self._set(saga["id"], kms_key_ref=ref)
            saga["kms_key_ref"] = ref
        replica = saga["kms_replica_ref"]
        if not replica and self._replica_region and hasattr(self._provider, "replicate"):
            replica = self._provider.replicate(saga["kms_key_ref"], self._replica_region)  # type: ignore[attr-defined]
            self._set(saga["id"], kms_replica_ref=replica)
        with self._conn() as conn:
            conn.execute(
                "insert into org_keys (org_id, key_version, provider, key_ref, replica_ref)"
                " values (%s, 1, %s, %s, %s) on conflict do nothing",
                [org_id, self._provider.name, saga["kms_key_ref"], replica],
            )
            conn.execute(
                "update organizations set kms_key_ref = %s where id = %s",
                [saga["kms_key_ref"], org_id],
            )

    def _step_audit_key(self, saga: dict[str, Any]) -> None:
        org_id = str(saga["org_id"])
        today = datetime.now(UTC)
        month = date(today.year, today.month, 1)
        with self._conn() as conn:
            exists = conn.execute(
                "select 1 from audit_keys where org_id = %s and workspace_id is null and month = %s",
                [org_id, month],
            ).fetchone()
            if exists:
                return
            private, public = generate_keypair()
            wrapped = self._provider.wrap(
                saga["kms_key_ref"], private, encryption_context(org_id, None, f"audit_key:{month}")
            )
            conn.execute(
                "insert into audit_keys (org_id, month, public_key, wrapped_private_key, wrapped_by)"
                " values (%s, %s, %s, %s, (select max(key_version) from org_keys where org_id = %s))",
                [org_id, month, public, wrapped, org_id],
            )

    def _step_auth0_org(self, saga: dict[str, Any]) -> None:
        if not self._auth0 or saga["auth0_org_id"]:
            return
        name = _slug(saga["input"]["name"])
        auth0_id = self._auth0.find_organization(name) or self._auth0.create_organization(
            name=name,
            display_name=saga["input"]["name"],
            metadata={"lmqa_org_id": str(saga["org_id"])},
        )
        self._set(saga["id"], auth0_org_id=auth0_id)
        saga["auth0_org_id"] = auth0_id
        with self._conn() as conn:
            conn.execute(
                "update organizations set auth0_org_id = %s where id = %s",
                [auth0_id, saga["org_id"]],
            )

    def _step_auth0_member(self, saga: dict[str, Any]) -> None:
        if not self._auth0 or not saga["auth0_org_id"]:
            return
        self._auth0.add_member(saga["auth0_org_id"], saga["input"]["sub"])
        self._auth0.assign_role(saga["auth0_org_id"], saga["input"]["sub"], "super_admin")

    def _step_membership(self, saga: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "insert into memberships (user_id, org_id, role, status, state_reason, decided_at)"
                " select %s, %s, 'super_admin', 'active', 'approved', now()"
                " where not exists (select 1 from memberships where user_id = %s and org_id = %s)",
                [saga["user_id"], saga["org_id"], saga["user_id"], saga["org_id"]],
            )

    def _step_activate(self, saga: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "update organizations set status = 'active', state_changed_at = now()"
                " where id = %s and status = 'pending'",
                [saga["org_id"]],
            )
            lmqa_audit.append(
                conn,
                org_id=saga["org_id"],
                action="org.created",
                actor_id=saga["user_id"],
                target_type="organization",
                target_id=saga["org_id"],
                payload={"saga": str(saga["id"]), "kind": saga["input"]["kind"]},
            )

    # --- persistence ----------------------------------------------------------------------------------------

    def _load(self, saga_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "select * from provisioning_sagas where id = %s", [saga_id]
            ).fetchone()
        if not row:
            raise SagaError(f"saga {saga_id} not found")
        saga = dict(row)
        for key in ("id", "org_id", "user_id"):
            if isinstance(saga.get(key), UUID):
                saga[key] = str(saga[key])
        return saga

    def _set(self, saga_id: str, **fields: Any) -> None:
        cols = ", ".join(f"{k} = %s" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"update provisioning_sagas set {cols}, updated_at = now() where id = %s",  # noqa: S608 - column names are keyword args from this module; values bound
                [*fields.values(), saga_id],
            )

    def _advance(self, saga_id: str, step: str) -> dict[str, Any]:
        self._set(saga_id, step=step)
        return self._load(saga_id)

    def _bump(self, saga_id: str, error: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "update provisioning_sagas set attempts = attempts + 1, error = %s, updated_at = now()"
                " where id = %s returning attempts",
                [error[:500], saga_id],
            ).fetchone()
        return int(row["attempts"])

    def _finish(self, saga_id: str, state: str) -> SagaResult:
        self._set(saga_id, state=state)
        return self._result(self._load(saga_id))

    @staticmethod
    def _result(saga: dict[str, Any]) -> SagaResult:
        return SagaResult(str(saga["id"]), saga["org_id"], saga["state"], saga["step"])
