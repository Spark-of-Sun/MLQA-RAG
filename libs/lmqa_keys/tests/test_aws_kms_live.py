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

pytestmark = [pytest.mark.stage1]
REGION = os.environ.get("AWS_REGION", "us-east-1")


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
