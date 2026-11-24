"""Create roles and the database, apply db/migrations, db/policies and db/roles/grants.sql, then refresh PgBouncer.

On a database that still has plaintext content columns, the upgrade stops at 0012_field_encryption, runs the
one-time re-encryption job (tools/reencrypt_fields.py, needs OpenBao or KMS) and then continues to head, where
0013_drop_plaintext drops the plaintext columns (KD-9, Q-36 default).

PgBouncer authenticates request-path roles with the SCRAM verifiers PostgreSQL itself stores, so the userlist is
copied from `pg_authid` after the roles exist and PgBouncer is told to reload it (SIGHUP). Verifiers are never
printed. Only the runtime roles go through the pooler; `lmqa_owner` (migrations) and superusers connect directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from lmqa_db import connect_role as connect
from lmqa_db.direct import POOLED_ROLES as _POOLED
from lmqa_db.migrate import migrate, pending
from lmqa_models.envfile import ROOT
from lmqa_models.settings import Settings, load_settings

POOLED_ROLES = tuple(sorted(_POOLED))
REENCRYPT_AT = "0012_field_encryption"
DROP_PLAINTEXT = "0013_drop_plaintext"
USERLIST = ROOT / "data" / "infra" / "pgbouncer" / "userlist.txt"


def write_pgbouncer_userlist() -> bool:
    """Copy the pooled roles' SCRAM verifiers into the PgBouncer auth file; True when the file changed."""
    settings = load_settings()
    with connect(settings, "postgres", autocommit=True) as conn:
        rows = conn.execute(
            "select rolname, rolpassword from pg_authid where rolname = any(%s) order by rolname",
            [list(POOLED_ROLES)],
        ).fetchall()
    body = "".join(
        f'"{name}" "{secret}"\n'
        for name, secret in rows
        if secret and secret.startswith("SCRAM-SHA-256$")
    )
    USERLIST.parent.mkdir(parents=True, exist_ok=True)
    if USERLIST.is_file() and USERLIST.read_text(encoding="utf-8") == body:
        return False
    # Rewrite in place: a file bind mount follows the inode, so replacing the file would hide the change from
    # PgBouncer. Readable by the pgbouncer user inside the container; the parent directory is 0700.
    with USERLIST.open("w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(USERLIST, 0o644)
    return True


def reload_pgbouncer() -> None:
    docker = shutil.which("docker")
    if not docker:
        return
    running = subprocess.run(  # noqa: S603 - fixed docker argv
        [docker, "ps", "-q", "--filter", "name=^lmqa-pgbouncer$"],
        capture_output=True,
        text=True,
        check=False,
    )
    if running.stdout.strip():
        subprocess.run(  # noqa: S603 - fixed docker argv
            [docker, "kill", "-s", "HUP", "lmqa-pgbouncer"], capture_output=True, check=False
        )


def _db_exists(settings: Settings) -> bool:
    with connect(settings, "postgres", autocommit=True) as conn:
        return (
            conn.execute(
                "select 1 from pg_database where datname = %s", [settings.db_name]
            ).fetchone()
            is not None
        )


def main() -> int:
    settings = load_settings()
    applied: list[str] = []
    # Q-36 default (KD-9): plaintext rows are re-encrypted by a one-time job between the revision that adds the
    # ciphertext columns and the one that drops the plaintext columns.
    waiting = pending(settings, settings.db_name) if _db_exists(settings) else []
    if DROP_PLAINTEXT in waiting:
        if REENCRYPT_AT in waiting:
            applied += migrate(settings, target=REENCRYPT_AT)
        import reencrypt_fields

        report = reencrypt_fields.run(settings)
        print(
            f"re-encryption: keys {report['keys']}; rows {report['reencrypted'] or 'none needed'}"
        )
    applied += migrate(settings)
    print(
        f"database {settings.db_name}: {len(applied)} new migration(s) {applied or ''}; policies and grants applied"
    )
    if write_pgbouncer_userlist():
        reload_pgbouncer()
        print("pgbouncer: auth file refreshed from pg_authid and reloaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
