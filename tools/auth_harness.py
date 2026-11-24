"""Auth harness (blueprint 18, G0.7): a minimal, real Auth0 relying party for backend stages before the frontend.

Authorization Code with PKCE against the tenant's `auth_harness` client (infra/auth0). Playwright drives the
Universal Login page with a virtual WebAuthn authenticator; this server receives the callback, exchanges the code,
and writes the tokens to `data/auth_harness/<label>.json` (mode 0600) for the test that asked for them. Tokens are
never printed or logged.

    python tools/auth_harness.py serve                     # listens on 127.0.0.1:8765
    python tools/auth_harness.py url --label admin [--org <auth0 org id>] [--audience main|onboarding]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from lmqa_models.envfile import ROOT, merged_env

PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
STATE_DIR = ROOT / "data" / "auth_harness"
_PENDING: dict[str, dict[str, str]] = {}
_LOCK = threading.Lock()


def _env(name: str) -> str:
    value = merged_env().get(name)
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def authorize_url(label: str, *, org: str | None, audience: str) -> str:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(24)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    pending = {"label": label, "verifier": verifier}
    (STATE_DIR / f"pending-{state}.json").write_text(json.dumps(pending), encoding="utf-8")
    params = {
        "response_type": "code",
        "client_id": _env("AUTH0_CLIENT_ID_HARNESS"),
        "redirect_uri": REDIRECT,
        "scope": "openid profile email offline_access",
        "audience": _env(
            "AUTH0_AUDIENCE_MAIN" if audience == "main" else "AUTH0_AUDIENCE_ONBOARDING"
        ),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if org:
        params["organization"] = org
    return f"https://{_env('AUTH0_DOMAIN')}/authorize?{urlencode(params)}"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:  # no request logging: URLs carry codes
        return

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path != "/callback":
            self.send_error(404)
            return
        query = parse_qs(url.query)
        state = (query.get("state") or [""])[0]
        pending_file = STATE_DIR / f"pending-{state}.json"
        if not state or not pending_file.is_file() or "code" not in query:
            self.send_error(400, "unknown state or missing code")
            return
        pending = json.loads(pending_file.read_text(encoding="utf-8"))
        pending_file.unlink()
        resp = httpx.post(
            f"https://{_env('AUTH0_DOMAIN')}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": _env("AUTH0_CLIENT_ID_HARNESS"),
                "client_secret": _env("AUTH0_CLIENT_SECRET_HARNESS"),
                "code": query["code"][0],
                "redirect_uri": REDIRECT,
                "code_verifier": pending["verifier"],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            self.send_error(502, "token exchange refused")
            return
        out = STATE_DIR / f"{pending['label']}.json"
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(resp.json(), fh)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"signed in; you can close this window")


def read_tokens(label: str) -> dict[str, str]:
    return json.loads((STATE_DIR / f"{label}.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    u = sub.add_parser("url")
    u.add_argument("--label", required=True)
    u.add_argument("--org")
    u.add_argument("--audience", choices=["main", "onboarding"], default="main")
    args = parser.parse_args()
    if args.cmd == "url":
        print(authorize_url(args.label, org=args.org, audience=args.audience))
        return 0
    server = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    print(f"auth harness listening on {REDIRECT}", file=sys.stderr)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
