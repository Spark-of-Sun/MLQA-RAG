"""Simulate the whole product workflow end to end, through the real HTTP API, and check every outcome.

  make demo            (or: uv run python tools/demo.py [--keep])

What is real: the gateway and every service in-process over ASGI, PostgreSQL with row-level security, the
public corpus documents, Gemini embeddings and answers, the citation validator, the audit chain.
Sign-in is real too (R-27, R-89): every cast member is a real account in the Auth0 tenant, signed in once
through Universal Login with tools/auth_harness.py (labels demo-alice ... demo-frank). The gateway verifies
their access tokens against the tenant's JWKS. Nothing in this script signs a token; see tools/real_identity.py.

It uses a separate database, `lmqa_demo`, recreated on every run, so your real data is never touched.

Cast: Alice creates "Hale & Partners LLP" (Super Admin). Bob joins as admin with the Organization Code
(workspace "Litigation"). Carol joins Bob's workspace as a tenant with the Admin Code. Dave creates a second
organization, a hospital; Erin is its admin. Isolation is checked from every wrong position.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
import warnings
from typing import Any

import psycopg

from lmqa_db import connect_role as connect
from lmqa_db.migrate import drop_database, migrate
from lmqa_models.envfile import ROOT
from lmqa_models.settings import load_settings

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402
from real_identity import Identity, load  # noqa: E402

from gateway.app import create_app  # noqa: E402

DEMO_DB = "lmqa_demo"
CAST = ["demo-alice", "demo-bob", "demo-carol", "demo-dave", "demo-erin", "demo-frank"]
CORPUS = ROOT / "corpus" / "data"
CONTRACT = "edgar-0001104659-24-041548-tm2410073d11_ex10-2.htm"  # separation agreement (SEC EDGAR)
DRUG_LABEL = "dailymed-5da82411.xml"  # metoprolol tartrate label (DailyMed)
CAROL_WITNESSES = b"""Witness preparation note - Rivera Logistics

Deposition of the warehouse supervisor is scheduled for 22 April 2025 at the downtown office.

The supervisor will testify about the loading dock incident of 3 February 2025.
"""
BOB_BRIEFING = b"""Briefing for Carol - privileged

The opposing counsel in the Rivera matter is Morgan & Pike LLP.

