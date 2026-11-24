"""Load the real public corpus (corpus/manifest.toml) into an admin's workspace through the product's APIs.

  LMQA_ACCESS_TOKEN=<Auth0 access token> python tools/load_corpus.py --email admin@example.com
      [--api http://127.0.0.1:8000] [--domain legal|medical|all] [--limit N]
      [--admin-code CODE --workspace-name NAME]       join an organization as admin first (onboarding API)
      [--create-org NAME --kind legal|medical|both]   or create the organization first (onboarding API)

The token must be a real Auth0 access token for the main API audience, issued to the signed-in user (R-89.4); this
tool never signs tokens and never writes to the database. Each document goes through POST /v1/documents, the same
upload path as the web app, so quotas, scanning, audit and ingestion all apply. Each file's SHA-256 is checked
against the manifest first, and files already uploaded (same filename) are skipped. Run `make corpus` first.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
SUFFIX = {"html": "htm", "jats": "xml", "spl": "xml"}
TERMINAL = {"ready", "failed", "quarantined", "rejected"}


def onboard(api: httpx.Client, args: argparse.Namespace) -> dict[str, Any] | None:
    """Return the caller's membership, joining or creating the organization through onboarding if asked."""
    me = api.get("/v1/me").raise_for_status().json()
    if args.email and str(me["user"]["email"]).lower() != args.email.lower():
        sys.exit(f"The token belongs to {me['user']['email']}, not {args.email}.")
    if me["membership"] is None and args.create_org:
        api.post(
            "/v1/onboarding/organization", json={"name": args.create_org, "kind": args.kind}
        ).raise_for_status()
    elif me["membership"] is None and args.admin_code:
        api.post(
            "/v1/onboarding/join-admin",
            json={"code": args.admin_code, "workspace_name": args.workspace_name},
        ).raise_for_status()
    return api.get("/v1/me").raise_for_status().json()["membership"]


def upload(api: httpx.Client, path: Path, title: str) -> dict[str, Any]:
    while True:
        with path.open("rb") as handle:
            response = api.post(
                "/v1/documents",
                files={"file": (path.name, handle)},
                data={"title": title[:200], "visibility": "private"},
            )
        if response.status_code != 429:
            return response.raise_for_status().json()
        print("    upload rate limit reached; waiting 60 s", flush=True)
        time.sleep(60)


def wait(api: httpx.Client, doc_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        doc = api.get(f"/v1/documents/{doc_id}").raise_for_status().json()
        if doc["status"] in TERMINAL or time.monotonic() > deadline:
            return doc
        time.sleep(3)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--email", default="", help="expected account email; refuses a token for anyone else"
    )
    ap.add_argument(
        "--api", default=os.environ.get("LMQA_API_INTERNAL_URL", "http://127.0.0.1:8000")
    )
    ap.add_argument("--domain", choices=["legal", "medical", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--admin-code", default="")
    ap.add_argument("--workspace-name", default="Corpus")
    ap.add_argument("--create-org", default="")
    ap.add_argument("--kind", choices=["legal", "medical", "both"], default="both")
    ap.add_argument("--timeout", type=float, default=600, help="seconds to wait for each document")
    args = ap.parse_args()

    token = os.environ.get("LMQA_ACCESS_TOKEN", "")
    if not token:
        print(
            "Set LMQA_ACCESS_TOKEN to a real Auth0 access token for the admin (it is never taken on argv)."
        )
        return 2
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=args.api, headers=headers, timeout=120) as api:
        membership = onboard(api, args)
        if membership is None or membership["role"] != "admin" or not membership["active"]:
            state = (
                "no membership"
                if membership is None
                else f"{membership['role']}, {membership['status']}"
            )
            print(
                f"Not an active admin yet ({state}). Join as admin and get approved, then re-run."
            )
            return 1

        items = tomllib.loads((CORPUS / "manifest.toml").read_text(encoding="utf-8"))["item"]
        items = [
            i
            for i in items
            if (args.domain in ("all", i["domain"])) and i["allowed_use"] == "commercial"
        ]
        if args.limit:
            items = items[: args.limit]
        have = {d["filename"] for d in api.get("/v1/documents").raise_for_status().json()}
        ready = failed = 0
        for item in items:
            path = CORPUS / "data" / f"{item['id']}.{SUFFIX.get(item['format'], item['format'])}"
            if not path.is_file():
                print(f"  skip {item['id']}: not downloaded (run `make corpus`)")
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                print(f"  skip {item['id']}: SHA-256 does not match the manifest")
                failed += 1
                continue
            if path.name in have:
                print(f"  have {item['title'][:72]}")
                continue
            print(f"  uploading {item['title'][:72]} ...", flush=True)
            doc = wait(api, upload(api, path, item["title"])["id"], args.timeout)
            print(
                f"    {doc['status']}: {doc.get('chunk_count') or 0} chunks {doc.get('error') or ''}".rstrip()
            )
            ready += doc["status"] == "ready"
            failed += doc["status"] in TERMINAL - {"ready"}
    print(f"{ready} document(s) ready, {failed} problem(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
