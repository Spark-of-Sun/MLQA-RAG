"""Simulate signed-in browsers against the real production frontend and check role routing and the BFF.

  make demo-web        (runs `make demo` first if the lmqa_demo database does not exist)

Starts a second gateway on 127.0.0.1:8001 (demo database, the real Auth0 tenant) and the built Next.js app on
http://localhost:3001, then requests pages as Alice (Super Admin), Bob (admin), Carol (member) and a brand-new
user. Each is a real Auth0 account signed in through the auth harness (labels demo-alice, demo-bob, demo-carol,
demo-newcomer; see tools/real_identity.py). Their real access tokens are wrapped in an Auth0 SDK session cookie
with the SDK's testing helper; no token is signed locally and the gateway verifies each one against Auth0.
Your running app on :3000/:8000 is not touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
import warnings
from typing import Any

import httpx
import psycopg
import uvicorn

warnings.filterwarnings("ignore")
import demo  # noqa: E402  (tools/demo.py: constants, check helpers)
from real_identity import load  # noqa: E402

from gateway.app import create_app  # noqa: E402
from lmqa_db import connect_role as connect  # noqa: E402
from lmqa_models.envfile import ROOT, merged_env  # noqa: E402
from lmqa_models.settings import load_settings  # noqa: E402

WEB = "http://localhost:3001"
API_PORT = 8001
check, step, results = demo.check, demo.step, demo.results


def demo_db_ready(settings: Any, subs: list[str]) -> bool:
    try:
        with connect(settings, "svc_identity", database=demo.DEMO_DB, connect_timeout=3) as conn:
            row = conn.execute(
                "select count(*) from users where auth0_sub = any(%s)", [subs]
            ).fetchone()
            return bool(row and row[0] >= 3)
    except psycopg.Error:
        return False


def session_cookie(token: str, sub: str, email: str, name: str) -> str:
    """Encrypt a session with the SDK's testing helper; the secret is read by node from its environment."""
    now = int(time.time())
    session = {
        "user": {"sub": sub, "email": email, "name": name},
        "tokenSet": {
            "accessToken": token,
            "expiresAt": now + 3600,
            "scope": "openid profile email",
        },
        "internal": {"sid": uuid.uuid4().hex, "createdAt": now},
    }
    script = (
        "const { generateSessionCookie } = await import('@auth0/nextjs-auth0/testing');"
        "const s = JSON.parse(await new Response(process.stdin).text());"
        "s.tokenSet.audience = process.env.AUTH0_AUDIENCE_MAIN;"
        "process.stdout.write(await generateSessionCookie(s, { secret: process.env.AUTH0_SESSION_SECRET }));"
    )
    out = subprocess.run(  # noqa: S603 - fixed argv
        ["node", "--input-type=module", "-e", script],  # noqa: S607
        cwd=ROOT / "frontend",
        input=json.dumps(session).encode(),
        capture_output=True,
        env={**os.environ, **merged_env()},
        check=True,
    )
    return out.stdout.decode()


