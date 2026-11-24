"""Key providers: the organization CMK lives in a real KMS (blueprint 12.1, 12.10). Two real adapters, no fakes:

  AwsKmsProvider   reference cloud (D23). Encrypt/Decrypt/GenerateDataKey with an encryption context; deletion is
                   always scheduled with the maximum window, never immediate (KMS enforces 7 to 30 days).
  OpenBaoProvider  OpenBao Transit, local and CI. Derived keys with a context; supports immediate destruction,
                   which the shredding tests need (G1.11).

Both bind every wrap and unwrap to an encryption context (`org_id`, `workspace_id`, purpose), so a wrapped key
copied into another organization or workspace fails to unwrap. Service roles may encrypt, decrypt and generate data
keys only; disable, schedule and destroy calls exist for KeyGuard, whose cloud role is the only one allowed to make
them (12.5).
"""

from __future__ import annotations

import base64
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import httpx

from lmqa_models.infra import InfraSettings, load_infra_settings

PRODUCTION_DELETION_WINDOW_DAYS = 30
DRILL_DELETION_WINDOW_DAYS = 7


class KeyState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    PENDING_DELETION = "pending_deletion"
    DESTROYED = "destroyed"


class KeyProviderError(RuntimeError):
    """A provider call failed. Messages name the operation and key reference, never key material."""


class KeyUnavailableError(KeyProviderError):
    """The key is disabled, pending deletion or destroyed: decryption fails closed."""


@dataclass(frozen=True)
class DataKey:
    plaintext: bytes  # 32 bytes, kept in memory only
    wrapped: bytes

    def __repr__(self) -> str:
        return f"DataKey(wrapped={len(self.wrapped)} bytes)"


def _context_json(context: Mapping[str, str]) -> str:
    return json.dumps(dict(sorted(context.items())), separators=(",", ":"))


class KeyProvider(Protocol):
    name: str

    def create_key(
        self, *, alias: str, tags: Mapping[str, str], drill: bool = False, policy: str | None = None
    ) -> str: ...
    def wrap(self, key_ref: str, plaintext: bytes, context: Mapping[str, str]) -> bytes: ...
    def unwrap(self, key_ref: str, wrapped: bytes, context: Mapping[str, str]) -> bytes: ...
    def generate_data_key(self, key_ref: str, context: Mapping[str, str]) -> DataKey: ...
    def state(self, key_ref: str) -> KeyState: ...
    def disable(self, key_ref: str) -> None: ...
    def enable(self, key_ref: str) -> None: ...
    def schedule_deletion(self, key_ref: str, *, window_days: int) -> None: ...
    def cancel_deletion(self, key_ref: str) -> None: ...


# --- OpenBao Transit -------------------------------------------------------------------------------------------


