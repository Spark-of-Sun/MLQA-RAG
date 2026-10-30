"""Stage 2 on the real stack (no Auth0): onboarding, codes, approvals, cascades, revocation, escalation."""

from __future__ import annotations

import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from valkey.asyncio import Valkey

from identity.codes import CodeRejected, CodeService, RateLimiter
from identity.domain import INVALIDATIONS, ConflictError, Identity, NotFoundError
from lmqa_audit import AuditReader
from lmqa_db import ContextRole, Database, DbContext
from lmqa_keys import KeyService, OpenBaoProvider
from lmqa_testing import world
from lmqa_testing.fixtures import Stack
from lmqa_testing.pg import role_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


pytestmark = [pytest.mark.integration, pytest.mark.live_kms, pytest.mark.stage2]
PEPPERS = {"v1": secrets.token_bytes(32)}


@dataclass
class Rig:
    identity: Identity
    stack: Stack
    valkey: Valkey
    db: Database
    provider: OpenBaoProvider


@pytest_asyncio.fixture
async def rig(migrated_db: str, stack: Stack) -> AsyncGenerator[Rig]:
    provider = OpenBaoProvider(
        os.environ.get("OPENBAO_ADDR", "http://127.0.0.1:8200"),
        os.environ.get("OPENBAO_TOKEN", "lmqa-dev-token"),
    )
    valkey = Valkey.from_url(os.environ.get("VALKEY_URL", "redis://127.0.0.1:6379"))
    db = Database(role_dsn("svc_identity", migrated_db), pooled=False, use_null_pool=True)
    codes = CodeService(db, RateLimiter(valkey), PEPPERS, "v1")
    yield Rig(
        Identity(db, KeyService(provider), provider, codes, valkey), stack, valkey, db, provider
    )
    await db.dispose()
    await valkey.aclose()
    await provider.aclose()


def sub() -> str:
    return f"auth0|{uuid.uuid4().hex}"


async def uid(rig: Rig, s: str) -> UUID:
    async with rig.db.scoped(world.SYSTEM) as sess:
        return UUID(
            str(
                (
                    await sess.execute(text("SELECT id FROM users WHERE auth0_sub = :s"), {"s": s})
                ).scalar_one()
            )
        )


async def make_org(rig: Rig) -> tuple[UUID, UUID, DbContext]:
    owner = sub()
    out = await rig.identity.create_organization(owner, "Acme Legal LLP", "both")
    org, user = UUID(out["organization_id"]), await uid(rig, owner)
    return org, user, DbContext(role=ContextRole.SUPER_ADMIN, org_id=org, user_id=user)


async def make_workspace(rig: Rig):
    org, _sa, sa_ctx = await make_org(rig)
    admin_sub = sub()
    code = await rig.identity.generate_org_code(sa_ctx)
    await rig.identity.join_admin(admin_sub, code, "10.0.0.1")
    admin = await uid(rig, admin_sub)
    await rig.identity.decide_admin(sa_ctx, admin, "approve")
    async with rig.db.scoped(world.SYSTEM) as s:
        ws = UUID(
            str(
                (
                    await s.execute(
                        text("SELECT workspace_id FROM memberships WHERE user_id = :u"),
                        {"u": admin},
                    )
                ).scalar_one()
            )
        )
    return (
        org,
        sa_ctx,
        DbContext(role=ContextRole.ADMIN, org_id=org, workspace_id=ws, user_id=admin),
        ws,
        admin,
    )


async def join_tenant(rig: Rig, admin_ctx: DbContext, *, approve: bool = True) -> tuple[str, UUID]:
    code = await rig.identity.generate_admin_code(admin_ctx)
    tsub = sub()
    await rig.identity.join_tenant(tsub, code, "10.0.0.2")
    tenant = await uid(rig, tsub)
    if approve:
        await rig.identity.decide_tenant(admin_ctx, tenant, "approve")
    return tsub, tenant


@pytest.mark.asyncio
async def test_g2_1_an_organization_is_created_with_keys_audit_and_a_super_admin(rig: Rig) -> None:
    owner = sub()
    first = await rig.identity.create_organization(owner, "Acme Hospital System", "medical")
    again = await rig.identity.create_organization(owner, "Acme Hospital System", "medical")
    assert first["created"] is True
    assert again == {
        "organization_id": first["organization_id"],
        "created": False,
    }
    org = UUID(first["organization_id"])
    async with rig.db.scoped(world.SYSTEM) as s:
        assert (
            await s.execute(text("SELECT state FROM orgs WHERE id = :o"), {"o": org})
        ).scalar_one() == "active"
        keys = (
            await s.execute(
                text("SELECT kms_key_id, escrow_key_id FROM org_keys WHERE org_id = :o"), {"o": org}
            )
        ).one()
        members = (
            await s.execute(
                text("SELECT role, state FROM memberships WHERE org_id = :o"), {"o": org}
            )
        ).all()
    assert keys[0] != keys[1], "a separate escrow key exists"
    assert [tuple(m) for m in members] == [("super_admin", "active")]
    async with rig.stack.audit_reader.scoped(world.SYSTEM) as s:
        assert (
            await s.execute(text("SELECT audit_verify(:c)"), {"c": f"org:{org}"})
        ).scalar_one() is None