def main() -> int:  # noqa: C901, PLR0915 - one linear flow; splitting it is a DEV-33 follow-up
    base = load_settings()
    cast = load(
        ["demo-alice", "demo-bob", "demo-carol", "demo-newcomer"], base.auth0_claims_namespace
    )
    settings = base.with_overrides(
        db_name=demo.DEMO_DB,
        data_dir=ROOT / "data" / "demo",
        api_port=API_PORT,
    )
    if not demo_db_ready(settings, [cast[k].sub for k in ("demo-alice", "demo-bob", "demo-carol")]):
        print("Preparing the demo database (tools/demo.py --keep) …", flush=True)
        subprocess.run([sys.executable, str(ROOT / "tools" / "demo.py"), "--keep"], check=True)  # noqa: S603
        results.clear()

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, resume_jobs=False),
            host="127.0.0.1",
            port=API_PORT,
            log_level="warning",
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    env = {
        **os.environ,
        **merged_env(),
        "APP_BASE_URL": WEB,
        "LMQA_API_INTERNAL_URL": f"http://127.0.0.1:{API_PORT}",
    }
    web = subprocess.Popen(
        ["pnpm", "exec", "next", "start", "--hostname", "127.0.0.1", "--port", "3001"],  # noqa: S607
        cwd=ROOT / "frontend",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{WEB}/", timeout=2).status_code == 200 and server.started:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        print(
            f"{demo.B}Frontend simulation{demo.X}  {demo.D}{WEB} -> gateway :{API_PORT} -> {demo.DEMO_DB}{demo.X}"
        )

        def browser(label: str) -> tuple[httpx.Client, str]:
            who = cast[label]
            token = who.token
            cookie = session_cookie(token, who.sub, who.email, who.name)
            client = httpx.Client(
                base_url=WEB, cookies={"__session": cookie}, timeout=120, follow_redirects=False
            )
            return client, token

        def where(client: httpx.Client, path: str) -> tuple[int, str]:
            r = client.get(path)
            return r.status_code, r.headers.get("location", "")

        alice, alice_token = browser("demo-alice")
        bob, bob_token = browser("demo-bob")
        carol, _ = browser("demo-carol")
        newbie, _ = browser("demo-newcomer")

        step("Sign-in robustness")
        loop = httpx.get(
            WEB.replace("localhost", "127.0.0.1") + "/auth/login?screen_hint=signup",
            follow_redirects=False,
        )
        check(
            "a login started at 127.0.0.1 is moved to localhost first",
            loop.status_code == 200 and f'url={WEB}/auth/login?screen_hint=signup"' in loop.text,
            f"HTTP {loop.status_code}",
        )
        stale = httpx.get(f"{WEB}/auth/callback?code=used&state=stale", follow_redirects=False)
        check(
            "a stale or replayed callback returns to the start page with a reason",
            stale.status_code in {302, 307} and "auth_error=" in stale.headers.get("location", ""),
            stale.headers.get("location", ""),
        )
        landing = httpx.get(f"{WEB}/?auth_error=invalid_state")
        check(
            "the start page explains it and offers sign-in",
            "already used or has expired" in landing.text,
        )

        step("Role routing after sign-in (blueprint 17.1)")
        check(
            "Super Admin lands on Manage admins", where(alice, "/home") == (307, "/manage-admins")
        )
        check("Super Admin is sent away from Ask", where(alice, "/chat") == (307, "/manage-admins"))
        check("admin lands on Ask", where(bob, "/home") == (307, "/chat"))
        check("member lands on Ask", where(carol, "/home") == (307, "/chat"))
        check("new user lands on onboarding", where(newbie, "/home") == (307, "/onboarding"))
        check("admin cannot open Manage admins (404)", bob.get("/manage-admins").status_code == 404)
        check(
            "member cannot open Manage members (404)",
            carol.get("/manage-tenants").status_code == 404,
        )
        check(
            "Super Admin cannot open Manage members (404)",
            alice.get("/manage-tenants").status_code == 404,
        )

        step("Pages render for the right roles")
        pages = [
            (alice, "/manage-admins", "Admins and workspaces"),
            (alice, "/audit", "Organization-level events"),
            (bob, "/chat", "Ask your documents"),
            (bob, "/library", "Selected members"),
            (bob, "/manage-tenants", "Questions counts every question asked, not chats"),
            (bob, "/audit?category=library", "Uploads, shares, indexing and deletions"),
            (bob, "/profile", "Profile"),
            (carol, "/library", "Share with my workspace admin"),
            (carol, "/audit", "Everything about you in this workspace"),
            (carol, "/audit?category=chats", "Chats you started, renamed or deleted"),
            (carol, "/profile", "Your workspace admin can see these details"),
            (alice, "/profile", "Only you can see these details"),
            (newbie, "/onboarding", "How will you use it?"),
        ]
        bodies: list[str] = []
        for client, path, text in pages:
            r = client.get(path)
            bodies.append(r.text)
            check(
                f"{path} renders", r.status_code == 200 and text in r.text, f"HTTP {r.status_code}"
            )

        step("Browser -> BFF -> gateway, with the token kept server-side")
        docs = bob.get("/api/backend/documents")
        check(
            "BFF lists documents for the admin", docs.status_code == 200 and len(docs.json()) >= 1
        )
        r = bob.post(
            "/api/backend/queries",
            headers={"origin": WEB},
            json={"question": "When must the severance benefit be paid?"},
        )
        answer = r.json() if r.status_code == 200 else {}
        check(
            "question answered through the BFF with verified citations",
            answer.get("outcome") in {"answered", "partial"} and answer["stats"]["verified"] >= 1,
            f"HTTP {r.status_code}, {answer.get('stats', {}).get('verified')} verified",
        )

        step("One chat, many questions: continue where you left off")
        chat_id = answer.get("conversation_id", "")
        before = {c["id"] for c in bob.get("/api/backend/conversations").json()}
        r = bob.post(
            "/api/backend/queries",
            headers={"origin": WEB},
            json={
                "question": "And what must the Executive sign first?",
                "conversation_id": chat_id,
            },
        )
        follow = r.json() if r.status_code == 200 else {}
        check(
            "the follow-up is added to the same chat",
            follow.get("conversation_id") == chat_id,
            f"HTTP {r.status_code}, searched as: {follow.get('standalone_question')}",
        )
        after = bob.get("/api/backend/conversations").json()
        check("no new chat was created for the follow-up", {c["id"] for c in after} == before)
        mine = next((c for c in after if c["id"] == chat_id), {})
        check(
            "the chat list shows one chat with both questions",
            mine.get("turns") == 2,
            mine.get("title", ""),
        )
        page = bob.get(f"/chat/{chat_id}")
        check(
            "the chat has its own address (/chat/<id>) to come back to",
            page.status_code == 200,
            f"HTTP {page.status_code}",
        )
        thread = bob.get(f"/api/backend/conversations/{chat_id}").json()
        check(
            "re-opening it returns the questions in order",
            [t["question"] for t in thread.get("turns", [])]
            == [
                "When must the severance benefit be paid?",
                "And what must the Executive sign first?",
            ],
        )
        check(
            "another person's chat address shows nothing (404)",
            carol.get(f"/api/backend/conversations/{chat_id}").status_code == 404,
        )
        check(
            "a malformed chat address is a 404 page", bob.get("/chat/not-a-chat").status_code == 404
        )

        step("Profile, sharing and audit through the BFF")
        prof = carol.get("/api/backend/profile")
        check(
            "a member reads her profile",
            prof.status_code == 200 and prof.json().get("role") == "tenant",
        )
        r = carol.patch(
            "/api/backend/profile",
            headers={"origin": WEB},
            json={"department": "Commercial disputes"},
        )
        check(
            "and updates it",
            r.status_code == 200 and r.json().get("department") == "Commercial disputes",
        )
        row = next(
            (
                m
                for m in bob.get("/api/backend/workspace/members").json()
                if m["email"] == cast["demo-carol"].email
            ),
            {},
        )
        check(
            "her admin sees the change and her usage counts",
            row.get("department") == "Commercial disputes" and row.get("questions", 0) >= 1,
            f"questions={row.get('questions')} tokens≈{row.get('tokens')} shared={row.get('shared_with_you')}",
        )
        labels = {d["title"]: d.get("shared_by") for d in bob.get("/api/backend/documents").json()}
        check(
            "the admin's library labels who shared each document",
            labels.get("Rivera witness preparation note") == "member"
            and labels.get("Briefing for Carol") == "you",
        )
        chats = carol.get("/api/backend/audit?category=chats").json()
        check(
            "the member's Chats audit section holds chat events only",
            bool(chats) and all(e["action"].startswith(("query.", "conversation.")) for e in chats),
            f"{len(chats)} events",
        )
        v = carol.get("/api/backend/audit/verify")
        check("the member can verify the hash chain", v.status_code == 200 and "ok" in v.json())

        step("Browser -> BFF security")
        r = bob.post(
            "/api/backend/queries",
            headers={"origin": "https://evil.example"},
            json={"question": "x?"},
        )
        check("cross-site POST refused by the BFF (403)", r.status_code == 403)
        r = alice.post(
            "/api/backend/queries", headers={"origin": WEB}, json={"question": "hello there?"}
        )
        check("Super Admin has no route to questions, even via the BFF (404)", r.status_code == 404)
        leaked = any(
            t in body
            for body in [*bodies, docs.text, json.dumps(answer)]
            for t in (alice_token, bob_token)
        )
        check("no access token appears in any page or API response", not leaked)
        csp = bob.get("/chat").headers.get("content-security-policy", "")
        check(
            "strict nonce CSP on app pages",
            "'strict-dynamic'" in csp and "nonce-" in csp and "frame-ancestors 'none'" in csp,
        )

        step("Documentation: public pages for everyone, private pages by role")
        anon = httpx.Client(base_url=WEB, timeout=60, follow_redirects=False)
        # A sentence from the body of each page: present only when the page is shown, absent behind the wall.
        public, member, admin, owner = (
            ("/docs/introduction", "Answer from general knowledge"),
            ("/docs/chats", "Hover over a chat to rename it"),
            ("/docs/managing-members", "Every question asked, not the number of chats"),
            ("/docs/the-owners-role", "No access rule lets your role read documents, passages"),
        )

        def reads(client: httpx.Client, page: tuple[str, str]) -> bool:
            r = client.get(page[0])
            return r.status_code == 200 and page[1] in r.text

        def walled(client: httpx.Client, page: tuple[str, str], wording: str) -> bool:
            r = client.get(page[0])
            return r.status_code == 200 and wording in r.text and page[1] not in r.text

        index = anon.get("/docs")
        check("anyone can open the docs home", index.status_code == 200)
        check(
            "the menu lists every page alike, with no lock or role marker",
            all(t in index.text for t in ("Managing admins", "Workspace audit", "Chats"))
            and "lucide-lock" not in index.text,
        )
        check("signed out: a public page is readable", reads(anon, public))
        check(
            "signed out: a member page shows the sign-in wall, and none of its text",
            walled(anon, member, "Sign in to read"),
        )
        check("the wall appears only on the page itself", "lucide-lock" in anon.get(member[0]).text)
        check(
            "a signed-in user without an approved membership gets the inactive wall",
            walled(newbie, member, "not active yet"),
        )
        check("member: reads member pages", reads(carol, member))
        check("member: admin pages are walled", walled(carol, admin, "for other roles"))
        check("member: Super Admin pages are walled", walled(carol, owner, "for other roles"))
        check("admin: reads admin and member pages", reads(bob, admin) and reads(bob, member))
        check("admin: Super Admin pages are walled", walled(bob, owner, "for other roles"))
        check(
            "Super Admin: reads every page",
            all(reads(alice, p) for p in (public, member, admin, owner)),
        )
        check("an unknown docs page is 404", anon.get("/docs/no-such-page").status_code == 404)
    finally:
        os.killpg(web.pid, 15)
        server.should_exit = True
        time.sleep(1)

    passed = sum(ok for _, ok in results)
    print(
        f"\n{demo.B}{demo.G if passed == len(results) else demo.R}{passed}/{len(results)} checks passed{demo.X}"
    )
    for label, ok in results:
        if not ok:
            print(f"  {demo.R}✗ {label}{demo.X}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
