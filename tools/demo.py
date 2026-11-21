"""Simulate the whole product workflow end to end, through the real HTTP API, and check every outcome.

  make demo            (or: uv run python tools/demo.py [--keep])

What is real: the gateway and every service in-process over ASGI, PostgreSQL with row-level security, the
public corpus documents, Gemini embeddings and answers, the citation validator, the audit chain.
What is simulated: sign-in. Browser login with Auth0 cannot run unattended, so this script signs RS256 access
tokens with a throwaway key and serves its JWKS on 127.0.0.1; the gateway verifies them with the same code
path it uses for Auth0 tokens (issuer, audience, signature, expiry).

It uses a separate database, `lmqa_demo`, recreated on every run, so your real data is never touched.

Cast: Alice creates "Hale & Partners LLP" (Super Admin). Bob joins as admin with the Organization Code
(workspace "Litigation"). Carol joins Bob's workspace as a tenant with the Admin Code. Dave creates a second
organization, a hospital; Erin is its admin. Isolation is checked from every wrong position.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

from lmqa_db.migrate import drop_database, migrate
from lmqa_models.envfile import ROOT
from lmqa_models.settings import load_settings

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402

DEMO_DB = "lmqa_demo"
ISSUER = "https://demo-idp.local/"
AUDIENCE = "https://api.demo.local"
CORPUS = ROOT / "corpus" / "data"
CONTRACT = "edgar-0001104659-24-041548-tm2410073d11_ex10-2.htm"  # separation agreement (SEC EDGAR)
DRUG_LABEL = "dailymed-5da82411.xml"  # metoprolol tartrate label (DailyMed)
CAROL_MEMO = b"""Client intake memo - Rivera Logistics

Matter reference: RL-2025-117.

Rivera Logistics received a notice of termination of its master services agreement on 14 March 2025.