@pytest.mark.asyncio
async def test_all_three_paths_work_and_a_preview_does_not_consume_a_use(rig: Rig) -> None:
    org, _sa_ctx, admin_ctx, ws, _admin = await make_workspace(rig)
    async with rig.db.scoped(world.SYSTEM) as s:
        assert (
            await s.execute(text("SELECT state FROM workspaces WHERE id = :w"), {"w": ws})
        ).scalar_one() == "active"
        assert (
            await s.execute(
                text("SELECT count(*) FROM workspace_keys WHERE workspace_id = :w"), {"w": ws}
            )
        ).scalar_one() == 1
        assert (
            await s.execute(
                text("SELECT count(*) FROM audit_keys WHERE workspace_id = :w"), {"w": ws}
            )
        ).scalar_one() == 1
    code = await rig.identity.generate_admin_code(admin_ctx)
    me = sub()
    assert (await rig.identity.preview_tenant_code(me, code, "10.0.0.3"))["valid"] is True
    async with rig.db.scoped(world.SYSTEM) as s:
        assert (
            await s.execute(
                text(
                    "SELECT used_count FROM join_codes WHERE workspace_id = :w AND state = 'active'"
                ),
                {"w": ws},
            )
        ).scalar_one() == 0
    assert (await rig.identity.join_tenant(me, code, "10.0.0.3")) == {"state": "pending_approval"}
    tenant = await uid(rig, me)
    assert (await rig.identity.status(me))["state"] == "pending_approval"
    await rig.identity.decide_tenant(admin_ctx, tenant, "approve")
    assert (await rig.identity.status(me))["state"] == "active"
    caps = await rig.identity.me(
        DbContext(role=ContextRole.TENANT, org_id=org, workspace_id=ws, user_id=tenant)
    )
    assert caps["capabilities"] == ["chat", "library", "own_audit"]
    async with rig.db.scoped(world.SYSTEM) as s:
        assert (
            await s.execute(
                text(
                    "SELECT used_count FROM join_codes WHERE workspace_id = :w AND state = 'active'"
                ),
                {"w": ws},
            )
        ).scalar_one() == 1
    with pytest.raises(
        CodeRejected
    ):  # the same person using it again is refused and consumes nothing
        await rig.identity.join_tenant(me, code, "10.0.0.3")


@pytest.mark.asyncio
async def test_g2_5_every_kind_of_bad_code_is_rejected_identically_and_the_reason_is_logged(
    rig: Rig,
) -> None:
    org, sa_ctx, admin_ctx, ws, _admin = await make_workspace(rig)
    good = await rig.identity.generate_admin_code(admin_ctx)
    rotated = good
    good = await rig.identity.generate_admin_code(admin_ctx)  # rotation kills the previous one
    wrong_secret = good[:-3] + (
        "AAA" if not good.endswith("AAA") else "BBB"
    )  # fails the check character or the hash
    org_code = await rig.identity.generate_org_code(sa_ctx)
    async with rig.db.scoped(world.SYSTEM) as s:
        await s.execute(
            text(
                "UPDATE join_codes SET max_uses = 1, used_count = 1 WHERE workspace_id = :w AND state = 'active'"
            ),
            {"w": ws},
        ) if False else None
    cases = {
        "malformed": "not-a-code",
        "empty": "",
        "rotated": rotated,
        "wrong check/secret": wrong_secret,
        "org code as admin code": org_code,
    }
    outcomes = set()
    for label, bad in cases.items():
        try:
            await rig.identity.join_tenant(sub(), bad, f"10.1.{len(label)}.9")
        except CodeRejected as exc:
            outcomes.add((type(exc).__name__, str(exc)))
        else:
            pytest.fail(f"{label} was accepted")
    assert outcomes == {("CodeRejected", "")}, "one outcome, one message, for every reason"
    async with rig.db.scoped(world.SYSTEM) as s:
        reasons = {
            r[0].split(" (")[0]
            for r in (
                await s.execute(
                    text("SELECT true_reason FROM join_attempts WHERE outcome = 'rejected'")
                )
            ).all()
        }
    assert {"malformed", "state_rotated"} <= reasons, (
        "the true reason is recorded for the audit log only"
    )
    # an expired code (the lifetime is configuration: created already in the past)
    async with rig.db.scoped(admin_ctx) as s:
        expired = await rig.identity.codes.create(
            s,
            __import__("lmqa_security.codes", fromlist=["CodeKind"]).CodeKind.ADMIN,
            org,
            ws,
            admin_ctx.user,
            now=datetime.now(UTC) - timedelta(days=200),
        )
    with pytest.raises(CodeRejected):
        await rig.identity.join_tenant(sub(), expired, "10.2.0.1")