Settlement authority for the Rivera matter is capped at USD 250,000 until the client meeting on 30 April 2025.
"""
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
    print(
        f"   {G + '✓' if ok else R + '✗'}{X} {label}" + (f" {D}({detail}){X}" if detail else ""),
        flush=True,
    )
    return ok


def step(title: str) -> None:
    print(f"\n{B}▸ {title}{X}", flush=True)


class User:
    def __init__(self, client: TestClient, identity: Identity) -> None:
        self.name = identity.name
        self.label = identity.label.removeprefix("demo-")
        self.email = identity.email
        self.client = client
        self.headers = identity.headers

    def get(self, path: str) -> Any:
        return self.client.get(f"/v1{path}", headers=self.headers)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.client.post(f"/v1{path}", headers=self.headers, json=body or {})

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/v1{path}", headers=self.headers)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self.client.patch(f"/v1{path}", headers=self.headers, json=body)

    def upload(
        self,
        filename: str,
        data: bytes,
        visibility: str,
        title: str | None = None,
        share_with: list[str] | None = None,
    ) -> Any:
        form: dict[str, Any] = {"visibility": visibility, **({"title": title} if title else {})}
        if share_with:
            form["share_with"] = share_with
        return self.client.post(
            "/v1/documents", headers=self.headers, files={"file": (filename, data)}, data=form
        )

    def ask(self, question: str, conversation_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"question": question}
        if conversation_id:
            body["conversation_id"] = conversation_id
        resp = self.post("/queries", body)
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
            print(
                f"     {R}⊘ A claim could not be verified and was removed{X} {D}({seg['reason']}){X}"
            )
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


def main() -> int:  # noqa: C901, PLR0915 - one linear flow; splitting it is a DEV-33 follow-up
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

    cast = load(CAST, base.auth0_claims_namespace)
    settings = base.with_overrides(
        db_name=DEMO_DB,
        data_dir=ROOT / "data" / "demo",
    )
    print(
        f"{B}LMQA workflow demo{X}  {D}database={DEMO_DB}  models={' -> '.join(settings.llm_models)}{X}"
    )
    drop_database(settings, DEMO_DB)
    migrate(settings, DEMO_DB)

    app = create_app(settings, resume_jobs=False)
    with TestClient(app) as client:
        alice = User(client, cast["demo-alice"])
        bob = User(client, cast["demo-bob"])
        carol = User(client, cast["demo-carol"])
        dave = User(client, cast["demo-dave"])
        erin = User(client, cast["demo-erin"])

        step("Sign-in and token checks (gateway, blueprint G3.1)")
        check("health is public", client.get("/v1/health").status_code == 200)
        check("no token -> 401", client.get("/v1/me").status_code == 401)
        real = alice.headers["authorization"]
        tampered = real[:-4] + ("AAAA" if not real.endswith("AAAA") else "BBBB")
        check(
            "real token with a tampered signature -> 401",
            client.get("/v1/me", headers={"authorization": tampered}).status_code == 401,
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
        check(
            "code panel shows lookup id and uses, never the code",
            "code" not in info and info["uses"] == 0,
        )

        step("Path B: Bob joins as admin with the Organization Code")
        bad1 = bob.post(
            "/onboarding/join-admin", {"code": "NOT-A-CODE", "workspace_name": "Litigation"}
        )
        tampered = org_code[:-3] + ("0" if org_code[-3] != "0" else "1") + org_code[-2:]
        bad2 = bob.post(
            "/onboarding/join-admin", {"code": tampered, "workspace_name": "Litigation"}
        )
        check(
            "bad codes get one identical error",
            bad1.status_code == bad2.status_code == 400 and bad1.json() == bad2.json(),
            bad1.json()["detail"],
        )
        r = bob.post("/onboarding/join-admin", {"code": org_code, "workspace_name": "Litigation"})
        check(
            "join request accepted, pending approval",
            r.status_code == 201 and r.json()["status"] == "pending",
        )
        check(
            "pending admin cannot reach documents (403)", bob.get("/documents").status_code == 403
        )
        admins = alice.get("/org/admins").json()
        check(
            "request appears in Manage Admins",
            len(admins) == 1 and admins[0]["status"] == "pending",
        )
        r = alice.post(f"/org/admins/{admins[0]['id']}/approve")
        check(
            "Alice approves Bob", r.status_code == 200 and r.json()["workspace_status"] == "active"
        )
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
            preview.get("workspace") == "Litigation" and preview.get("admin") == bob.name,
            json.dumps(preview),
        )
        check("preview does not consume a use", bob.get("/workspace/code").json()["uses"] == 0)
        check(
            "Carol requests to join",
            carol.post("/onboarding/join-tenant", {"code": admin_code}).status_code == 201,
        )
        members = bob.get("/workspace/members").json()
        check(
            "Bob approves Carol",
            bob.post(f"/workspace/members/{members[0]['id']}/approve").status_code == 200,
        )

        step("Second organization: Dave creates a hospital, Erin is its admin")
        dave.post("/onboarding/organization", {"name": "St. Mary's Hospital", "kind": "medical"})
        erin.post(
            "/onboarding/join-admin",
            {"code": dave.post("/org/code").json()["code"], "workspace_name": "Cardiology"},
        )
        dave.post(f"/org/admins/{dave.get('/org/admins').json()[0]['id']}/approve")
        check("Erin is an active admin", erin.get("/me").json()["membership"]["active"])

        step("Uploads: real public documents and a private memo")
        contract = bob.upload(
            CONTRACT,
            (CORPUS / CONTRACT).read_bytes(),
            "private",
            "Separation and Release Agreement (American National Bankshares)",
        ).json()
        memo = carol.upload(
            "rivera-intake-memo.txt", CAROL_MEMO, "private", "Rivera Logistics intake memo"
        ).json()
        label = erin.upload(
            DRUG_LABEL,
            (CORPUS / DRUG_LABEL).read_bytes(),
            "private",
            "Metoprolol tartrate tablets: prescribing information",
        ).json()
        check(
            "nobody can upload with the removed `workspace` visibility (refused)",
            carol.upload("x.txt", b"some text here", "workspace").status_code in {400, 403},
        )
        check(
            "disguised file rejected (magic bytes)",
            bob.upload("fake.pdf", b"not a pdf", "private").status_code == 400,
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
        check(
            "Carol sees her private memo, not Bob's private contract",
            memo["id"] in ids_carol and contract["id"] not in ids_carol,
        )
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
        check(
            "Super Admin has no route to documents (404)",
            alice.get("/documents").status_code == 404,
        )
        check(
            "Super Admin has no route to questions (404)",
            alice.post("/queries", {"question": "hello?"}).status_code == 404,
        )
        check(
            "tenant has no route to Manage Tenants (404)",
            carol.get("/workspace/members").status_code == 404,
        )

        step("Questions with verified citations (blueprint 11.6)")
        q1 = "When must the severance benefit be paid, and what condition must be met first?"
        a1 = bob.ask(q1)
        show_answer("Bob", q1, a1)
        check(
            "answered with verified, cited sentences",
            a1.get("outcome") in {"answered", "partial"} and a1["stats"]["verified"] >= 1,
        )
        cited_docs = {c["document_id"] for c in a1.get("citations", [])}
        check(
            "every citation points into Bob's visible documents",
            bool(cited_docs) and cited_docs <= ids_bob,
        )
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

        step("Chats: follow-ups continue a conversation, and chats stay private")
        conv_c = a2.get("conversation_id", "")
        conv_b = a1.get("conversation_id", "")
        check(
            "a new chat is created by its first message (Bob and Carol each have their own)",
            bool(conv_c) and bool(conv_b) and conv_c != conv_b,
            a2.get("conversation_title", ""),
        )
        q2b = "By what date do they intend to cure it?"
        a2b = carol.ask(q2b, conv_c)
        show_answer("Carol (follow-up)", q2b, a2b)
        print(f"     {D}interpreted as: {a2b.get('standalone_question')}{X}")
        check(
            "the follow-up is rewritten with the earlier context",
            "rivera" in a2b.get("standalone_question", "").lower()
            and a2b.get("conversation_id") == conv_c,
        )
        check(
            "the follow-up is answered from the memo, with a citation",
            any("4 April 2025" in s.get("text", "") for s in a2b.get("segments", []))
            and any(c["document_id"] == memo["id"] for c in a2b.get("citations", [])),
        )
        chats_c = carol.get("/conversations").json()
        check(
            "Carol's chat list shows the chat with both turns",
            any(c["id"] == conv_c and c["turns"] == 2 for c in chats_c),
            f"{len(chats_c)} chat(s)",
        )
        full = carol.get(f"/conversations/{conv_c}").json()
        check(
            "re-opening the chat continues where she left off",
            [t["question"] for t in full.get("turns", [])] == [q2, q2b]
            and all(c.get("text") for t in full["turns"] for c in t["citations"]),
        )
        check(
            "Bob's chat list does not include Carol's chat",
            all(c["id"] != conv_c for c in bob.get("/conversations").json()),
        )
        check(
            "Bob (her admin) cannot open Carol's chat (404)",
            bob.get(f"/conversations/{conv_c}").status_code == 404,
        )
        check(
            "Bob cannot post into Carol's chat (404)",
            bob.post("/queries", {"question": "What else?", "conversation_id": conv_c}).status_code
            == 404,
        )
        check(
            "Erin (other organization) cannot open it (404)",
            erin.get(f"/conversations/{conv_c}").status_code == 404,
        )
        check(
            "Super Admin has no route to chats (404)",
            alice.get("/conversations").status_code == 404,
        )
        renamed = carol.client.patch(
            f"/v1/conversations/{conv_c}",
            headers=carol.headers,
            json={"title": "Rivera cure period"},
        )
        check(
            "Carol can rename her chat",
            renamed.status_code == 200 and renamed.json()["title"] == "Rivera cure period",
        )
        check(
            "Bob cannot rename it (404)",
            bob.client.patch(
                f"/v1/conversations/{conv_c}", headers=bob.headers, json={"title": "x"}
            ).status_code
            == 404,
        )
        check(
            "Bob cannot delete it (404)", bob.delete(f"/conversations/{conv_c}").status_code == 404
        )
        check("Bob deletes his own chat", bob.delete(f"/conversations/{conv_b}").status_code == 204)
        check(
            "its questions are gone with it", bob.get(f"/queries/{a1.get('id')}").status_code == 404
        )
        with connect(settings, "lmqa_app", database=DEMO_DB) as conn:
            with connect(settings, "svc_identity", database=DEMO_DB) as sys_conn:
                bob_row = sys_conn.execute(
                    "select id from users where auth0_sub = %s", [cast["demo-bob"].sub]
                ).fetchone()
            assert bob_row is not None
            with conn.transaction():
                conn.execute("select set_config('app.user_id', %s, true)", [str(bob_row[0])])
                seen = conn.execute(
                    "select (select count(*) from conversations where id = %s),"
                    " (select count(*) from queries where conversation_id = %s)",
                    [conv_c, conv_c],
                ).fetchone()
            check(
                "in SQL, Bob's context sees 0 of Carol's chat rows and 0 of its questions",
                seen is not None and seen[0] == 0 and seen[1] == 0,
            )

        step("Sharing: a member shares with the admin, the admin shares with selected members")
        frank = User(client, cast["demo-frank"])
        frank.post("/onboarding/join-tenant", {"code": admin_code})
        pending = [x for x in bob.get("/workspace/members").json() if x["status"] == "pending"]
        bob.post(f"/workspace/members/{pending[0]['id']}/approve")
        ids = {u.label: u.get("/me").json()["user"]["id"] for u in (bob, carol, frank)}
        witness = carol.upload(
            "witness-note.txt",
            CAROL_WITNESSES,
            "private",
            "Rivera witness preparation note",
            ["admin"],
        ).json()
        check(
            "Carol shares a document with her admin; it is labelled 'shared by you'",
            witness.get("access") == "shared"
            and witness.get("shared_by") == "you"
            and [x["role"] for x in witness.get("shared_with", [])] == ["admin"],
        )
        check(
            "a member cannot share with another member (403)",
            carol.upload("x.txt", b"some text here", "private", None, [ids["frank"]]).status_code
            == 403,
        )
        briefing = bob.upload(
            "briefing.txt", BOB_BRIEFING, "private", "Briefing for Carol", [ids["carol"]]
        ).json()
        check(
            "Bob shares a document with Carol only",
            briefing.get("access") == "shared"
            and [x["id"] for x in briefing.get("shared_with", [])] == [ids["carol"]],
        )
        check(
            "the admin cannot share with someone outside the workspace (400)",
            bob.upload("x.txt", b"some text here", "private", None, [str(uuid.uuid4())]).status_code
            == 400,
        )
        wait_ready(carol, [witness["id"], briefing["id"]])
        docs_bob = {d["id"]: d for d in bob.get("/documents").json()}
        docs_carol = {d["id"]: d for d in carol.get("/documents").json()}
        ids_frank = {d["id"] for d in frank.get("/documents").json()}
        check(
            "Bob sees Carol's shared note, labelled 'shared by member'",
            docs_bob.get(witness["id"], {}).get("shared_by") == "member",
        )
        check("Bob still does not see Carol's private memo", memo["id"] not in docs_bob)
        check(
            "Carol sees Bob's briefing, labelled 'shared by admin'",
            docs_carol.get(briefing["id"], {}).get("shared_by") == "admin",
        )
        check(
            "Frank sees neither (and the workspace contract is still there)",
            witness["id"] not in ids_frank
            and briefing["id"] not in ids_frank
            and contract["id"] in ids_frank,
        )
        check(
            "Frank gets 404 for the briefing; Bob cannot delete Carol's note (403)",
            frank.get(f"/documents/{briefing['id']}").status_code == 404
            and bob.delete(f"/documents/{witness['id']}").status_code == 403,
        )
        with connect(settings, "lmqa_app", database=DEMO_DB) as conn:

            def visible_chunks(user_id: str, doc_id: str) -> int:
                with conn.transaction():
                    conn.execute("select set_config('app.user_id', %s, true)", [user_id])
                    row = conn.execute(
                        "select count(*) from chunks where document_id = %s", [doc_id]
                    ).fetchone()
                return int(row[0]) if row else -1

            check(
                "in SQL, retrieval sees the shared passages: Bob gets Carol's note, Carol gets the briefing",
                visible_chunks(ids["bob"], witness["id"]) > 0
                and visible_chunks(ids["carol"], briefing["id"]) > 0,
            )
            check(
                "in SQL, Frank's context sees 0 passages of either",
                visible_chunks(ids["frank"], witness["id"]) == 0
                and visible_chunks(ids["frank"], briefing["id"]) == 0,
            )
            try:
                with conn.transaction():
                    conn.execute("select set_config('app.user_id', %s, true)", [ids["frank"]])
                    with connect(settings, "svc_identity", database=DEMO_DB) as sc:
                        org_ws = sc.execute(
                            "select org_id, workspace_id from documents where id = %s", [memo["id"]]
                        )
                        org, ws = org_ws.fetchone() or (None, None)
                    conn.execute(
                        "insert into document_shares (org_id, workspace_id, document_id, owner_id, user_id)"
                        " values (%s, %s, %s, %s, %s)",
                        [org, ws, memo["id"], ids["carol"], ids["frank"]],
                    )
                forged = True
            except psycopg.Error:
                forged = False
            check("in SQL, Frank cannot forge a share of Carol's memo to himself", not forged)

        step("Profiles: members edit their details, their admin can read them")
        r = carol.patch(
            "/profile",
            {"name": "Carol M. Diaz", "job_title": "Associate", "phone": "+1 415 555 0100"},
        )
        check(
            "Carol updates her profile",
            r.status_code == 200 and r.json().get("job_title") == "Associate",
        )
        check(
            "an invalid phone number is rejected (400)",
            carol.patch("/profile", {"phone": "call me!"}).status_code == 400,
        )
        check(
            "her edited name survives the next sign-in (Auth0 still says 'Carol Diaz')",
            carol.get("/me").json()["user"]["name"] == "Carol M. Diaz",
        )
        row_c = next(
            (x for x in bob.get("/workspace/members").json() if x["user_id"] == ids["carol"]),
            {},
        )
        check(
            "Bob sees Carol's profile in Manage members",
            row_c.get("name") == "Carol M. Diaz" and row_c.get("phone") == "+1 415 555 0100",
        )
        check(
            "Manage members counts questions (not chats), tokens and documents shared with Bob",
            row_c.get("questions") == 2
            and row_c.get("tokens", 0) > 0
            and row_c.get("shared_with_you") == 1,
            f"questions={row_c.get('questions')} tokens≈{row_c.get('tokens')} shared={row_c.get('shared_with_you')}",
        )
        check(
            "Manage members counts Carol's private documents and the documents Bob shared with her",
            row_c.get("private_documents") == 1
            and row_c.get("shared_with_them") == 1
            and row_c.get("shared_with_workspace") == 1,
            f"private={row_c.get('private_documents')} shared by Bob={row_c.get('shared_with_them')}",
        )
        check(
            "a member has no route to other members' profiles (404)",
            carol.get("/workspace/members").status_code == 404,
        )

        step("Audit sections and filters")
        lib_c = carol.get("/audit?category=library").json()
        check(
            "Carol's Library section: only document events, including Bob's briefing shared with her",
            lib_c
            and all(e["action"].startswith("document.") for e in lib_c)
            and any(e["target_id"] == briefing["id"] for e in lib_c),
            f"{len(lib_c)} events",
        )
        check(
            "Frank's audit does not show the briefing shared with Carol only",
            all(e["target_id"] != briefing["id"] for e in frank.get("/audit").json()),
        )
        chats_audit = carol.get("/audit?category=chats").json()
        acts = {e["action"] for e in chats_audit}
        check(
            "Carol's Chats section: chat started, renamed and each question",
            {"conversation.created", "conversation.renamed", "query.answered"} <= acts
            and all(a.startswith(("query.", "conversation.")) for a in acts),
        )
        all_c = carol.get("/audit").json()
        check(
            "Carol's All activity includes her approval and profile change",
            {"tenant.approve", "profile.updated"} <= {e["action"] for e in all_c},
        )
        vc = carol.get("/audit/verify")
        check("a member can verify the hash chain", vc.status_code == 200 and vc.json()["ok"])
        memo_events = [
            e for e in bob.get("/audit?category=library").json() if e["target_id"] == memo["id"]
        ]
        check(
            "Bob's audit shows Carol's private memo without its title",
            memo_events and all("title" not in e["payload"] for e in memo_events),
        )
        probe = bob.get("/audit?q=Rivera%20Logistics%20intake").json()
        check(
            "searching for the private memo's title finds nothing for Bob",
            all(e["target_id"] != memo["id"] for e in probe),
        )
        by_carol = bob.get(f"/audit?category=members&actor={ids['Carol Diaz']}").json()
        check(
            "filters combine: Members section + person = Carol",
            by_carol
            and all(
                e["actor_name"] == "Carol M. Diaz"
                and e["action"].startswith(("tenant.", "profile."))
                for e in by_carol
            ),
        )
        check(
            "date filter: nothing before 2001",
            bob.get("/audit?until=2001-01-01T00:00:00Z").json() == [],
        )
        check(
            "an unknown section is rejected (400)",
            bob.get("/audit?category=billing").status_code == 400,
        )

        step("Database is the final authority (direct SQL as the runtime role)")
        with connect(settings, "lmqa_app", database=DEMO_DB) as conn:
            no_ctx = conn.execute("select count(*) from chunks").fetchone()
            check("no context -> 0 chunks visible", no_ctx is not None and no_ctx[0] == 0)
            with connect(settings, "svc_identity", database=DEMO_DB) as sys_conn:
                erin_row = sys_conn.execute(
                    "select id from users where auth0_sub = %s", [cast["demo-erin"].sub]
                ).fetchone()
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
            sa_events
            and all(e["action"].startswith(("org.", "admin.", "code.org")) for e in sa_events),
            f"{len(sa_events)} events",
        )
        with connect(settings, "lmqa_app", database=DEMO_DB) as conn:
            try:
                conn.execute("update audit_events set action = 'x'")
                blocked = False
            except psycopg.Error:
                blocked = True
        check("runtime role cannot rewrite audit events", blocked)
        with connect(settings, "postgres", database=DEMO_DB) as conn:
            # A superuser can switch triggers off for its own session; the chain still shows the change.
            conn.execute("set local session_replication_role = replica")
            conn.execute(
                "update audit_events set meta = meta || '{\"tampered\": true}'"
                " where id = (select min(id) + 2 from audit_events)"
            )
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
