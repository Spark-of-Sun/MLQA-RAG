"""Audit anchoring, verification and sealed-payload reading (blueprint 13.1 to 13.3, 12.9, G1.8, G9.1, G9.2).

Hourly: the latest hash of every audit chain (one per workspace, one control chain per organization) is a Merkle
leaf; the root, the leaves and the period are written as one JSON object to the Object Lock bucket (compliance mode
in production), so anyone holding the bucket can later prove that no event before the anchor was changed, even by a
database superuser. Deleting an anchor object is refused by Object Lock.

The `audit` service is the only holder of audit private keys: each workspace-month (and control-chain-month) private
key is wrapped by the organization CMK (lmqa_keys.KeyRing.ensure_audit_key) and unwrapped here on demand, cached per
process for at most 15 minutes. Shredding a month (destroying its wrapped private keys) makes that month's payloads
unreadable while the chain still verifies.

Retention (R-61.5): `detach_month` anchors every chain's range in a past month, then `audit_detach_month` writes the
partition_detach checkpoints with the anchor reference and detaches that month's partitions; verification starts at
the checkpoint.

Tombstone mirror: deletion_tombstones rows are copied to the tombstone bucket (outside the backup set) and marked
mirrored; `replay_tombstones` re-applies them after any restore, before traffic is accepted.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from lmqa_keys.keyring import audit_key_context
from lmqa_keys.providers import KeyProvider
from lmqa_security.sealing import unseal

PRIVATE_KEY_TTL = 900.0


def merkle_root(leaves: list[str]) -> str:
    """SHA-256 Merkle root over hex leaves, sorted for determinism; odd nodes are promoted unchanged."""
    level = sorted(leaves) or [hashlib.sha256(b"").hexdigest()]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(
                    hashlib.sha256(
                        bytes.fromhex(level[i]) + bytes.fromhex(level[i + 1])
                    ).hexdigest()
                )
            else:
                nxt.append(level[i])
        level = nxt
    return level[0]


@dataclass
class AnchorResult:
    period_start: datetime
    root: str
    leaves: int
    object_key: str


class Anchorer:
    def __init__(self, conn_factory: Any, s3: Any, bucket: str) -> None:
        self._conn = conn_factory
        self._s3 = s3
        self._bucket = bucket

    def anchor(self, period_end: datetime | None = None) -> AnchorResult | None:
        end = (period_end or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=1)
        with self._conn() as conn:
            if conn.execute(
                "select 1 from audit_anchors where period_start = %s", [start]
            ).fetchone():
                return None
            leaves_rows = conn.execute(
                "select chain_id, org_id, seq, hash from audit_anchor_leaves(%s)", [end]
            ).fetchall()
            leaves = [_leaf(r["chain_id"], r["seq"], r["hash"]) for r in leaves_rows]
            root = merkle_root(leaves)
            key = f"anchors/{start:%Y/%m/%d/%H}.json"
            body = json.dumps(
                {
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "root": root,
                    "leaves": [
                        {
                            "chain_id": str(r["chain_id"]),
                            "org_id": str(r["org_id"]),
                            "seq": r["seq"],
                            "hash": r["hash"],
                        }
                        for r in leaves_rows
                    ],
                },
                sort_keys=True,
            ).encode()
            out = self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType="application/json",
                ChecksumSHA256=_b64sha(body),
            )
            conn.execute(
                "insert into audit_anchors (period_start, period_end, merkle_root, leaf_count, object_key,"
                " object_version) values (%s, %s, %s, %s, %s, %s)",
                [start, end, root, len(leaves), key, out.get("VersionId")],
            )
            for r in leaves_rows:
                conn.execute(
                    "select audit_checkpoint(%s, %s, 'hourly', %s)", [r["chain_id"], r["seq"], key]
                )
        return AnchorResult(start, root, len(leaves), key)

    def verify(self, period_start: datetime) -> bool:
        """The stored object, the recorded root and the current chain heads at that time must all agree."""
        with self._conn() as conn:
            row = conn.execute(
                "select * from audit_anchors where period_start = %s", [period_start]
            ).fetchone()
            if not row:
                return False
            obj = (
                json.loads(
                    self._s3.get_object(
                        Bucket=self._bucket, Key=row["object_key"], VersionId=row["object_version"]
                    )["Body"].read()
                )
                if row["object_version"]
                else json.loads(
                    self._s3.get_object(Bucket=self._bucket, Key=row["object_key"])["Body"].read()
                )
            )
            leaves = [_leaf(x["chain_id"], x["seq"], x["hash"]) for x in obj["leaves"]]
            if merkle_root(leaves) != obj["root"] or obj["root"] != row["merkle_root"]:
                return False
            for x in obj["leaves"]:
                ev = conn.execute(
                    "select hash from audit_events where chain_id = %s and seq = %s",
                    [x["chain_id"], x["seq"]],
                ).fetchone()
                if ev is not None and ev["hash"] != x["hash"]:
                    return False  # an event that was anchored has changed
        return True


def _leaf(chain_id: Any, seq: Any, hash_: str) -> str:
    return hashlib.sha256(f"{chain_id}|{seq}|{hash_}".encode()).hexdigest()


def ensure_partitions(conn_factory: Any, months: int = 3) -> int:
    """Create this month's and the next months' audit partitions (audit_append fails closed without one)."""
    with conn_factory() as conn:
        row = conn.execute("select audit_ensure_partitions(null, %s) as n", [months]).fetchone()
    return int(row["n"]) if row else 0


def detach_month(conn_factory: Any, s3: Any, bucket: str, month: date) -> int:
    """Retention detach of one past month (R-61.5): anchor every chain's range in the month to the Object Lock
    bucket first, then write the checkpoints with that reference and detach the partitions. Returns the number of
    checkpoints written."""
    with conn_factory() as conn:
        heads = conn.execute(
            "select chain_id, org_id, workspace_id, first_seq, last_seq, last_hash, range_start, range_end"
            " from audit_month_heads(%s)",
            [month],
        ).fetchall()
        body = json.dumps(
            {
                "kind": "partition_detach",
                "month": month.isoformat(),
                "root": merkle_root(
                    [_leaf(h["chain_id"], h["last_seq"], h["last_hash"]) for h in heads]
                ),
                "checkpoints": [
                    {k: (str(v) if v is not None else None) for k, v in dict(h).items()}
                    for h in heads
                ],
            },
            sort_keys=True,
        ).encode()
        key = f"checkpoints/{month:%Y/%m}.json"
        out = s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ChecksumSHA256=_b64sha(body),
        )
        ref = f"{key}@{out.get('VersionId')}" if out.get("VersionId") else key
        row = conn.execute("select audit_detach_month(%s, %s) as n", [month, ref]).fetchone()
    return int(row["n"]) if row else 0


def _b64sha(body: bytes) -> str:
    import base64

    return base64.b64encode(hashlib.sha256(body).digest()).decode()


class PayloadReader:
    """Opens sealed payloads for the views each role may see (13.5). Only the audit service constructs this."""

    def __init__(self, provider: KeyProvider) -> None:
        self._provider = provider
        self._keys: dict[int, tuple[float, bytes]] = {}

    def _private_key(self, conn: Any, key_id: int) -> bytes | None:
        hit = self._keys.get(key_id)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        row = conn.execute(
            "select k.org_id, k.workspace_id, k.month, k.wrapped_private_key, k.state, o.key_ref from audit_keys k"
            " join org_keys o on o.org_id = k.org_id and o.key_version = k.wrapped_by where k.id = %s",
            [key_id],
        ).fetchone()
        if not row or row["state"] == "destroyed" or not row["wrapped_private_key"]:
            return None  # shredded month: the payload is gone, the chain still verifies
        ws = str(row["workspace_id"]) if row["workspace_id"] else None
        key = self._provider.unwrap(
            row["key_ref"],
            bytes(row["wrapped_private_key"]),
            audit_key_context(str(row["org_id"]), ws, row["month"]),
        )
        self._keys[key_id] = (time.monotonic() + PRIVATE_KEY_TTL, key)
        return key

    def payload(self, conn: Any, event: dict[str, Any]) -> dict[str, Any] | None:
        """The event's opened content: {} when it has none, None when its month is shredded."""
        if event.get("payload_ct_sha256") is None:
            return {}
        row = conn.execute(
            "select p.ciphertext, k.month from audit_payloads p join audit_keys k on k.id = p.key_id"
            " where p.event_id = %s and p.created_at = %s",
            [event["id"], event["created_at"]],
        ).fetchone()
        if row is None:
            return None
        key = self._private_key(conn, int(event["payload_key_id"]))
        if key is None:
            return None
        return unseal(
            bytes(row["ciphertext"]),
            key,
            org_id=str(event["org_id"]),
            workspace_id=str(event["workspace_id"]) if event.get("workspace_id") else None,
            month=row["month"],
            action=event["action"],
        )

    @staticmethod
    def shred_month(conn: Any, org_id: str, month: date) -> None:
        conn.execute(
            "update audit_keys set wrapped_private_key = null, state = 'destroyed' where org_id = %s and month = %s",
            [org_id, month],
        )
        conn.execute(
            "insert into deletion_tombstones (org_id, scope, target_id) values (%s, 'audit_month', %s)",
            [org_id, month.isoformat()],
        )