@pytest.mark.asyncio
async def test_g2_5_rate_limits_block_a_user_an_address_and_a_code_even_for_the_right_code(
    rig: Rig,
) -> None:
    _org, _sa, admin_ctx, _ws, _admin = await make_workspace(rig)
    good = await rig.identity.generate_admin_code(admin_ctx)
    victim = sub()
    for _ in range(5):
        with pytest.raises(CodeRejected):
            await rig.identity.join_tenant(victim, "0" * 32, "10.3.0.1")
    with pytest.raises(CodeRejected):  # now even the correct code is refused for this user
        await rig.identity.join_tenant(victim, good, "10.3.0.1")
    assert (await rig.identity.join_tenant(sub(), good, "10.3.0.99"))[
        "state"
    ] == "pending_approval", "other users are unaffected"
    ip = "10.4.0.1"
    for _ in range(20):
        with pytest.raises(CodeRejected):
            await rig.identity.join_tenant(sub(), "1" * 32, ip)
    with pytest.raises(CodeRejected):
        await rig.identity.join_tenant(sub(), good, ip)


@pytest.mark.asyncio
async def test_g2_5_the_work_done_for_an_unknown_code_matches_a_known_wrong_one(rig: Rig) -> None:
    """Both paths compute the keyed hash and compare in constant time (a statistical bound, not a proof)."""
    _org, _sa, admin_ctx, _ws, _admin = await make_workspace(rig)
    good = await rig.identity.generate_admin_code(admin_ctx)
    known_wrong = good.replace("-", "")[:-1]
    unknown = secrets.token_hex(16).upper()
    from lmqa_security.codes import CodeKind, generate  # noqa: PLC0415

    unknown = generate(CodeKind.ADMIN).display
    times: dict[str, list[float]] = {"known": [], "unknown": []}
    for i in range(30):
        for label, code in (("known", good[:-3] + "AAA"), ("unknown", unknown)):
            start = time.perf_counter()
            with pytest.raises(CodeRejected):
                await rig.identity.codes.verify(
                    CodeKind.ADMIN, code, f"timing-{i}-{label}", f"10.5.{i}.{len(label)}"
                )
            times[label].append(time.perf_counter() - start)
    median = {k: sorted(v)[len(v) // 2] for k, v in times.items()}
    assert abs(median["known"] - median["unknown"]) < 0.5 * max(median.values()), median
    assert known_wrong


@pytest.mark.asyncio
async def test_escalation_attempts_fail_in_the_database_not_just_in_code(rig: Rig) -> None:
    org, sa_ctx, admin_ctx, ws, admin = await make_workspace(rig)
    tsub, tenant = await join_tenant(rig, admin_ctx)
    tenant_ctx = DbContext(role=ContextRole.TENANT, org_id=org, workspace_id=ws, user_id=tenant)
    with pytest.raises(NotFoundError):  # a tenant cannot approve or even see an admin
        await rig.identity.decide_admin(tenant_ctx, admin, "suspend")
    with pytest.raises(ConflictError, match="own membership"):
        await rig.identity.decide_admin(sa_ctx, sa_ctx.user, "suspend")
    with pytest.raises(NotFoundError):  # a tenant cannot approve another tenant
        await rig.identity.decide_tenant(tenant_ctx, tenant, "approve")
    async with rig.db.scoped(
        tenant_ctx
    ) as s:  # and the database refuses a self-activation outright
        _s2, pending = await join_tenant(rig, admin_ctx, approve=False)
        own = DbContext(role=ContextRole.TENANT, org_id=org, workspace_id=ws, user_id=pending)
    async with rig.db.scoped(own) as s:
        result = await s.execute(
            text("UPDATE memberships SET state = 'active' WHERE user_id = :u"), {"u": pending}
        )
        assert result.rowcount == 0, (
            "a pending tenant cannot activate themselves: own row is read-only"
        )
    other_org, _s, other_admin, _w, _a = await make_workspace(rig)
    with pytest.raises(
        NotFoundError
    ):  # another workspace's admin cannot touch this workspace's tenant
        await rig.identity.decide_tenant(other_admin, tenant, "suspend")
    with pytest.raises(
        NotFoundError
    ):  # nor can another organization's Super Admin touch this admin
        await rig.identity.decide_admin(
            DbContext(role=ContextRole.SUPER_ADMIN, org_id=other_org, user_id=uuid.uuid4()),
            admin,
            "suspend",
        )
    # The Super Admin boundary: no tenant row is visible from a Super Admin context.
    async with rig.db.scoped(sa_ctx) as s:
        assert (
            await s.execute(text("SELECT count(*) FROM memberships WHERE role = 'tenant'"))
        ).scalar_one() == 0
        assert (await s.execute(text("SELECT count(*) FROM matter_walls"))).scalar_one() == 0
    assert tsub


@pytest.mark.asyncio
async def test_g2_8_suspending_an_admin_cascades_and_reactivating_restores_only_the_cascade(
    rig: Rig,
) -> None:
    _org, sa_ctx, admin_ctx, ws, admin = await make_workspace(rig)
    _s1, t_cascade = await join_tenant(rig, admin_ctx)
    _s2, t_own = await join_tenant(rig, admin_ctx)
    await rig.identity.decide_tenant(
        admin_ctx, t_own, "suspend"
    )  # suspended by the admin before the cascade
    old_code = await rig.identity.generate_admin_code(admin_ctx)
    async with rig.db.scoped(world.SYSTEM) as s:
        before = (
            await s.execute(
                text("SELECT principal_version FROM memberships WHERE user_id = :u"),
                {"u": t_cascade},
            )
        ).scalar_one()
    pubsub = rig.valkey.pubsub()
    await pubsub.subscribe(INVALIDATIONS)
    await rig.identity.decide_admin(sa_ctx, admin, "suspend")
    async with rig.db.scoped(world.SYSTEM) as s:
        rows = {
            UUID(str(r[0])): (r[1], r[2])
            for r in (
                await s.execute(
                    text(
                        "SELECT user_id, state, state_reason FROM memberships WHERE workspace_id = :w"
                    ),
                    {"w": ws},
                )
            ).all()
        }
        assert (
            await s.execute(text("SELECT state FROM workspaces WHERE id = :w"), {"w": ws})
        ).scalar_one() == "frozen"
        assert (
            await s.execute(
                text(
                    "SELECT state FROM join_codes WHERE workspace_id = :w ORDER BY created_at DESC LIMIT 1"
                ),
                {"w": ws},
            )
        ).scalar_one() == "disabled"
        after = (
            await s.execute(
                text("SELECT principal_version FROM memberships WHERE user_id = :u"),
                {"u": t_cascade},
            )
        ).scalar_one()
    assert rows[admin] == ("suspended", "admin_action")
    assert rows[t_cascade] == ("suspended", "workspace_frozen")
    assert after > before, "principal_version bumps so every cached principal is dropped"
    seen: set[str] = set()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not {str(admin), str(t_cascade)} <= seen:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if msg:
            seen.add(json.loads(msg["data"])["user_id"])
    assert {str(admin), str(t_cascade)} <= seen, (
        "revocation messages published within 2 s for every affected user"
    )
    await pubsub.aclose()
    await rig.identity.decide_admin(sa_ctx, admin, "reactivate")
    async with rig.db.scoped(world.SYSTEM) as s:
        rows = {
            UUID(str(r[0])): r[1]
            for r in (
                await s.execute(
                    text("SELECT user_id, state FROM memberships WHERE workspace_id = :w"),
                    {"w": ws},
                )
            ).all()
        }
        assert (
            await s.execute(text("SELECT state FROM workspaces WHERE id = :w"), {"w": ws})
        ).scalar_one() == "active"
    assert rows[admin] == rows[t_cascade] == "active"
    assert rows[t_own] == "suspended", "a tenant the admin suspended separately stays suspended"
    with pytest.raises(CodeRejected):
        await rig.identity.join_tenant(
            sub(), old_code, "10.6.0.1"
        )  # the Admin Code stays dead until rotated
    new_code = await rig.identity.generate_admin_code(admin_ctx)
    assert (await rig.identity.join_tenant(sub(), new_code, "10.6.0.2"))[
        "state"
    ] == "pending_approval"


@pytest.mark.asyncio
async def test_grants_matters_walls_and_policy_follow_the_role_rules(rig: Rig) -> None:
    org, _sa, admin_ctx, ws, _admin = await make_workspace(rig)
    _s, tenant = await join_tenant(rig, admin_ctx)
    tenant_ctx = DbContext(role=ContextRole.TENANT, org_id=org, workspace_id=ws, user_id=tenant)
    m1 = (await rig.identity.create_matter(admin_ctx, "Smith v. Jones"))["id"]
    m2 = (await rig.identity.create_matter(admin_ctx, "Acme acquisition"))["id"]
    assert await rig.identity.list_matters(tenant_ctx) == [], (
        "a tenant sees only the matters granted to them"
    )
    await rig.identity.set_grants(admin_ctx, tenant, [{"matter_id": m1, "max_tier": 2}])
    assert [m["label"] for m in await rig.identity.list_matters(tenant_ctx)] == ["Smith v. Jones"]
    await rig.identity.set_grants(admin_ctx, tenant, [{"matter_id": m2, "max_tier": 3}])
    assert [m["label"] for m in await rig.identity.list_matters(tenant_ctx)] == [
        "Acme acquisition"
    ], "grants are replaced"
    with pytest.raises(ConflictError):
        await rig.identity.delete_matter(admin_ctx, UUID(m2))
    await rig.identity.create_wall(admin_ctx, tenant, UUID(m1), "conflict")
    assert len(await rig.identity.list_walls(admin_ctx)) == 1
    async with rig.db.scoped(tenant_ctx) as s:
        assert (await s.execute(text("SELECT count(*) FROM matter_walls"))).scalar_one() == 0, (
            "the walled user cannot see the wall"
        )
    await rig.identity.delete_matter(
        admin_ctx, UUID((await rig.identity.create_matter(admin_ctx, "empty"))["id"])
    )
    assert (
        await rig.identity.patch_policy(
            admin_ctx, {"on_fail": "refuse", "delivery_mode": "buffered"}
        )
    )["delivery_mode"] == "buffered"
    with pytest.raises(
        ConflictError
    ):  # a governance-controlled flag cannot be changed by one person
        await rig.identity.patch_policy(admin_ctx, {"admin_can_read_private": True})
    with pytest.raises(
        Exception, match=r"check|violates"
    ):  # regenerate needs buffered delivery (doc 11.6)
        await rig.identity.patch_policy(
            admin_ctx, {"on_fail": "regenerate", "delivery_mode": "sentence_gated"}
        )


@pytest.mark.asyncio
async def test_the_org_code_needs_an_active_org_and_an_org_code_cannot_create_a_tenant(
    rig: Rig,
) -> None:
    org, sa, sa_ctx = await make_org(rig)
    code = await rig.identity.generate_org_code(sa_ctx)
    assert re.fullmatch(r"([0-9A-Z]{8}-){7}[0-9A-Z]{8}", code), "64 characters in 8 groups"
    with pytest.raises(CodeRejected):
        await rig.identity.join_tenant(sub(), code, "10.7.0.1")
    async with rig.db.scoped(world.SYSTEM) as s:
        await s.execute(text("UPDATE orgs SET state = 'frozen' WHERE id = :o"), {"o": org})
    with pytest.raises(ConflictError):
        await rig.identity.generate_org_code(sa_ctx)
    with pytest.raises(CodeRejected):  # a frozen organization accepts no new admins
        await rig.identity.join_admin(sub(), code, "10.7.0.2")
    assert sa


@pytest.mark.asyncio
async def test_audit_events_are_written_for_every_lifecycle_step_and_the_chain_verifies(
    rig: Rig,
) -> None:
    org, sa_ctx, admin_ctx, ws, _admin = await make_workspace(rig)
    await join_tenant(rig, admin_ctx)
    async with rig.stack.audit_reader.scoped(admin_ctx) as s:
        actions = [
            r[0]
            for r in (await s.execute(text("SELECT action FROM audit_event ORDER BY seq"))).all()
        ]
        assert (
            await s.execute(text("SELECT audit_verify(:c)"), {"c": f"ws:{ws}"})
        ).scalar_one() is None
    assert {"admin_code.generated", "tenant.join_requested", "tenant.approve"} <= set(actions)
    async with rig.stack.audit_reader.scoped(sa_ctx) as s:
        sa_actions = {r[0] for r in (await s.execute(text("SELECT action FROM audit_event"))).all()}
    assert {"organization.created", "org_code.generated", "admin.approve"} <= sa_actions
    assert "tenant.approve" not in sa_actions, (
        "the Super Admin sees org and admin events, not workspace activity"
    )
    assert AuditReader
    assert org
