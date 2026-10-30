"""AWS KMS behavior (doc 12.5, G1.11 AWS half, G1.12 windows). Needs real AWS credentials.

Marked ``live_aws``: it runs in CI with an assumed role (OIDC, no static keys) and locally only
when ``AWS_*`` credentials are present. ``make test`` excludes it; ``make gate`` includes it.
The first test needs no credentials: the window rule is enforced before any API call.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from lmqa_keys import (
    AwsKmsProvider,
    ContextMismatchError,
    KeyProviderError,
    KeyState,
    KeyUnavailableError,
)
from lmqa_keys.aws_kms import kms_alias

pytestmark = [pytest.mark.stage1]
REGION = os.environ.get("AWS_REGION", "us-east-1")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("given", "expected"),
    [("lmqa-org-1", "alias/lmqa-org-1"), ("alias/lmqa-org-1", "alias/lmqa-org-1")],
)
def test_alias_names_always_begin_with_alias_slash(given: str, expected: str) -> None:
    assert kms_alias(given) == expected


@pytest.mark.unit
def test_the_aws_reserved_alias_namespace_is_refused() -> None:
    with pytest.raises(KeyProviderError, match="reserved"):
        kms_alias("alias/aws/s3")


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("days", [-1, 0, 3, 6, 31, 365])
async def test_a_deletion_window_outside_7_to_30_days_is_refused_before_any_api_call(
    days: int,
) -> None:
    with pytest.raises(KeyProviderError, match="7 to 30"):
        await AwsKmsProvider(REGION).schedule_deletion("key-that-is-never-contacted", days)


@pytest.mark.integration
@pytest.mark.live_kms
@pytest.mark.live_aws
@pytest.mark.asyncio
async def test_g1_11_schedule_cancel_enable_round_trip_on_real_kms() -> None:
    kms = AwsKmsProvider(REGION)
    key_id = await kms.create_drill_key(
        f"alias/lmqa-drill-{uuid4()}"
    )  # the drill tag allows 7 days
    context = {"org_id": str(uuid4()), "purpose": "test"}
    wrapped = await kms.wrap(key_id, b"k" * 32, context)
    assert await kms.unwrap(key_id, wrapped, context) == b"k" * 32
    with pytest.raises(ContextMismatchError):
        await kms.unwrap(key_id, wrapped, {**context, "org_id": str(uuid4())})
    await kms.schedule_deletion(key_id, 7)
    assert await kms.describe(key_id) is KeyState.PENDING_DELETION
    with pytest.raises(KeyUnavailableError):
        await kms.unwrap(key_id, wrapped, context)
    await kms.cancel_deletion(key_id)
    assert await kms.describe(key_id) is KeyState.DISABLED
    await kms.enable(key_id)
    assert await kms.unwrap(key_id, wrapped, context) == b"k" * 32
    await kms.schedule_deletion(key_id, 7)  # leave nothing behind


@pytest.mark.unit
def test_every_organization_key_is_born_with_the_keyguard_deny_policy() -> None:
    import json  # noqa: PLC0415

    from lmqa_keys.aws_kms import DESTRUCTIVE_ACTIONS, kms_key_policy  # noqa: PLC0415

    destroyer = "arn:aws:iam::111122223333:role/keyguard-destroyer"
    admin = "arn:aws:iam::111122223333:role/key-admin"
    policy = json.loads(kms_key_policy("111122223333", destroyer, admin))
    by_sid = {s["Sid"]: s for s in policy["Statement"]}
    assert by_sid["EnableIamPermissions"]["Principal"] == {"AWS": "arn:aws:iam::111122223333:root"}
    deny = by_sid["KeyGuardDenyDestructiveActions"]
    assert deny["Effect"] == "Deny"
    assert deny["Principal"] == {"AWS": "*"}, "the deny applies to every principal"
    assert set(deny["Action"]) == set(DESTRUCTIVE_ACTIONS)
    assert set(deny["Condition"]["StringNotEquals"]["aws:PrincipalArn"]) == {destroyer, admin}
    assert "kms:Decrypt" not in deny["Action"], "ordinary cryptographic use is never denied"
