"""Random organizations for differential tests (doc 10.3, 5.4).

Worlds are built by a superuser (BYPASSRLS) so any state can be placed directly; every READ
and WRITE under test goes through the real service roles. Worlds are seeded, so failures reproduce.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from lmqa_models import AccessContext, Grant, Role

if TYPE_CHECKING:
    import random

    import psycopg


@dataclass
class Doc:
    id: UUID
    owner: UUID
    matter: UUID | None
    visibility: str
    tier: int
    chunk_quarantined: bool


@dataclass
class World:
    org: UUID
    ws: UUID
    sa: UUID
    admin: UUID
    tenants: list[UUID]
    matters: list[UUID]
    docs: list[Doc]
    member_state: dict[UUID, str]
    ws_state: str
    org_state: str
    flag: bool
    walls: dict[UUID, set[UUID]] = field(default_factory=dict[UUID, set[UUID]])
    grants: dict[UUID, dict[UUID, Grant]] = field(default_factory=dict[UUID, dict[UUID, Grant]])
    emergency: dict[UUID, dict[UUID, datetime]] = field(
        default_factory=dict[UUID, dict[UUID, datetime]]
    )
    break_glass: bool = False

    def users(self) -> list[tuple[UUID, Role]]:
        return [(self.admin, Role.ADMIN), *[(t, Role.TENANT) for t in self.tenants]]


def _row(conn: psycopg.Connection, sql: str, *params: object) -> UUID:
    cur = conn.execute(sql, params)  # type: ignore[arg-type]
    got = cur.fetchone()
    assert got is not None
    return got[0]


def build_world(conn: psycopg.Connection, rng: random.Random, now: datetime) -> World:
    org_state = rng.choices(["active", "frozen"], [95, 5])[0]
    ws_state = rng.choices(["active", "frozen"], [90, 10])[0]
    org = _row(
        conn,
        "INSERT INTO orgs (name, deployment_type, state) VALUES ('w', 'both', %s) RETURNING id",
        org_state,
    )
    flag = rng.random() < 0.6
    ws = _row(
        conn,
        "INSERT INTO workspaces (org_id, state, admin_can_read_private) VALUES (%s, %s, %s) RETURNING id",
        org,
        ws_state,
        flag,
    )

    def user() -> UUID:
        return _row(
            conn, "INSERT INTO users (auth0_sub) VALUES (%s) RETURNING id", f"auth0|{uuid4().hex}"
        )

    sa, admin = user(), user()
    tenants = [user() for _ in range(rng.randint(3, 5))]
    member_state: dict[UUID, str] = {}
    conn.execute(
        "INSERT INTO memberships (user_id, org_id, role, state) VALUES (%s, %s, 'super_admin', 'active')",
        (sa, org),
    )
    for uid, role in [(admin, "admin"), *[(t, "tenant") for t in tenants]]:
        state = rng.choices(["active", "suspended", "removed"], [85, 10, 5])[0]
        member_state[uid] = state
        conn.execute(
            "INSERT INTO memberships (user_id, org_id, workspace_id, role, state) VALUES (%s, %s, %s, %s, %s)",
            (uid, org, ws, role, state),
        )
    matters = [
        _row(
            conn,
            "INSERT INTO matters (org_id, workspace_id, label) VALUES (%s, %s, 'm') RETURNING id",
            org,
            ws,
        )
        for _ in range(3)
    ]
    w = World(org, ws, sa, admin, tenants, matters, [], member_state, ws_state, org_state, flag)

    for uid, _role in w.users():
        w.walls[uid] = {m for m in matters if rng.random() < 0.18}
        for m in w.walls[uid]:
            conn.execute(
                "INSERT INTO matter_walls (org_id, workspace_id, matter_id, user_id, reason_code)"
                " VALUES (%s, %s, %s, %s, 'c')",
                (org, ws, m, uid),
            )
    for t in tenants:
        w.grants[t], w.emergency[t] = {}, {}
        for m in matters:
            if rng.random() < 0.6:
                expiry = rng.choice([None, now + timedelta(days=1), now - timedelta(days=1)])
                tier = rng.randint(1, 4)
                w.grants[t][m] = Grant(max_tier=tier, expires_at=expiry)
                conn.execute(
                    "INSERT INTO matter_grants (org_id, workspace_id, matter_id, user_id, max_tier, expires_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s)",
                    (org, ws, m, t, tier, expiry),
                )
            if rng.random() < 0.45:
                state = rng.choices(["active", "requested", "expired"], [75, 10, 15])[0]
                expiry = rng.choices(
                    [now + timedelta(hours=1), now - timedelta(minutes=5)], [80, 20]
                )[0]
                conn.execute(
                    "INSERT INTO access_sessions (org_id, workspace_id, user_id, kind, matter_id, state,"
                    " reason_code, expires_at) VALUES (%s, %s, %s, 'emergency', %s, %s, 'x', %s)",
                    (org, ws, t, m, state, expiry),
                )
                if state == "active" and expiry > now:
                    w.emergency[t][m] = expiry
    if rng.random() < 0.85:  # break-glass is a rare combination; weight it so rule 7 is exercised
        state = rng.choices(["active", "requested", "revoked"], [80, 10, 10])[0]
        expiry = rng.choices([now + timedelta(hours=1), now - timedelta(minutes=5)], [80, 20])[0]
        conn.execute(
            "INSERT INTO access_sessions (org_id, workspace_id, user_id, kind, state, reason_code, expires_at)"
            " VALUES (%s, %s, %s, 'break_glass', %s, 'x', %s)",
            (org, ws, admin, state, expiry),
        )
        w.break_glass = state == "active" and expiry > now

    owners = [admin, *tenants]
    for _ in range(rng.randint(14, 24)):
        owner = rng.choice(owners)
        visibility = rng.choice(["private", "matter"])
        matter = rng.choice(matters) if visibility == "matter" else rng.choice([None, *matters])
        tier = rng.randint(1, 4)
        quarantined = rng.random() < 0.08
        doc = _row(
            conn,
            "INSERT INTO documents (org_id, workspace_id, owner_user_id, matter_id, title_ciphertext, visibility,"
            " confidentiality_tier, status) VALUES (%s, %s, %s, %s, %s, %s, %s, 'indexed') RETURNING id",
            org,
            ws,
            owner,
            matter,
            os.urandom(8),
            visibility,
            tier,
        )
        conn.execute(
            "INSERT INTO chunks (org_id, workspace_id, doc_id, doc_version, ordinal, owner_user_id, matter_id,"
            " visibility, confidentiality_tier, kind, page_start, page_end, text_ciphertext, text_sha256,"
            " token_count, quarantined) VALUES (%s, %s, %s, 1, 0, %s, %s, %s, %s, 'paragraph', 1, 1, %s, %s, 9, %s)",
            (
                org,
                ws,
                doc,
                owner,
                matter,
                visibility,
                tier,
                os.urandom(8),
                os.urandom(8).hex(),
                quarantined,
            ),
        )
        w.docs.append(Doc(doc, owner, matter, visibility, tier, quarantined))
    return w


def oracle_context(w: World, user: UUID, role: Role, now: datetime) -> AccessContext:
    return AccessContext(
        user_id=user,
        role=role,
        now=now,
        membership_active=w.member_state[user] == "active",
        workspace_active=w.ws_state == "active",
        org_active=w.org_state == "active",
        walls=frozenset(w.walls.get(user, set())),
        grants=dict(w.grants.get(user, {})),
        emergency=dict(w.emergency.get(user, {})),
        admin_can_read_private=w.flag,
        break_glass_active=w.break_glass and role is Role.ADMIN,
    )


def oracle_may_upload(ctx: AccessContext, matter: UUID | None, tier: int) -> bool:
    if not (ctx.membership_active and ctx.workspace_active and ctx.org_active):
        return False
    if matter is None:
        return True
    if matter in ctx.walls:
        return False
    if ctx.role is Role.ADMIN:
        return True
    grant = ctx.grants.get(matter)
    return grant is not None and grant.is_active(ctx.now) and grant.max_tier >= tier
