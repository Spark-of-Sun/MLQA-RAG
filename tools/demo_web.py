"""Simulate signed-in browsers against the real production frontend and check role routing and the BFF.

  make demo-web        (runs `make demo` first if the lmqa_demo database does not exist)

Starts a second gateway on 127.0.0.1:8001 (demo database, demo token issuer) and the built Next.js app on
http://localhost:3001, then mints Auth0 SDK session cookies with the SDK's own testing helper and requests
pages as Alice (Super Admin), Bob (admin), Carol (member) and a brand-new user. What is simulated: only the
Auth0 login itself. Everything after it (proxy.ts, server layouts, the BFF, the gateway, RLS, Gemini) is real.
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

import httpx
import psycopg
import uvicorn

warnings.filterwarnings("ignore")
import demo  # noqa: E402  (tools/demo.py: IdP, constants, check helpers)

from gateway.app import create_app  # noqa: E402
from lmqa_models.envfile import ROOT, merged_env  # noqa: E402
from lmqa_models.settings import load_settings  # noqa: E402

WEB = "http://localhost:3001"
API_PORT = 8001
check, step, results = demo.check, demo.step, demo.results


def demo_db_ready(settings) -> bool:  # type: ignore[no-untyped-def]
    try:
        with psycopg.connect(settings.dsn("lmqa_system", database=demo.DEMO_DB), connect_timeout=3) as conn:
            row = conn.execute("select count(*) from users where email like '%%@hale-partners.example'").fetchone()
            return bool(row and row[0] >= 3)
    except psycopg.Error:
        return False


def session_cookie(token: str, sub: str, email: str, name: str) -> str:
    """Encrypt a session with the SDK's testing helper; the secret is read by node from its environment."""
    now = int(time.time())
    session = {
        "user": {"sub": sub, "email": email, "name": name},
        "tokenSet": {"accessToken": token, "expiresAt": now + 3600, "scope": "openid profile email"},
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


def main() -> int:
    base = load_settings()
    idp = demo.IdP(base.auth0_claims_namespace)
    settings = base.with_overrides(
        db_name=demo.DEMO_DB,
        auth0_issuer_override=demo.ISSUER,
        auth0_jwks_url_override=idp.jwks_url,
        auth0_audience=demo.AUDIENCE,
        data_dir=ROOT / "data" / "demo",
        api_port=API_PORT,
    )
    if not demo_db_ready(settings):
        print("Preparing the demo database (tools/demo.py --keep) …", flush=True)
        subprocess.run([sys.executable, str(ROOT / "tools" / "demo.py"), "--keep"], check=True)  # noqa: S603
        results.clear()

    with psycopg.connect(settings.dsn("lmqa_system", database=demo.DEMO_DB)) as conn:
        users = {
            r[0]: (r[1], r[2])
            for r in conn.execute("select email, auth0_sub, name from users where email like '%%.example'").fetchall()
        }

    server = uvicorn.Server(
        uvicorn.Config(create_app(settings, resume_jobs=False), host="127.0.0.1", port=API_PORT, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    env = {**os.environ, **merged_env(), "APP_BASE_URL": WEB, "LMQA_API_INTERNAL_URL": f"http://127.0.0.1:{API_PORT}"}
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
        print(f"{demo.B}Frontend simulation{demo.X}  {demo.D}{WEB} -> gateway :{API_PORT} -> {demo.DEMO_DB}{demo.X}")

        def browser(email: str, name: str) -> tuple[httpx.Client, str]:
            sub = users[email][0] if email in users else f"auth0|{uuid.uuid4().hex[:16]}"
            token = idp.token(sub, email, name)
            cookie = session_cookie(token, sub, email, name)
            client = httpx.Client(base_url=WEB, cookies={"__session": cookie}, timeout=120, follow_redirects=False)
            return client, token

        def where(client: httpx.Client, path: str) -> tuple[int, str]:
            r = client.get(path)
            return r.status_code, r.headers.get("location", "")

        alice, alice_token = browser("alice@hale-partners.example", "Alice Hale")
        bob, bob_token = browser("bob@hale-partners.example", "Bob Ortiz")
        carol, _ = browser("carol@hale-partners.example", "Carol Diaz")
        newbie, _ = browser(f"new-{uuid.uuid4().hex[:6]}@example.org", "New Person")

        step("Sign-in robustness")
        loop = httpx.get(
            WEB.replace("localhost", "127.0.0.1") + "/auth/login?screen_hint=signup", follow_redirects=False
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
        check("the start page explains it and offers sign-in", "already used or has expired" in landing.text)

        step("Role routing after sign-in (blueprint 17.1)")
        check("Super Admin lands on Manage admins", where(alice, "/home") == (307, "/manage-admins"))
        check("Super Admin is sent away from Ask", where(alice, "/chat") == (307, "/manage-admins"))
        check("admin lands on Ask", where(bob, "/home") == (307, "/chat"))
        check("member lands on Ask", where(carol, "/home") == (307, "/chat"))
        check("new user lands on onboarding", where(newbie, "/home") == (307, "/onboarding"))
        check("admin cannot open Manage admins (404)", bob.get("/manage-admins").status_code == 404)
        check("member cannot open Manage members (404)", carol.get("/manage-tenants").status_code == 404)
        check("Super Admin cannot open Manage members (404)", alice.get("/manage-tenants").status_code == 404)

        step("Pages render for the right roles")
        pages = [
            (alice, "/manage-admins", "Admins and workspaces"),
            (alice, "/audit", "Organization-level events"),
            (bob, "/chat", "Ask your documents"),
            (bob, "/library", "Shared documents are visible"),
            (bob, "/manage-tenants", "Manage members"),
            (carol, "/library", "Documents you upload are private"),
            (newbie, "/onboarding", "How will you use it?"),
        ]
        bodies: list[str] = []
        for client, path, text in pages:
            r = client.get(path)
            bodies.append(r.text)
            check(f"{path} renders", r.status_code == 200 and text in r.text, f"HTTP {r.status_code}")

        step("Browser -> BFF -> gateway, with the token kept server-side")
        docs = bob.get("/api/backend/documents")
        check("BFF lists documents for the admin", docs.status_code == 200 and len(docs.json()) >= 1)
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
        r = bob.post("/api/backend/queries", headers={"origin": "https://evil.example"}, json={"question": "x?"})
        check("cross-site POST refused by the BFF (403)", r.status_code == 403)
        r = alice.post("/api/backend/queries", headers={"origin": WEB}, json={"question": "hello there?"})
        check("Super Admin has no route to questions, even via the BFF (404)", r.status_code == 404)
        leaked = any(t in body for body in [*bodies, docs.text, json.dumps(answer)] for t in (alice_token, bob_token))
        check("no access token appears in any page or API response", not leaked)
        csp = bob.get("/chat").headers.get("content-security-policy", "")
        check(
            "strict nonce CSP on app pages",
            "'strict-dynamic'" in csp and "nonce-" in csp and "frame-ancestors 'none'" in csp,
        )
    finally:
        os.killpg(web.pid, 15)
        server.should_exit = True
        time.sleep(1)

    passed = sum(ok for _, ok in results)
    print(f"\n{demo.B}{demo.G if passed == len(results) else demo.R}{passed}/{len(results)} checks passed{demo.X}")
    for label, ok in results:
        if not ok:
            print(f"  {demo.R}✗ {label}{demo.X}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
