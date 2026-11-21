"""Check that every real dependency is configured and reachable. Prints names and results, never values.

Auth0 checks are read-only: OIDC discovery, JWKS, a client-credentials probe that only classifies the error,
and (when the M2M app is allowed to) reads of the API and application settings through the Management API.
"""

from __future__ import annotations

import sys
from typing import Any

import httpx
import psycopg

from generation.llm_client import LLMClient, LLMError
from lmqa_models.envfile import merged_env
from lmqa_models.settings import EMBEDDING_DIM, load_settings
from lmqa_vectorstore import Embedder, EmbeddingError

OK, WARN, FAIL = "\033[32m  ok \033[0m", "\033[33mwarn \033[0m", "\033[31mFAIL \033[0m"
failures = 0


def report(status: str, what: str, detail: str = "") -> None:
    global failures
    failures += status == FAIL
    print(f"[{status}] {what}" + (f": {detail}" if detail else ""), flush=True)


def check_settings(env: dict[str, str]) -> None:
    print("\nSettings (.env / .secrets / .secrets.generated)")
    required = {
        "AUTH0_DOMAIN": "Auth0 tenant domain",
        "AUTH0_CLIENT_ID_BFF": "Auth0 Regular Web Application client id",
        "AUTH0_CLIENT_SECRET_BFF": "Auth0 Regular Web Application client secret",
        "AUTH0_AUDIENCE_MAIN": "Auth0 API identifier (audience)",
        "AUTH0_SESSION_SECRET": "session cookie encryption secret",
        "CODE_PEPPER_V1": "join-code pepper",
        "LMQA_DB_APP_PASSWORD": "database password",
        "GEMINI_API_KEY": "Google AI Studio key (embeddings always; answers when LLM_PROVIDER=gemini)",
    }
    for key, what in required.items():
        present = bool(env.get(key)) or (key == "GEMINI_API_KEY" and bool(env.get("GOOGLE_API_KEY")))
        report(OK if present else FAIL, key, "set" if present else f"missing ({what})")
    s = load_settings()
    report(OK, "LLM_PROVIDER", s.llm_provider)
    report(OK if s.llm_models else FAIL, "answer models", " -> ".join(s.llm_models) or "LLM_MODEL is not set")


def check_database() -> None:
    print("\nDatabase")
    s = load_settings()
    try:
        with psycopg.connect(s.dsn("lmqa_owner"), connect_timeout=5) as conn:
            version = conn.execute("show server_version").fetchone()
            vec = conn.execute("select extversion from pg_extension where extname = 'vector'").fetchone()
            applied = conn.execute("select count(*) from schema_migrations").fetchone()
            forced = conn.execute(
                "select count(*) from pg_class where relname in"
                " ('documents', 'chunks', 'queries', 'retrieval_records', 'conversations', 'document_shares')"
                " and relrowsecurity and relforcerowsecurity"
            ).fetchone()
            roles = conn.execute(
                "select rolname, rolbypassrls, rolsuper from pg_roles where rolname like 'lmqa_%' order by 1"
            ).fetchall()
        report(OK, "PostgreSQL", f"{version[0] if version else '?'} on {s.db_host}:{s.db_port}")
        report(OK if vec else FAIL, "pgvector", vec[0] if vec else "extension missing")
        report(OK, "migrations", f"{applied[0] if applied else 0} applied")
        report(
            OK if forced and forced[0] == 6 else FAIL,
            "row-level security",
            f"FORCE RLS on {forced[0] if forced else 0}/6 content tables",
        )
        app_ok = any(r[0] == "lmqa_app" and not r[1] and not r[2] for r in roles)
        report(OK if app_ok else FAIL, "lmqa_app role", "non-superuser, NOBYPASSRLS" if app_ok else "misconfigured")
        with psycopg.connect(s.dsn("lmqa_app"), connect_timeout=5) as conn:
            leaked = conn.execute("select count(*) from documents").fetchone()
        report(OK if leaked and leaked[0] == 0 else FAIL, "fail closed", "lmqa_app without a context sees 0 rows")
    except psycopg.OperationalError as exc:
        report(FAIL, "PostgreSQL", f"{type(exc).__name__}: run `make db` and `make migrate`")
    except psycopg.errors.UndefinedTable:
        report(FAIL, "migrations", "not applied: run `make migrate`")