def mirror_tombstones(conn_factory: Any, s3: Any, bucket: str, limit: int = 500) -> int:
    with conn_factory() as conn:
        rows = conn.execute(
            "select * from deletion_tombstones where mirrored_at is null order by created_at"
            " limit %s for update skip locked",
            [limit],
        ).fetchall()
        for r in rows:
            body = json.dumps(
                {k: (str(v) if v is not None else None) for k, v in dict(r).items()}
            ).encode()
            s3.put_object(
                Bucket=bucket,
                Key=f"tombstones/{r['org_id']}/{r['id']}.json",
                Body=body,
                ChecksumSHA256=_b64sha(body),
            )
            conn.execute(
                "update deletion_tombstones set mirrored_at = now() where id = %s", [r["id"]]
            )
    return len(rows)


def replay_tombstones(conn_factory: Any, s3: Any, bucket: str, org_id: str) -> int:
    """After a restore: re-shred every key the ledger says was destroyed, before accepting traffic (12.9)."""
    n = 0
    paginator = s3.get_paginator("list_objects_v2")
    with conn_factory() as conn:
        for page in paginator.paginate(Bucket=bucket, Prefix=f"tombstones/{org_id}/"):
            for obj in page.get("Contents", []):
                t = json.loads(s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read())
                if t["scope"] == "document":
                    n += conn.execute(
                        "update doc_keys set wrapped_key = '\\x00'::bytea, state = 'destroyed',"
                        " destroyed_at = coalesce(destroyed_at, now()) where document_id = %s"
                        " and state <> 'destroyed'",
                        [t["target_id"]],
                    ).rowcount
                elif t["scope"] == "workspace":
                    n += conn.execute(
                        "update workspace_keys set wrapped_key = '\\x00'::bytea, escrow_wrapped = null,"
                        " state = 'destroyed' where workspace_id = %s and state <> 'destroyed'",
                        [t["target_id"]],
                    ).rowcount
                elif t["scope"] == "audit_month":
                    n += conn.execute(
                        "update audit_keys set wrapped_private_key = null, state = 'destroyed'"
                        " where org_id = %s and month = %s and state <> 'destroyed'",
                        [t["org_id"], t["target_id"]],
                    ).rowcount
    return n