class OpenBaoProvider:
    """OpenBao Transit with derived keys. `schedule_deletion` records a window; `destroy_now` shreds immediately."""

    name = "openbao"

    def __init__(self, infra: InfraSettings | None = None, *, mount: str = "transit") -> None:
        self._infra = infra or load_infra_settings()
        self._mount = mount
        self._base_url = f"{self._infra.openbao_addr}/v1/"
        self._headers = {"X-Vault-Token": self._infra.require("OPENBAO_TOKEN")}

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        # One short-lived client per call: calls are rare (unwrapped keys are cached by the key ring), and no
        # pooled socket outlives the call. The token travels in a header and is never logged.
        with httpx.Client(base_url=self._base_url, headers=self._headers, timeout=10.0) as client:
            return client.request(method, path, **kwargs)

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = self._request(method, path, **kwargs)
        if resp.status_code == 404:
            raise KeyUnavailableError(f"openbao {path}: key not found")
        if resp.status_code >= 400:
            raise KeyProviderError(f"openbao {method} {path}: HTTP {resp.status_code}")
        return resp.json() if resp.content else {}

    def ensure_mount(self) -> None:
        mounts = self._call("GET", "sys/mounts")
        if f"{self._mount}/" not in mounts.get("data", mounts):
            self._call("POST", f"sys/mounts/{self._mount}", json={"type": "transit"})

    def create_key(
        self, *, alias: str, tags: Mapping[str, str], drill: bool = False, policy: str | None = None
    ) -> str:
        del (
            tags,
            drill,
            policy,
        )  # OpenBao keys carry no tags or policies; the alias is the reference
        self.ensure_mount()
        self._call(
            "POST", f"{self._mount}/keys/{alias}", json={"type": "aes256-gcm96", "derived": True}
        )
        return alias

    def wrap(self, key_ref: str, plaintext: bytes, context: Mapping[str, str]) -> bytes:
        self._require_enabled(key_ref)
        out = self._call(
            "POST",
            f"{self._mount}/encrypt/{key_ref}",
            json={
                "plaintext": base64.b64encode(plaintext).decode(),
                "context": base64.b64encode(_context_json(context).encode()).decode(),
            },
        )
        return out["data"]["ciphertext"].encode()

    def unwrap(self, key_ref: str, wrapped: bytes, context: Mapping[str, str]) -> bytes:
        self._require_enabled(key_ref)
        resp = self._request(
            "POST",
            f"{self._mount}/decrypt/{key_ref}",
            json={
                "ciphertext": wrapped.decode(),
                "context": base64.b64encode(_context_json(context).encode()).decode(),
            },
        )
        if resp.status_code >= 400:
            raise KeyUnavailableError(
                f"openbao unwrap {key_ref}: refused (HTTP {resp.status_code})"
            )
        return base64.b64decode(resp.json()["data"]["plaintext"])

    def generate_data_key(self, key_ref: str, context: Mapping[str, str]) -> DataKey:
        plaintext = secrets.token_bytes(32)
        return DataKey(plaintext=plaintext, wrapped=self.wrap(key_ref, plaintext, context))

    def _meta(self, key_ref: str) -> dict[str, Any]:
        return self._call("GET", f"{self._mount}/keys/{key_ref}")["data"]

    def _state_path(self, key_ref: str) -> str:
        return f"secret/data/lmqa-keystate/{key_ref}"

    def _set_state(self, key_ref: str, state: KeyState) -> None:
        self._call("POST", self._state_path(key_ref), json={"data": {"state": state.value}})

    def state(self, key_ref: str) -> KeyState:
        try:
            self._meta(key_ref)
        except KeyUnavailableError:
            return KeyState.DESTROYED
        try:
            recorded = self._call("GET", self._state_path(key_ref))["data"]["data"]["state"]
        except KeyUnavailableError:
            return KeyState.ENABLED
        return KeyState(recorded)

    def _require_enabled(self, key_ref: str) -> None:
        if self.state(key_ref) is not KeyState.ENABLED:
            raise KeyUnavailableError(f"key {key_ref} is not enabled")

    def disable(self, key_ref: str, *, state: KeyState = KeyState.DISABLED) -> None:
        """Recorded state plus a cryptographic block: after a rotation, only the new (unused) version decrypts."""
        self._call("POST", f"{self._mount}/keys/{key_ref}/rotate")
        latest = int(self._meta(key_ref).get("latest_version", 1))
        self._call(
            "POST", f"{self._mount}/keys/{key_ref}/config", json={"min_decryption_version": latest}
        )
        self._set_state(key_ref, state)

    def enable(self, key_ref: str) -> None:
        self._call(
            "POST", f"{self._mount}/keys/{key_ref}/config", json={"min_decryption_version": 1}
        )
        self._set_state(key_ref, KeyState.ENABLED)

    def schedule_deletion(self, key_ref: str, *, window_days: int) -> None:
        del (
            window_days
        )  # Transit has no deletion window; KeyGuard keeps the window in its own records
        self.disable(key_ref, state=KeyState.PENDING_DELETION)

    def cancel_deletion(self, key_ref: str) -> None:
        self.enable(key_ref)

    def destroy_now(self, key_ref: str) -> None:
        """Immediate, irreversible destruction (local shredding tests only; never offered by AWS KMS)."""
        self._call("POST", f"{self._mount}/keys/{key_ref}/config", json={"deletion_allowed": True})
        self._call("DELETE", f"{self._mount}/keys/{key_ref}")
        self._request("DELETE", f"secret/metadata/lmqa-keystate/{key_ref}")


# --- AWS KMS ---------------------------------------------------------------------------------------------------


