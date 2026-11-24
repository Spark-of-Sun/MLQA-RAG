"""Render the credential files that compose.yaml mounts, from the local secrets in .env (never printed).

  data/infra/valkey/users.acl       ACL users per service, passwords as SHA-256 only; the default user is off
  data/infra/seaweedfs/s3.json      S3 identities: `admin` (setup, probe) and `ingestion` (its bucket only)
  data/infra/pgbouncer/userlist.txt created empty here; `make migrate` copies the SCRAM verifiers into it

Run by `make setup` and `make up` before Docker starts, so a bind mount never points at a missing file (Docker would
create a directory in its place).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from lmqa_models.envfile import ROOT
from lmqa_models.infra import OBJECT_STORE_BUCKET, InfraConfigError, load_infra_settings

INFRA_DIR = ROOT / "data" / "infra"

# Key and channel patterns per caller (blueprint 4.2: each service holds only its own Valkey ACL user).
# `-@dangerous` comes last so no user can run FLUSHALL, CONFIG, DEBUG, KEYS or CLIENT KILL.
_BASE = "-@all +@connection +acl|whoami +@read +@write +@keyspace +@string +@hash +@list +@set +@sortedset +@scripting"
VALKEY_RULES = {
    "gateway": f"~pv:* ~rl:* ~idem:* ~ctx:* resetchannels &revocation:* {_BASE} +@pubsub -@dangerous",
    "identity": f"~pv:* resetchannels &revocation:* {_BASE} +@pubsub -@dangerous",
    "retrieval": f"~scope:* resetchannels {_BASE} -@dangerous",
    "generation": f"~cache:* resetchannels {_BASE} -@dangerous",
    "frontend": f"~sess:* resetchannels {_BASE} -@dangerous",
    "doctor": "resetkeys resetchannels -@all +ping +info +acl|whoami",
    "test": f"~lmqa-test:* resetchannels &lmqa-test:* {_BASE} +@pubsub -@dangerous",
}


def _write(path: Path, body: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # In place, not rename: a file bind mount follows the inode, so a running container sees the new content.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, mode)


def valkey_acl() -> str:
    infra = load_infra_settings()
    lines = [
        "user default off resetkeys resetchannels -@all",
        # Fixed, ping-only account for the container health check: it can do nothing else.
        "user healthcheck on >healthcheck resetkeys resetchannels -@all +ping",
    ]
    for user, rules in VALKEY_RULES.items():
        digest = hashlib.sha256(infra.valkey_password(user).encode()).hexdigest()
        lines.append(f"user {user} on #{digest} {rules}")
    return "\n".join(lines) + "\n"


def seaweed_s3() -> str:
    infra = load_infra_settings()
    admin = infra.object_store_credentials("admin")
    ingestion = infra.object_store_credentials("ingestion")
    scoped = [f"{a}:{OBJECT_STORE_BUCKET}" for a in ("Read", "Write", "List", "Tagging")]
    doc = {
        "identities": [
            {
                "name": "admin",
                "credentials": [{"accessKey": admin[0], "secretKey": admin[1]}],
                "actions": ["Admin", "Read", "Write", "List", "Tagging"],
            },
            {
                "name": "ingestion",
                "credentials": [{"accessKey": ingestion[0], "secretKey": ingestion[1]}],
                "actions": scoped,
            },
        ]
    }
    return json.dumps(doc, indent=2) + "\n"


def render() -> list[str]:
    INFRA_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(INFRA_DIR, 0o700)
    # Containers run as their own users (valkey, pgbouncer), so these two are world-readable inside a 0700
    # directory; they hold hashes and SCRAM verifiers only. The S3 file holds secret keys and SeaweedFS runs as root.
    _write(INFRA_DIR / "valkey" / "users.acl", valkey_acl(), 0o644)
    _write(INFRA_DIR / "seaweedfs" / "s3.json", seaweed_s3(), 0o600)
    userlist = INFRA_DIR / "pgbouncer" / "userlist.txt"
    if not userlist.is_file():
        _write(userlist, "", 0o644)
    return ["valkey/users.acl", "seaweedfs/s3.json", "pgbouncer/userlist.txt"]


def main() -> int:
    try:
        files = render()
    except InfraConfigError as exc:
        print(f"infra config: {exc}", file=sys.stderr)
        return 1
    print(f"infra config: rendered {', '.join(files)} under data/infra/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
