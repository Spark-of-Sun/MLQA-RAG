"""AWS KMS adapter (doc 12.5 to 12.8): the reference production key provider.

boto3 is blocking, so every call runs in a worker thread. Deletion windows are validated here
as well as by the policy lint in CI: a production key always uses the 30 day maximum.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import boto3
from botocore.exceptions import ClientError

from lmqa_keys.provider import (
    MIN_DELETION_WINDOW_DAYS,
    PRODUCTION_DELETION_WINDOW_DAYS,
    ContextMismatchError,
    KeyProviderError,
    KeyState,
    KeyUnavailableError,
)

_STATES = {
    "Enabled": KeyState.ENABLED,
    "Disabled": KeyState.DISABLED,
    "PendingDeletion": KeyState.PENDING_DELETION,
    "PendingReplicaDeletion": KeyState.PENDING_DELETION,
    "Unavailable": KeyState.DELETED,
}
_UNAVAILABLE_CODES = {
    "DisabledException",
    "KMSInvalidStateException",
    "NotFoundException",
    "KeyUnavailableException",
}


def kms_alias(name: str) -> str:
    """AWS aliases must begin with ``alias/``; ``alias/aws/`` is reserved for AWS."""
    alias = name if name.startswith("alias/") else f"alias/{name}"
    if alias.startswith("alias/aws/"):
        msg = "aliases under alias/aws/ are reserved by AWS"
        raise KeyProviderError(msg)
    return alias


DESTRUCTIVE_ACTIONS = (
    "kms:ScheduleKeyDeletion",
    "kms:DisableKey",
    "kms:PutKeyPolicy",
    "kms:DeleteImportedKeyMaterial",
)


def kms_key_policy(account_id: str, destroyer_role_arn: str, key_admin_role_arn: str) -> str:
    """The key policy every organization key is born with (doc 12.5, KeyGuard preventive layer).

    The account root keeps IAM-delegated permissions (so the key can never be orphaned), and an
    explicit DENY on the four destructive actions applies to every principal except the two KeyGuard
    roles. A key policy deny beats any IAM allow, so a compromised service role cannot schedule a
    key's deletion.
    """
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "EnableIamPermissions",
                    "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
                    "Action": "kms:*",
                    "Resource": "*",
                },
                {
                    "Sid": "KeyGuardDenyDestructiveActions",
                    "Effect": "Deny",
                    "Principal": {"AWS": "*"},
                    "Action": list(DESTRUCTIVE_ACTIONS),
                    "Resource": "*",
                    "Condition": {
                        "StringNotEquals": {
                            "aws:PrincipalArn": [destroyer_role_arn, key_admin_role_arn]
                        }
                    },
                },
            ],
        }
    )


class AwsKmsProvider:
    """Symmetric organization keys in AWS KMS, with multi-Region replicas."""

    name = "aws"

    def __init__(self, region: str, *, key_policy: str | None = None) -> None:
        """Create the provider; ``key_policy`` (see ``kms_key_policy``) goes on every new key."""
        self._key_policy = key_policy
        self._kms: Any = boto3.client("kms", region_name=region)  # pyright: ignore[reportUnknownMemberType] - overloaded boto3 stubs
        self._region = region

    async def _run(self, operation: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        try:
            result: dict[str, Any] = await asyncio.to_thread(
                getattr(self._kms, operation), **kwargs
            )
        except ClientError as exc:
            response = cast("dict[str, Any]", exc.response)
            code = str(response.get("Error", {}).get("Code", ""))
            if code == "InvalidCiphertextException":
                msg = "encryption context mismatch or corrupt ciphertext"
                raise ContextMismatchError(msg) from exc
            if code in _UNAVAILABLE_CODES:
                msg = f"key unavailable: {code}"
                raise KeyUnavailableError(msg) from exc
            msg = f"KMS {operation} failed: {code}"
            raise KeyProviderError(msg) from exc
        return result

    async def create_key(self, alias: str) -> str:
        """Create a multi-Region symmetric key with an alias; returns the key ID."""
        created = await self._run(
            "create_key",
            KeySpec="SYMMETRIC_DEFAULT",
            KeyUsage="ENCRYPT_DECRYPT",
            MultiRegion=True,
            Tags=[
                {"TagKey": "project", "TagValue": "lmqa"}
            ],  # the IAM policy allows CreateKey only with this tag
            **(
                {"Policy": self._key_policy, "BypassPolicyLockoutSafetyCheck": False}
                if self._key_policy
                else {}
            ),
            Description=f"lmqa organization key {alias}",
        )
        key_id = str(created["KeyMetadata"]["KeyId"])
        await self._run("create_alias", AliasName=kms_alias(alias), TargetKeyId=key_id)
        return key_id

    async def create_drill_key(self, alias: str) -> str:
        """Create a key tagged ``drill`` so the policy lint may allow the 7 day minimum window."""
        key_id = await self.create_key(alias)
        await self._run(
            "tag_resource", KeyId=key_id, Tags=[{"TagKey": "drill", "TagValue": "true"}]
        )
        return key_id

    async def wrap(self, key_id: str, plaintext_key: bytes, context: dict[str, str]) -> bytes:
        """Encrypt a data key under ``key_id`` with an encryption context."""
        out = await self._run(
            "encrypt", KeyId=key_id, Plaintext=plaintext_key, EncryptionContext=context
        )
        return bytes(out["CiphertextBlob"])

    async def unwrap(self, key_id: str, wrapped: bytes, context: dict[str, str]) -> bytes:
        """Decrypt a wrapped data key; KMS checks the encryption context."""
        out = await self._run(
            "decrypt", KeyId=key_id, CiphertextBlob=wrapped, EncryptionContext=context
        )
        return bytes(out["Plaintext"])

    async def describe(self, key_id: str) -> KeyState:
        """The key's lifecycle state as KMS reports it."""
        out = await self._run("describe_key", KeyId=key_id)
        return _STATES.get(str(out["KeyMetadata"]["KeyState"]), KeyState.DISABLED)

    async def disable(self, key_id: str) -> None:
        """Disable the key (reversible)."""
        await self._run("disable_key", KeyId=key_id)

    async def enable(self, key_id: str) -> None:
        """Re-enable a disabled key."""
        await self._run("enable_key", KeyId=key_id)

    async def schedule_deletion(self, key_id: str, window_days: int) -> None:
        """Schedule deletion. Valid windows are 7 to 30 days; production uses 30."""
        if not MIN_DELETION_WINDOW_DAYS <= window_days <= PRODUCTION_DELETION_WINDOW_DAYS:
            msg = (
                f"deletion window must be {MIN_DELETION_WINDOW_DAYS} to "
                f"{PRODUCTION_DELETION_WINDOW_DAYS} days"
            )
            raise KeyProviderError(msg)
        await self._run("schedule_key_deletion", KeyId=key_id, PendingWindowInDays=window_days)

    async def cancel_deletion(self, key_id: str) -> None:
        """Cancel a scheduled deletion. KMS leaves the key disabled until it is enabled again."""
        await self._run("cancel_key_deletion", KeyId=key_id)