class AwsKmsProvider:
    """AWS KMS. Credentials come from the SDK chain (SSO profile locally, OIDC federation in CI); never from .env."""

    name = "aws_kms"

    def __init__(self, *, region: str, client: Any | None = None) -> None:
        import boto3

        self._kms = client or boto3.client("kms", region_name=region)
        self._errors = self._kms.exceptions

    def create_key(
        self, *, alias: str, tags: Mapping[str, str], drill: bool = False, policy: str | None = None
    ) -> str:
        """Multi-Region CMK with rotation, tags and the KeyGuard key policy (infra/keyguard/key-policy.json.tftpl)."""
        tag_list = [{"TagKey": k, "TagValue": v} for k, v in sorted(tags.items())]
        if drill:
            tag_list.append({"TagKey": "drill", "TagValue": "true"})
        extra = {"Policy": policy, "BypassPolicyLockoutSafetyCheck": False} if policy else {}
        key = self._kms.create_key(
            KeySpec="SYMMETRIC_DEFAULT",
            KeyUsage="ENCRYPT_DECRYPT",
            MultiRegion=True,
            Tags=tag_list,
            Description=f"lmqa organization CMK {alias}",
            **extra,
        )["KeyMetadata"]
        self._kms.create_alias(AliasName=alias, TargetKeyId=key["KeyId"])
        self._kms.enable_key_rotation(KeyId=key["KeyId"])
        return str(key["Arn"])

    def wrap(self, key_ref: str, plaintext: bytes, context: Mapping[str, str]) -> bytes:
        try:
            return bytes(
                self._kms.encrypt(
                    KeyId=key_ref, Plaintext=plaintext, EncryptionContext=dict(context)
                )["CiphertextBlob"]
            )
        except (self._errors.DisabledException, self._errors.KMSInvalidStateException) as exc:
            raise KeyUnavailableError(f"kms wrap {key_ref}: key unavailable") from exc

    def unwrap(self, key_ref: str, wrapped: bytes, context: Mapping[str, str]) -> bytes:
        try:
            return bytes(
                self._kms.decrypt(
                    KeyId=key_ref, CiphertextBlob=wrapped, EncryptionContext=dict(context)
                )["Plaintext"]
            )
        except (
            self._errors.DisabledException,
            self._errors.KMSInvalidStateException,
            self._errors.InvalidCiphertextException,
        ) as exc:
            raise KeyUnavailableError(f"kms unwrap {key_ref}: refused") from exc

    def generate_data_key(self, key_ref: str, context: Mapping[str, str]) -> DataKey:
        out = self._kms.generate_data_key(
            KeyId=key_ref, KeySpec="AES_256", EncryptionContext=dict(context)
        )
        return DataKey(plaintext=bytes(out["Plaintext"]), wrapped=bytes(out["CiphertextBlob"]))

    def state(self, key_ref: str) -> KeyState:
        meta = self._kms.describe_key(KeyId=key_ref)["KeyMetadata"]
        return {
            "Enabled": KeyState.ENABLED,
            "Disabled": KeyState.DISABLED,
            "PendingDeletion": KeyState.PENDING_DELETION,
            "PendingReplicaDeletion": KeyState.PENDING_DELETION,
        }.get(meta["KeyState"], KeyState.DISABLED)

    def tags(self, key_ref: str) -> dict[str, str]:
        out = self._kms.list_resource_tags(KeyId=key_ref)
        return {t["TagKey"]: t["TagValue"] for t in out.get("Tags", [])}

    def disable(self, key_ref: str) -> None:
        self._kms.disable_key(KeyId=key_ref)

    def enable(self, key_ref: str) -> None:
        self._kms.enable_key(KeyId=key_ref)

    def schedule_deletion(self, key_ref: str, *, window_days: int) -> None:
        drill = self.tags(key_ref).get("drill") == "true"
        minimum = DRILL_DELETION_WINDOW_DAYS if drill else PRODUCTION_DELETION_WINDOW_DAYS
        if window_days < minimum:
            raise KeyProviderError(
                f"deletion window {window_days} d is below the {minimum} d policy minimum"
            )
        self._kms.schedule_key_deletion(KeyId=key_ref, PendingWindowInDays=window_days)

    def cancel_deletion(self, key_ref: str) -> None:
        self._kms.cancel_key_deletion(KeyId=key_ref)

    def replicate(self, key_ref: str, region: str, *, policy: str | None = None) -> str:
        """Multi-Region replica (12.8): a second hold on deletion and regional disaster recovery."""
        extra = {"Policy": policy} if policy else {}
        return str(
            self._kms.replicate_key(KeyId=key_ref, ReplicaRegion=region, **extra)[
                "ReplicaKeyMetadata"
            ]["Arn"]
        )

    def sign(self, key_ref: str, message: bytes) -> bytes:
        """Asymmetric signature with the trust-root key (signer certificates, 9.1)."""
        return bytes(
            self._kms.sign(
                KeyId=key_ref, Message=message, MessageType="RAW", SigningAlgorithm="ECDSA_SHA_256"
            )["Signature"]
        )

    def public_key(self, key_ref: str) -> bytes:
        return bytes(self._kms.get_public_key(KeyId=key_ref)["PublicKey"])


def provider_from_settings(
    infra: InfraSettings | None = None, *, region: str | None = None
) -> KeyProvider:
    infra = infra or load_infra_settings()
    if infra.kms_provider == "aws":
        if not region:
            raise KeyProviderError("KMS_PROVIDER=aws needs AWS_REGION")
        return AwsKmsProvider(region=region)
    if infra.kms_provider == "openbao":
        return OpenBaoProvider(infra)
    raise KeyProviderError(f"unknown KMS_PROVIDER {infra.kms_provider}")
