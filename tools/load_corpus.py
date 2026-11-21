"""Load the real public corpus (corpus/manifest.toml) into an admin's workspace, for demos.

  python tools/load_corpus.py --email admin@example.com [--domain legal|medical|all] [--limit N]

The admin must already be an active admin (sign in, join with the Organization Code, get approved). Files go
through the normal ingestion pipeline as workspace documents owned by that admin; each file's SHA-256 is
checked against the manifest first. Run `make corpus` once to download the files.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tomllib
import uuid

import lmqa_audit
from ingestion import create_ingestion
from lmqa_db import Database
from lmqa_models.envfile import ROOT
from lmqa_models.settings import load_settings
from lmqa_objectstore import ObjectStore

CORPUS = ROOT / "corpus"
FILE_TYPE = {"pdf": "pdf", "html": "html", "xml": "xml", "jats": "xml", "spl": "xml", "docx": "docx", "txt": "txt"}
SUFFIX = {"pdf": ".pdf", "html": ".htm", "xml": ".xml", "jats": ".xml", "spl": ".xml", "docx": ".docx", "txt": ".txt"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--domain", choices=["legal", "medical", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    settings = load_settings()
    db = Database(settings)
    db.open()
    _, ingestor = create_ingestion(settings, db, workers=1)
    store = ObjectStore(settings.data_dir / "objects")
    with db.system() as conn:
        admin = conn.execute(
            "select u.id as user_id, m.org_id, m.workspace_id from users u join memberships m on m.user_id = u.id"
            " join workspaces w on w.id = m.workspace_id where lower(u.email) = lower(%s) and m.role = 'admin'"
            " and m.status = 'active' and w.status = 'active'",
            [args.email],
        ).fetchone()
    if admin is None:
        print(f"No active admin with email {args.email}. Sign in, join as admin and get approved first.")
        return 1

    items = tomllib.loads((CORPUS / "manifest.toml").read_text(encoding="utf-8"))["item"]
    items = [i for i in items if args.domain == "all" or i["domain"] == args.domain]
    if args.limit:
        items = items[: args.limit]
    ready = 0
    for item in items:
        path = CORPUS / "data" / f"{item['id']}{SUFFIX.get(item['format'], '')}"
        if not path.is_file():
            print(f"  skip {item['id']}: not downloaded (run `make corpus`)")
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != item["sha256"]:
            print(f"  skip {item['id']}: SHA-256 does not match the manifest")
            continue
        kind = FILE_TYPE[item["format"]]
        doc_id = str(uuid.uuid4())
        key = ObjectStore.key(admin["org_id"], admin["workspace_id"], doc_id, kind)
        with db.system() as conn:
            if conn.execute(
                "select 1 from documents where workspace_id = %s and sha256 = %s", [admin["workspace_id"], digest]
            ).fetchone():
                print(f"  have {item['title'][:72]}")
                continue
            store.put(key, data)
            conn.execute(
                "insert into documents (id, org_id, workspace_id, owner_id, title, filename, file_type, size_bytes,"
                " sha256, object_key, visibility) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'workspace')",
                [
                    doc_id,
                    admin["org_id"],
                    admin["workspace_id"],
                    admin["user_id"],
                    item["title"][:200],
                    path.name,
                    kind,
                    len(data),
                    digest,
                    key,
                ],
            )
            lmqa_audit.append(
                conn,
                org_id=admin["org_id"],
                workspace_id=admin["workspace_id"],
                actor_id=admin["user_id"],
                action="document.uploaded",
                target_type="document",
                target_id=doc_id,
                payload={"title": item["title"][:200], "type": kind, "source": item["source_url"], "sha256": digest},
            )
        print(f"  indexing {item['title'][:72]} ...", flush=True)
        ingestor.run_safely(doc_id)
        with db.system() as conn:
            row = conn.execute("select status, chunk_count, error from documents where id = %s", [doc_id]).fetchone()
        assert row is not None
        print(f"    {row['status']}: {row['chunk_count'] or 0} chunks {row['error'] or ''}".rstrip(), flush=True)
        ready += row["status"] == "ready"
    db.close()
    print(f"{ready} document(s) ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