def check_auth0(env: dict[str, str]) -> None:
    print("\nAuth0")
    s = load_settings()
    domain = s.auth0_domain
    if not domain:
        report(FAIL, "Auth0", "AUTH0_DOMAIN missing")
        return
    try:
        disc = httpx.get(f"https://{domain}/.well-known/openid-configuration", timeout=15)
        issuer = disc.json().get("issuer") if disc.status_code == 200 else None
        report(
            OK if issuer == s.auth0_issuer else FAIL,
            "OIDC discovery",
            f"issuer {issuer}" if issuer else f"HTTP {disc.status_code}",
        )
        jwks = httpx.get(s.auth0_jwks_url, timeout=15)
        report(OK if jwks.status_code == 200 and jwks.json().get("keys") else FAIL, "JWKS", f"HTTP {jwks.status_code}")
    except httpx.HTTPError as exc:
        report(FAIL, "Auth0 reachable", type(exc).__name__)
        return

    cid, secret = env.get("AUTH0_CLIENT_ID_BFF"), env.get("AUTH0_CLIENT_SECRET_BFF")
    if cid and secret:
        # A web app usually may not use client_credentials: 403 means the id and secret were accepted.
        resp = httpx.post(
            f"https://{domain}/oauth/token",
            timeout=15,
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": secret,
                "audience": s.auth0_audience or "",
            },
        )
        err = resp.json().get("error") if "json" in resp.headers.get("content-type", "") else None
        if resp.status_code == 200 or (resp.status_code == 403 and err in {"unauthorized_client", "access_denied"}):
            report(OK, "web app credentials", "client id and secret accepted")
        else:
            report(
                FAIL, "web app credentials", f"HTTP {resp.status_code} {err or ''} (check AUTH0_CLIENT_ID_BFF / SECRET)"
            )

    token = None
    mcid, msecret = env.get("AUTH0_M2M_CLIENT_ID"), env.get("AUTH0_M2M_CLIENT_SECRET")
    if mcid and msecret:
        r = httpx.post(
            f"https://{domain}/oauth/token",
            timeout=15,
            data={
                "grant_type": "client_credentials",
                "client_id": mcid,
                "client_secret": msecret,
                "audience": f"https://{domain}/api/v2/",
            },
        )
        token = r.json().get("access_token") if r.status_code == 200 else None
    if token is None:
        report(WARN, "Management API", "not available; check the dashboard settings in README by hand")
        return
    headers = {"Authorization": f"Bearer {token}"}
    rs = httpx.get(f"https://{domain}/api/v2/resource-servers", headers=headers, timeout=15)
    if rs.status_code == 200:
        found = s.auth0_audience in {r.get("identifier") for r in rs.json()}
        report(
            OK if found else FAIL,
            "API audience",
            "exists" if found else f"create an API with identifier {s.auth0_audience}",
        )
    else:
        report(WARN, "API audience", f"cannot read (HTTP {rs.status_code}; M2M app needs read:resource_servers)")
    if cid:
        app = httpx.get(
            f"https://{domain}/api/v2/clients/{cid}",
            headers=headers,
            timeout=15,
            params={"fields": "callbacks,allowed_logout_urls,grant_types"},
        )
        if app.status_code == 200:
            data: dict[str, Any] = app.json()
            callback = f"{s.app_base_url}/auth/callback"
            ok_cb = callback in (data.get("callbacks") or [])
            report(OK if ok_cb else FAIL, "Allowed Callback URLs", "ok" if ok_cb else f"add {callback}")
            ok_lo = s.app_base_url in (data.get("allowed_logout_urls") or [])
            report(OK if ok_lo else FAIL, "Allowed Logout URLs", "ok" if ok_lo else f"add {s.app_base_url}")
        else:
            report(WARN, "application settings", f"cannot read (HTTP {app.status_code}; M2M app needs read:clients)")


def check_models() -> None:
    print("\nAnswer models and embeddings")
    s = load_settings()
    client = LLMClient(s)
    for name, provider in client.providers.items():
        missing = provider.missing()
        report(
            OK if missing is None else FAIL, f"provider {name}", "configured" if missing is None else f"set {missing}"
        )
    gemini = client.gemini()
    if gemini is not None and gemini.configured:
        try:
            available = set(gemini.list_models())
            for p, model in s.llm_chain:
                if p == "gemini":
                    listed = model in available
                    report(OK if listed else WARN, f"model {model}", "listed" if listed else "not listed for this key")
        except LLMError as exc:
            report(WARN, "Gemini model list", str(exc))
    if client.configured:
        try:
            out = client.generate_json(
                system="Reply with JSON only.",
                user='Return {"ok": true}.',
                schema={"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}, "required": ["ok"]},
            )
            report(OK if out.data.get("ok") is True else FAIL, "generation", f"answered by {out.model}")
        except LLMError as exc:
            report(FAIL, "generation", str(exc))
    else:
        report(FAIL, "generation", f"no usable answer model: set {', '.join(client.missing())}")
    try:
        vec = Embedder(s).embed_query("Either party may terminate this Agreement on thirty (30) days notice.")
        report(OK if len(vec) == EMBEDDING_DIM else FAIL, f"embeddings {s.embedding_model}", f"{len(vec)} dimensions")
    except EmbeddingError as exc:
        report(FAIL, "embeddings", str(exc))


def main() -> int:
    env = merged_env()
    check_settings(env)
    check_database()
    check_auth0(env)
    check_models()
    print(f"\n{'All checks passed.' if failures == 0 else f'{failures} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