Under Section 12.3 of the master services agreement, the cure period for a material breach is fifteen (15)
business days after written notice. Rivera Logistics intends to cure the breach before 4 April 2025.
"""

G, R, Y, D, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    results.append((label, ok))
    print(f"   {G + '✓' if ok else R + '✗'}{X} {label}" + (f" {D}({detail}){X}" if detail else ""), flush=True)
    return ok


def step(title: str) -> None:
    print(f"\n{B}▸ {title}{X}", flush=True)


# ------------------------------------------------------------------------------ simulated identity provider
class IdP:
    def __init__(self, claims_namespace: str) -> None:
        self.ns = claims_namespace
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": "demo-1", "use": "sig", "alg": "RS256"})
        body = json.dumps({"keys": [jwk]}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.jwks_url = f"http://127.0.0.1:{self.server.server_port}/.well-known/jwks.json"

    def token(self, sub: str, email: str, name: str, **overrides: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": [AUDIENCE],
            "sub": sub,
            "iat": now,
            "exp": now + 3600,
            f"{self.ns}/email": email,
            f"{self.ns}/name": name,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "demo-1"})


class User:
    def __init__(self, client: TestClient, idp: IdP, name: str, email: str) -> None:
        self.name = name
        self.client = client
        self.headers = {"authorization": f"Bearer {idp.token(f'auth0|{uuid.uuid4().hex[:16]}', email, name)}"}

    def get(self, path: str) -> Any:
        return self.client.get(f"/v1{path}", headers=self.headers)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.client.post(f"/v1{path}", headers=self.headers, json=body or {})

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/v1{path}", headers=self.headers)

    def upload(self, filename: str, data: bytes, visibility: str, title: str | None = None) -> Any:
        form = {"visibility": visibility, **({"title": title} if title else {})}
        return self.client.post("/v1/documents", headers=self.headers, files={"file": (filename, data)}, data=form)

    def ask(self, question: str) -> dict[str, Any]:
        resp = self.post("/queries", {"question": question})
        if resp.status_code != 200:
            print(f"   {R}query failed: HTTP {resp.status_code} {resp.text[:300]}{X}")
            return {}
        return resp.json()


def show_answer(who: str, question: str, result: dict[str, Any]) -> None:
    print(f"   {D}{who} asks:{X} {question}")
    for seg in result.get("segments", []):
        if seg["type"] == "sentence":
            print(f"     {seg['text']} {Y}{''.join(f'[{n}]' for n in seg['citations'])}{X}")
        elif seg["type"] == "refusal":
            print(f"     {Y}{seg['text']}{X}")
        else:
            print(f"     {R}⊘ A claim could not be verified and was removed{X} {D}({seg['reason']}){X}")
    for c in result.get("citations", []):
        start, end = c["highlights"][0] if c["highlights"] else (0, 0)
        quote = c["text"][start:end] if end else ""
        pages = f" p.{c['page_start']}" if c.get("page_start") else ""
        print(
            f"     {D}[{c['n']}] {c['document_title'][:60]} · {c['section'] or ''}{pages}\n         “{quote[:160]}”{X}"
        )
    s = result.get("stats", {})
    print(
        f"     {D}outcome={result.get('outcome')} verified={s.get('verified')} removed={s.get('removed')} "
        f"model={s.get('model')} latency={s.get('latency_ms')}ms{X}"
    )


def wait_ready(user: User, doc_ids: list[str], timeout: float = 600) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while True:
        docs = {d["id"]: d for d in user.get("/documents").json()}
        pending = [i for i in doc_ids if docs.get(i, {}).get("status") == "processing"]
        if not pending or time.monotonic() > deadline:
            return docs
        time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep the lmqa_demo database afterwards")
    args = ap.parse_args()
    base = load_settings()
    if not base.gemini_api_key:
        print("GEMINI_API_KEY is not set; the demo needs it for embeddings and answers.")
        return 1
    for name in (CONTRACT, DRUG_LABEL):
        if not (CORPUS / name).is_file():
            print(f"Missing corpus file {name}. Run: make corpus")
            return 1

    idp = IdP(base.auth0_claims_namespace)
    settings = base.with_overrides(
        db_name=DEMO_DB,
        auth0_issuer_override=ISSUER,
        auth0_jwks_url_override=idp.jwks_url,
        auth0_audience=AUDIENCE,
        data_dir=ROOT / "data" / "demo",
    )
    print(f"{B}LMQA workflow demo{X}  {D}database={DEMO_DB}  models={' -> '.join(settings.llm_models)}{X}")
    drop_database(settings, DEMO_DB)
    migrate(settings, DEMO_DB)

    app = create_app(settings, resume_jobs=False)
    with TestClient(app) as client:
        alice = User(client, idp, "Alice Hale", "alice@hale-partners.example")
        bob = User(client, idp, "Bob Ortiz", "bob@hale-partners.example")
        carol = User(client, idp, "Carol Diaz", "carol@hale-partners.example")
        dave = User(client, idp, "Dave Kim", "dave@stmarys.example")
        erin = User(client, idp, "Erin Shah", "erin@stmarys.example")

        step("Sign-in and token checks (gateway, blueprint G3.1)")
        check("health is public", client.get("/v1/health").status_code == 200)
        check("no token -> 401", client.get("/v1/me").status_code == 401)
        expired = {"authorization": f"Bearer {idp.token('auth0|x', 'x@x', 'X', exp=int(time.time()) - 600)}"}
        check("expired token -> 401", client.get("/v1/me", headers=expired).status_code == 401)
        wrong_aud = {"authorization": f"Bearer {idp.token('auth0|x', 'x@x', 'X', aud='https://other.api')}"}
        check("wrong audience -> 401", client.get("/v1/me", headers=wrong_aud).status_code == 401)
        hs = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "sub": "auth0|x", "iat": int(time.time()), "exp": int(time.time()) + 60},
            "secret",
            algorithm="HS256",
        )
        check(
            "HS256-signed token -> 401",
            client.get("/v1/me", headers={"authorization": f"Bearer {hs}"}).status_code == 401,
        )
        me = alice.get("/me").json()
        check("first login has no membership", me["membership"] is None, me["user"]["email"])

        step("Path A: Alice creates an organization (Super Admin)")
        r = alice.post("/onboarding/organization", {"name": "Hale & Partners LLP", "kind": "legal"})
        check("organization created", r.status_code == 201)
        m = alice.get("/me").json()["membership"]
        check("Alice is an active Super Admin", m["role"] == "super_admin" and m["active"])
        r = alice.post("/org/code")
        org_code = r.json()["code"]
        check(
            "Organization Code generated, shown once",
            r.status_code == 201 and len(org_code.replace("-", "")) == 64,
            f"{org_code[:17]}… lookup {r.json()['lookup_id']}",
        )
        info = alice.get("/org/code").json()
        check("code panel shows lookup id and uses, never the code", "code" not in info and info["uses"] == 0)

        step("Path B: Bob joins as admin with the Organization Code")
        bad1 = bob.post("/onboarding/join-admin", {"code": "NOT-A-CODE", "workspace_name": "Litigation"})
        tampered = org_code[:-3] + ("0" if org_code[-3] != "0" else "1") + org_code[-2:]
        bad2 = bob.post("/onboarding/join-admin", {"code": tampered, "workspace_name": "Litigation"})
        check(
            "bad codes get one identical error",
            bad1.status_code == bad2.status_code == 400 and bad1.json() == bad2.json(),
            bad1.json()["detail"],
        )
        r = bob.post("/onboarding/join-admin", {"code": org_code, "workspace_name": "Litigation"})
        check("join request accepted, pending approval", r.status_code == 201 and r.json()["status"] == "pending")
        check("pending admin cannot reach documents (403)", bob.get("/documents").status_code == 403)
        admins = alice.get("/org/admins").json()
        check("request appears in Manage Admins", len(admins) == 1 and admins[0]["status"] == "pending")
        r = alice.post(f"/org/admins/{admins[0]['id']}/approve")
        check("Alice approves Bob", r.status_code == 200 and r.json()["workspace_status"] == "active")
        check(
            "illegal transition rejected (approve twice -> 409)",
            alice.post(f"/org/admins/{admins[0]['id']}/approve").status_code == 409,
        )

        step("Path C: Carol joins Bob's workspace as a tenant with the Admin Code")
        admin_code = bob.post("/workspace/code").json()["code"]
        check("Admin Code generated (32 characters)", len(admin_code.replace("-", "")) == 32)
        preview = carol.post("/onboarding/preview-tenant", {"code": admin_code}).json()
        check(
            "preview names the workspace and admin",
            preview.get("workspace") == "Litigation" and preview.get("admin") == "Bob Ortiz",
            json.dumps(preview),
        )
        check("preview does not consume a use", bob.get("/workspace/code").json()["uses"] == 0)
        check("Carol requests to join", carol.post("/onboarding/join-tenant", {"code": admin_code}).status_code == 201)
        members = bob.get("/workspace/members").json()
        check("Bob approves Carol", bob.post(f"/workspace/members/{members[0]['id']}/approve").status_code == 200)

        step("Second organization: Dave creates a hospital, Erin is its admin")
        dave.post("/onboarding/organization", {"name": "St. Mary's Hospital", "kind": "medical"})
        erin.post(
            "/onboarding/join-admin", {"code": dave.post("/org/code").json()["code"], "workspace_name": "Cardiology"}
        )
        dave.post(f"/org/admins/{dave.get('/org/admins').json()[0]['id']}/approve")
        check("Erin is an active admin", erin.get("/me").json()["membership"]["active"])

        step("Uploads: real public documents and a private memo")
        contract = bob.upload(
            CONTRACT,
            (CORPUS / CONTRACT).read_bytes(),
            "workspace",
            "Separation and Release Agreement (American National Bankshares)",
        ).json()
        memo = carol.upload("rivera-intake-memo.txt", CAROL_MEMO, "private", "Rivera Logistics intake memo").json()
        label = erin.upload(
            DRUG_LABEL,
            (CORPUS / DRUG_LABEL).read_bytes(),
            "workspace",
            "Metoprolol tartrate tablets: prescribing information",
        ).json()
        check(
            "tenant cannot share with the whole workspace (403)",
            carol.upload("x.txt", b"some text here", "workspace").status_code == 403,
        )
        check(
            "disguised file rejected (magic bytes)",
            bob.upload("fake.pdf", b"not a pdf", "workspace").status_code == 400,
        )
        print(f"   {D}indexing with {settings.embedding_model} …{X}", flush=True)
        docs_b = wait_ready(bob, [contract["id"]])
        docs_c = wait_ready(carol, [memo["id"]])
        docs_e = wait_ready(erin, [label["id"]])
        for docs, d in ((docs_b, contract), (docs_c, memo), (docs_e, label)):
            got = docs.get(d["id"], {})
            check(
                f"indexed: {d['title'][:60]}",
                got.get("status") == "ready",
                f"{got.get('chunk_count')} chunks, structure {got.get('structure')}"
                if got.get("status") == "ready"
                else str(got.get("error")),
            )

        step("Visibility (row-level security, blueprint 5.4)")
        ids_bob = {d["id"] for d in bob.get("/documents").json()}
        ids_carol = {d["id"] for d in carol.get("/documents").json()}
        check("Carol sees the shared contract and her private memo", {contract["id"], memo["id"]} <= ids_carol)
        check("Bob (admin) does not see Carol's private memo", memo["id"] not in ids_bob)
        check(
            "Bob cannot open or delete it (404)",
            bob.get(f"/documents/{memo['id']}").status_code == 404
            and bob.delete(f"/documents/{memo['id']}").status_code == 404,
        )
        check(
            "Erin (other organization) gets 404 for Bob's contract",
            erin.get(f"/documents/{contract['id']}").status_code == 404,
        )
        check("Super Admin has no route to documents (404)", alice.get("/documents").status_code == 404)
        check(
            "Super Admin has no route to questions (404)",
            alice.post("/queries", {"question": "hello?"}).status_code == 404,
        )
        check("tenant has no route to Manage Tenants (404)", carol.get("/workspace/members").status_code == 404)

        step("Questions with verified citations (blueprint 11.6)")
        q1 = "When must the severance benefit be paid, and what condition must be met first?"
        a1 = bob.ask(q1)
        show_answer("Bob", q1, a1)
        check(
            "answered with verified, cited sentences",
            a1.get("outcome") in {"answered", "partial"} and a1["stats"]["verified"] >= 1,
        )
        cited_docs = {c["document_id"] for c in a1.get("citations", [])}
        check("every citation points into Bob's visible documents", bool(cited_docs) and cited_docs <= ids_bob)
        spans_ok = all(c["highlights"] and c["text"] for c in a1.get("citations", []))
        check("every citation resolves to a highlighted span", spans_ok)

        q2 = "What is the cure period for Rivera Logistics under the master services agreement?"
        a2 = carol.ask(q2)
        show_answer("Carol", q2, a2)
        check(
            "Carol gets an answer from her private memo",
            any(c["document_id"] == memo["id"] for c in a2.get("citations", [])),
        )
        a3 = bob.ask(q2)
        show_answer("Bob", q2, a3)
        check(
            "Bob cannot retrieve Carol's private memo",
            all(c["document_id"] != memo["id"] for c in a3.get("citations", [])),
        )

        q4 = "What is the recommended starting dosage of metoprolol tartrate for hypertension?"
        a4 = erin.ask(q4)
        show_answer("Erin", q4, a4)
        check(
            "Erin gets a cited dosage answer from the drug label",
            a4.get("outcome") in {"answered", "partial"}
            and any("100" in s.get("text", "") for s in a4.get("segments", [])),
        )
        a5 = bob.ask(q4)
        show_answer("Bob", q4, a5)
        check(
            "Bob's workspace has no drug label -> refusal, nothing leaked",
            a5.get("outcome") == "refused" and not a5.get("citations"),
        )

        reopened = carol.get(f"/queries/{a2.get('id')}").json() if a2.get("id") else {}
        check(
            "history re-opens with citation text re-read under RLS",
            bool(reopened.get("citations")) and all(c.get("text") for c in reopened["citations"]),
        )

        step("Database is the final authority (direct SQL as the runtime role)")
        with psycopg.connect(settings.dsn("lmqa_app", database=DEMO_DB)) as conn:
            no_ctx = conn.execute("select count(*) from chunks").fetchone()
            check("no context -> 0 chunks visible", no_ctx is not None and no_ctx[0] == 0)
            with psycopg.connect(settings.dsn("lmqa_system", database=DEMO_DB)) as sys_conn:
                erin_row = sys_conn.execute("select id from users where email = 'erin@stmarys.example'").fetchone()
            assert erin_row is not None
            with conn.transaction():
                conn.execute("select set_config('app.user_id', %s, true)", [str(erin_row[0])])
                foreign = conn.execute(
                    "select count(*) from chunks where document_id = %s", [contract["id"]]
                ).fetchone()
            check(
                "Erin's context -> 0 rows of Bob's contract even when asked by id",
                foreign is not None and foreign[0] == 0,
            )

        step("Lifecycle: suspension applies on the next request")
        cm = bob.get("/workspace/members").json()[0]
        bob.post(f"/workspace/members/{cm['id']}/suspend")
        check("suspended tenant is blocked (403)", carol.get("/documents").status_code == 403)
        bob.post(f"/workspace/members/{cm['id']}/reactivate")
        check("reactivated tenant has access again", carol.get("/documents").status_code == 200)

        step("Audit chain (blueprint 13)")
        v = bob.get("/audit/verify").json()
        check("hash chain intact", v["ok"], f"{v['events_in_scope']} events in Bob's workspace")
        sa_events = alice.get("/audit").json()
        check(
            "Super Admin sees organization events only",
            sa_events and all(e["action"].startswith(("org.", "admin.", "code.org")) for e in sa_events),
            f"{len(sa_events)} events",
        )
        with psycopg.connect(settings.dsn("lmqa_app", database=DEMO_DB)) as conn:
            try:
                conn.execute("update audit_events set action = 'x'")
                blocked = False
            except psycopg.Error:
                blocked = True
        check("runtime role cannot rewrite audit events", blocked)
        with psycopg.connect(settings.dsn("postgres", database=DEMO_DB), autocommit=True) as conn:
            conn.execute("alter table audit_events disable trigger audit_no_update")
            conn.execute(
                "update audit_events set payload = payload || '{\"tampered\": true}'"
                " where id = (select min(id) + 2 from audit_events)"
            )
            conn.execute("alter table audit_events enable trigger audit_no_update")
        v2 = alice.get("/audit/verify").json()
        v3 = bob.get("/audit/verify").json()
        check(
            "tampering by a database superuser is detected",
            not v2["ok"] or not v3["ok"],
            f"first bad event id {v2['first_bad_id'] or v3['first_bad_id']}",
        )

    if not args.keep:
        drop_database(settings, DEMO_DB)
        import shutil

        shutil.rmtree(ROOT / "data" / "demo", ignore_errors=True)
    passed = sum(ok for _, ok in results)
    print(f"\n{B}{G if passed == len(results) else R}{passed}/{len(results)} checks passed{X}")
    for label, ok in results:
        if not ok:
            print(f"  {R}✗ {label}{X}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
