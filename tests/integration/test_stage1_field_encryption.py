"""Task 3.7: column encryption through lmqa_keys (R-51 criteria 3 and 4, R-53 criterion 2, R-59 criterion 1;
DEV-09 columns).

Core cases only: a round trip for each key kind, a ciphertext moved to another scope does not open, a rotated key
keeps older values readable, and the rows the re-encryption job wrote open to their stored hashes. Property 31
(task 3.15) and edge cases come later.

Real dependencies: PostgreSQL and OpenBao in local key mode. Rows are written by the superuser inside a transaction
that is always rolled back, so this also runs on the migrated dev database (LMQA_TEST_DATABASE=lmqa). The OpenBao
key created for the test organization is destroyed afterwards.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from lmqa_db import connect_role
from lmqa_db.migrate import drop_database, migrate
from lmqa_keys import DecryptionError, Field, FieldCipher, KeyRing, OpenBaoProvider
from lmqa_keys.envelope import key_version_of
from lmqa_models.infra import InfraConfigError
from lmqa_models.settings import load_settings

pytestmark = [pytest.mark.stage1, pytest.mark.integration]


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    existing = os.environ.get("LMQA_TEST_DATABASE")
    if existing:
        yield existing
        return
    cfg = load_settings()
    name = f"lmqa_scratch_fields_{os.getpid()}"
    try:
        migrate(cfg, name)
    except psycopg.OperationalError as exc:  # pragma: no cover - no Postgres running
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield name
    drop_database(cfg, name)


@pytest.fixture(scope="module")
def provider() -> OpenBaoProvider:
    try:
        bao = OpenBaoProvider()
        bao.ensure_mount()
    except (InfraConfigError, httpx.HTTPError) as exc:  # pragma: no cover - no OpenBao running
        pytest.skip(f"OpenBao unavailable: {exc}")
    return bao


@dataclass
class World:
    conn: psycopg.Connection[Any]
    ring: KeyRing
    cipher: FieldCipher
    org: UUID
    ws: UUID
    other_ws: UUID
    users: tuple[UUID, UUID]

    def document(self, ws: UUID | None = None) -> UUID:
        doc = uuid4()
        self.cipher.new_document(self.conn, self.org, ws or self.ws, doc)
        return doc


@pytest.fixture
def world(database: str, provider: OpenBaoProvider) -> Iterator[World]:
    ring = KeyRing(provider)
    org, ws, other_ws, u1, u2 = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    with (
        connect_role(load_settings(), "postgres", database=database, row_factory=dict_row) as conn,
        conn.transaction(force_rollback=True),
    ):
        for u in (u1, u2):
            conn.execute("insert into users (id, auth0_sub) values (%s, %s)", [u, f"test|{u}"])
        conn.execute(
            "insert into organizations (id, name, kind, status) values (%s, 'Keys org', 'legal', 'active')",
            [org],
        )
        for w in (ws, other_ws):
            conn.execute(
                "insert into workspaces (id, org_id, name, status) values (%s, %s, %s, 'active')",
                [w, org, f"Keys {w}"],
            )
            ring.ensure_workspace_key(conn, org, w)
        ring.ensure_platform_key(conn, "contact")
        yield World(conn, ring, FieldCipher(ring), org, ws, other_ws, (u1, u2))
    provider.destroy_now(f"lmqa-org-{org}")


def test_each_key_kind_round_trips(world: World) -> None:
    """R-51.3: document, workspace and platform keys seal and open; nonces are random, so equal values differ."""
    doc, chunk, query = world.document(), uuid4(), uuid4()
    fields: list[tuple[Field, str]] = [
        (Field.document("document.title", world.org, world.ws, doc), "Master services agreement"),
        (
            Field.chunk("chunk.text", world.org, world.ws, doc, chunk, 1),
            "The term is 30 days.",
        ),
        (
            Field.workspace("query.question", world.org, world.ws, query),
            "What is the cure period?",
        ),
        (Field.contact("user.email", world.users[0]), "someone@example.org"),
    ]
    for field, value in fields:
        blob = world.cipher.seal(world.conn, field, value)
        assert blob is not None and blob[:2] == b"L1" and value.encode() not in blob
        assert world.cipher.seal(world.conn, field, value) != blob
        world.ring.cache.clear()  # open through the provider and the key rows, not the cache
        assert world.cipher.open(world.conn, field, blob) == value
    result = Field.workspace("query.result", world.org, world.ws, query)
    assert world.cipher.open_json(
        world.conn, result, world.cipher.seal_json(world.conn, result, {"outcome": "answered"})
    ) == {"outcome": "answered"}


def test_ciphertext_moved_to_another_scope_does_not_open(world: World) -> None:
    """R-51.4: the associated data binds purpose, organization, workspace, object and version."""
    doc, other_doc = world.document(), world.document()
    title = Field.document("document.title", world.org, world.ws, doc)
    blob = world.cipher.seal(world.conn, title, "Confidential title")
    query = uuid4()
    question = Field.workspace("query.question", world.org, world.ws, query)
    asked = world.cipher.seal(world.conn, question, "A question")
    email = world.cipher.seal(
        world.conn, Field.contact("user.email", world.users[0]), "a@example.org"
    )
    moved = [
        (Field.document("document.title", world.org, world.ws, other_doc), blob),  # another row
        (Field.document("document.filename", world.org, world.ws, doc), blob),  # another column
        (Field.workspace("query.question", world.org, world.other_ws, query), asked),  # workspace
        (Field.workspace("query.question", world.org, world.ws, uuid4()), asked),  # another query
        (Field.workspace("query.standalone_question", world.org, world.ws, query), asked),
        (Field.contact("user.email", world.users[1]), email),  # another user
    ]
    for field, ciphertext in moved:
        with pytest.raises(DecryptionError):
            world.cipher.open(world.conn, field, ciphertext)


def test_rotation_keeps_older_ciphertext_readable(world: World) -> None:
    """R-53.2: a new workspace key version seals new values; older values and document keys stay readable, and
    re-wrapping moves document keys to the new version without changing them."""
    doc = world.document()
    title = Field.document("document.title", world.org, world.ws, doc)
    old_title = world.cipher.seal(world.conn, title, "Before rotation")
    question = Field.workspace("query.question", world.org, world.ws, uuid4())
    old = world.cipher.seal(world.conn, question, "Asked before rotation")
    assert old is not None and key_version_of(old) == 1

    assert world.ring.rotate_workspace_key(world.conn, world.org, world.ws) == 2
    new = world.cipher.seal(world.conn, question, "Asked after rotation")
    assert new is not None and key_version_of(new) == 2
    assert world.ring.rewrap_document_keys(world.conn, world.org, world.ws) == 1
    wrapped_by = world.conn.execute(
        "select wrapped_by from doc_keys where document_id = %s", [doc]
    ).fetchone()
    assert wrapped_by is not None and wrapped_by["wrapped_by"] == 2

    world.ring.cache.clear()
    assert world.cipher.open(world.conn, question, old) == "Asked before rotation"
    assert world.cipher.open(world.conn, question, new) == "Asked after rotation"
    assert world.cipher.open(world.conn, title, old_title) == "Before rotation"


def test_reencrypted_chunks_open_to_their_stored_hashes(
    database: str, provider: OpenBaoProvider
) -> None:
    """The one-time job (tools/reencrypt_fields.py) sealed each chunk under its own scope: every chunk opens and
    its text matches the SHA-256 recorded at ingestion. Skipped on a database without chunks."""
    cipher = FieldCipher(KeyRing(provider))
    with connect_role(load_settings(), "postgres", database=database, row_factory=dict_row) as conn:
        rows = conn.execute(
            "select id, org_id, workspace_id, document_id, version, text_ct, section_ct, text_sha256"
            " from chunks order by document_id, ordinal limit 500"
        ).fetchall()
        if not rows:
            pytest.skip("no chunks in this database")
        for row in rows:
            opened = cipher.open_chunk_row(conn, dict(row))
            assert hashlib.sha256(opened["text"].encode()).hexdigest() == row["text_sha256"]
