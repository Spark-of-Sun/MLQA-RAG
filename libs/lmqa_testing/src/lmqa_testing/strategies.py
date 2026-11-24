"""Shared Hypothesis strategies for the property tests (design, Testing strategy; R-4.5, R-95).

Generic building blocks only: access worlds with their principals and documents, operations, Organization and Admin
Codes, answer sentences carrying numbers and citation tags, audit event sequences and timed attempt sequences. The
properties themselves live with the tests that use them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hypothesis import strategies as st

from lmqa_testing.oracle import OPERATIONS, Document, Principal, World

__all__ = [
    "CROCKFORD",
    "Attempt",
    "AuditEvent",
    "Sentence",
    "audit_event_sequences",
    "check_char",
    "codes",
    "corrupted_codes",
    "documents",
    "operations",
    "principals",
    "scenarios",
    "sentences",
    "timed_attempt_sequences",
    "worlds",
]

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LAYOUT = {
    "org": (8, 55),
    "admin": (8, 23),
}  # (lookup ID, secret); one Luhn mod-32 check character follows
TAG_FORMAT = "[chunk_{n}]"  # design §9.4; the MVP uses [S{n}] (Q-12)
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_MOSTLY_TRUE = st.sampled_from((True, True, True, False))
_WINDOW = (
    48 * 3600
)  # expiries fall within two days either side of `now`, `now` itself included (expired)


def _uid(kind: int, n: int) -> str:
    """A stable, readable UUID: the first field names the kind of entity, the last the ordinal."""
    return str(uuid.UUID(int=(kind << 96) | n))


# --- access worlds (Property 1 and the isolation suite) -------------------------------------------------------------


@st.composite
def worlds(  # noqa: C901, PLR0913 - one nested loop per entity kind
    draw: st.DrawFn,
    *,
    max_orgs: int = 2,
    max_workspaces: int = 2,
    max_tenants: int = 3,
    max_matters: int = 3,
    max_documents: int = 6,
) -> World:
    """A world of organizations, workspaces, members in every state, matters, grants, walls, emergency exceptions,
    break-glass sessions and documents in every visibility and tier, plus a super_admin and an operator principal."""
    now = draw(st.datetimes(min_value=_EPOCH.replace(tzinfo=None), timezones=st.just(UTC))).replace(
        microsecond=0
    )

    def around() -> datetime:
        return now + timedelta(seconds=draw(st.integers(-_WINDOW, _WINDOW)))

    w = World(now=now)
    people: list[Principal] = []
    docs: list[Document] = []
    counter = iter(range(1, 1 << 30))
    for _ in range(draw(st.integers(1, max_orgs))):
        org_kind = draw(st.sampled_from(("legal", "medical", "both")))
        org_active = draw(_MOSTLY_TRUE)
        for _ in range(draw(st.integers(1, max_workspaces))):
            ws = _uid(2, next(counter))
            ws_active = draw(_MOSTLY_TRUE)
            w.admin_can_read_private[ws] = draw(st.booleans())
            w.emergency_enabled[ws] = org_kind != "legal" and draw(st.booleans())
            members = [
                Principal(
                    _uid(3, next(counter)),
                    role,
                    ws,
                    draw(_MOSTLY_TRUE),
                    ws_active,
                    org_active,
                    org_kind,
                )
                for role in ["admin"] + ["tenant"] * draw(st.integers(1, max_tenants))
            ]
            matters = [_uid(4, next(counter)) for _ in range(draw(st.integers(0, max_matters)))]
            for m in matters:
                for p in members:
                    if draw(st.integers(0, 4)) == 0:
                        w.walls.add((p.user_id, m))
                    if p.role != "tenant":
                        continue
                    if draw(st.booleans()):
                        w.grants[(p.user_id, m)] = (
                            draw(st.integers(1, 4)),
                            None if draw(st.booleans()) else around(),
                        )
                    if draw(st.integers(0, 3)) == 0:
                        w.emergency[(p.user_id, m)] = (draw(st.integers(1, 4)), around())
            if draw(st.booleans()):
                w.break_glass[members[0].user_id] = around()
            for _ in range(draw(st.integers(1, max_documents))):
                matter = draw(st.none() | st.sampled_from(matters)) if matters else None
                # CHECK documents_matter_visibility: visibility `matter` needs a matter_id (R-4.2).
                visibility = draw(st.sampled_from(("private", "matter"))) if matter else "private"
                owner = draw(st.sampled_from(members)).user_id
                docs.append(
                    Document(
                        _uid(5, next(counter)),
                        ws,
                        owner,
                        visibility,
                        matter,
                        draw(st.integers(1, 4)),
                    )
                )
            people.extend(members)
    people.append(Principal(_uid(1, next(counter)), "super_admin", None, True, True, True))
    people.append(Principal(_uid(1, next(counter)), "operator", None, True, True, True))
    w.principals = tuple(people)
    w.documents = tuple(docs)
    return w


def principals(world: World) -> st.SearchStrategy[Principal]:
    return st.sampled_from(world.principals)


def documents(world: World) -> st.SearchStrategy[Document]:
    return st.sampled_from(world.documents)


def operations() -> st.SearchStrategy[str]:
    return st.sampled_from(OPERATIONS)


@st.composite
def scenarios(draw: st.DrawFn, **world_kwargs: int) -> tuple[World, Principal, Document, str]:
    """One access question: (world, principal, document, operation)."""
    w = draw(worlds(**world_kwargs))
    return w, draw(principals(w)), draw(documents(w)), draw(operations())


# --- Organization and Admin Codes (R-16.1) --------------------------------------------------------------------------


def check_char(payload: str, alphabet: str = CROCKFORD) -> str:
    """Luhn mod N check character over `payload` (here N = 32, Crockford Base32)."""
    n, factor, total = len(alphabet), 2, 0
    for ch in reversed(payload):
        addend = factor * alphabet.index(ch)
        factor = 1 if factor == 2 else 2
        total += addend // n + addend % n
    return alphabet[(n - total % n) % n]


def codes(kind: str = "org") -> st.SearchStrategy[str]:
    """Well-formed codes: lookup ID, secret and check character, upper-case Crockford Base32, ungrouped."""
    lookup, secret = CODE_LAYOUT[kind]
    body = st.text(alphabet=CROCKFORD, min_size=lookup + secret, max_size=lookup + secret)
    return body.map(lambda b: b + check_char(b))


@st.composite
def corrupted_codes(draw: st.DrawFn, kind: str = "org") -> str:
    """A well-formed code with exactly one character substituted; Luhn mod N rejects every such code."""
    code = draw(codes(kind))
    i = draw(st.integers(0, len(code) - 1))
    ch = draw(st.sampled_from(CROCKFORD).filter(lambda c: c != code[i]))
    return code[:i] + ch + code[i + 1 :]


# --- answer sentences with numbers and citation tags (Validator properties) ----------------------------------------


@dataclass(frozen=True)
class Sentence:
    text: str
    numbers: tuple[str, ...]  # each number exactly as it appears in `text`
    tags: tuple[int, ...]  # chunk ordinals cited, in order


_WORDS = (
    "the",
    "patient",
    "court",
    "held",
    "dose",
    "was",
    "within",
    "section",
    "notice",
    "days",
    "claim",
    "rate",
)
_NUMBERS = st.one_of(
    st.integers(0, 10_000).map(str),
    st.integers(1_000, 9_999_999).map(lambda n: f"{n:,}"),
    st.decimals(0, 1000, places=2, allow_nan=False, allow_infinity=False).map(str),
    st.integers(0, 100).map(lambda n: f"{n}%"),
)


@st.composite
def sentences(
    draw: st.DrawFn,
    *,
    max_numbers: int = 3,
    max_tags: int = 2,
    max_chunk: int = 8,
    tag_format: str = TAG_FORMAT,
) -> Sentence:
    """A sentence of plain words with zero or more numbers mixed in and zero or more citation tags before the stop."""
    words = draw(st.lists(st.sampled_from(_WORDS), min_size=1, max_size=10))
    numbers = draw(st.lists(_NUMBERS, max_size=max_numbers))
    for num in numbers:
        words.insert(draw(st.integers(0, len(words))), num)
    tags = draw(st.lists(st.integers(1, max_chunk), max_size=max_tags))
    text = " ".join(words).capitalize() + "".join(" " + tag_format.format(n=t) for t in tags) + "."
    return Sentence(text, tuple(numbers), tuple(tags))


# --- audit event sequences (R-60, R-61) -----------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEvent:
    id: str
    ts: datetime
    org_id: str
    workspace_id: str | None  # None on the organization's control-plane chain
    actor_id: str
    actor_role: str
    action: str
    target_ids: tuple[str, ...]
    outcome: str
    reason_code: str | None
    request_id: str
    ip: str
    user_agent: str
    scope: str


_ACTIONS = (
    "document.upload",
    "query.run",
    "grant.create",
    "wall.create",
    "code.rotate",
    "export.create",
)


@st.composite
def audit_event_sequences(
    draw: st.DrawFn, *, min_size: int = 1, max_size: int = 20
) -> list[AuditEvent]:
    """Events for one chain (one workspace, or the control plane when workspace_id is None), timestamps non-decreasing.
    `prev_hash` and `hash` are left to the writer under test."""
    org = _uid(6, draw(st.integers(1, 3)))
    workspace = draw(st.none() | st.integers(1, 3).map(lambda n: _uid(7, n)))
    t = draw(st.datetimes(min_value=_EPOCH.replace(tzinfo=None), timezones=st.just(UTC)))
    events = []
    for i in range(draw(st.integers(min_size, max_size))):
        t += timedelta(milliseconds=draw(st.integers(0, 60_000)))
        outcome = draw(st.sampled_from(("allow", "deny", "error")))
        events.append(
            AuditEvent(
                id=_uid(8, i + 1),
                ts=t,
                org_id=org,
                workspace_id=workspace,
                actor_id=_uid(3, draw(st.integers(1, 4))),
                actor_role=draw(st.sampled_from(("super_admin", "admin", "tenant"))),
                action=draw(st.sampled_from(_ACTIONS)),
                target_ids=tuple(
                    _uid(9, n) for n in draw(st.lists(st.integers(1, 50), max_size=3))
                ),
                outcome=outcome,
                reason_code=None
                if outcome == "allow"
                else draw(st.sampled_from(("not_found", "forbidden", "rate"))),
                request_id=_uid(10, draw(st.integers(1, 1 << 20))),
                ip=draw(st.ip_addresses()).exploded,
                user_agent=draw(st.sampled_from(("Mozilla/5.0", "lmqa-cli/1.0", "curl/8.5"))),
                scope="workspace" if workspace else "control_plane",
            )
        )
    return events


# --- timed attempt sequences (rate limits, lockouts, code redemption) ---------------------------------------------


@dataclass(frozen=True)
class Attempt:
    at: datetime
    key: str  # the rate-limit key: a user, an IP or a code lookup ID
    ok: bool


@st.composite
def timed_attempt_sequences(
    draw: st.DrawFn,
    *,
    min_size: int = 1,
    max_size: int = 30,
    max_gap_seconds: int = 120,
    keys: int = 2,
) -> list[Attempt]:
    """Attempts in time order (gaps of 0 to `max_gap_seconds`, ties allowed) spread over up to `keys` keys."""
    t = draw(st.datetimes(min_value=_EPOCH.replace(tzinfo=None), timezones=st.just(UTC)))
    pool = [f"key-{n}" for n in range(1, keys + 1)]
    attempts = []
    for _ in range(draw(st.integers(min_size, max_size))):
        t += timedelta(seconds=draw(st.integers(0, max_gap_seconds)))
        attempts.append(Attempt(t, draw(st.sampled_from(pool)), draw(st.booleans())))
    return attempts
