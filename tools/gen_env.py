"""Create ``.env`` with strong random LOCAL secrets (doc 12.10, Appendix C).

Everything this project can generate itself (database passwords, the code pepper, the resume key,
service secrets, local Qdrant keys, object-store keys) is generated here with the operating
system's CSPRNG. Everything that belongs to a third party (Auth0, AWS, Cloudflare, the LLM
provider, SMTP) stays a placeholder for you to fill in. Valkey ACL users are optional locally and
are left as placeholders (the services treat a placeholder as "not configured").

    uv run python tools/gen_env.py                  # fill .env from .env.example
    uv run python tools/gen_env.py --hosts compose  # container host names in the DSNs
    uv run python tools/gen_env.py --out /tmp/x.env # write somewhere else (nothing in the repo changes)
"""

from __future__ import annotations

import json
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANDOM_HEX = "<RANDOM_64_HEX_CHARS>"
# One value per distinct placeholder name, shared wherever that name repeats (e.g. a service's DSN
# and its worker DSN must carry the same password).
NAMED = {
    r"<[A-Z]+_DB_PASSWORD>": lambda: secrets.token_urlsafe(24),
    r"<OWNER_PASSWORD>": lambda: secrets.token_urlsafe(24),
    r"<POSTGRES_ADMIN_PASSWORD>": lambda: secrets.token_urlsafe(24),
    r"<PGBOUNCER_AUTH_PASSWORD>": lambda: secrets.token_urlsafe(24),
    r"<QDRANT_READ_ONLY_KEY>": lambda: secrets.token_urlsafe(32),
    r"<QDRANT_READ_WRITE_KEY>": lambda: secrets.token_urlsafe(32),
    r"<OBJECT_STORE_ACCESS_KEY>": lambda: secrets.token_hex(10).upper(),
    r"<OBJECT_STORE_SECRET_KEY>": lambda: secrets.token_urlsafe(30),
    r"<OPENBAO_DEV_TOKEN>": lambda: secrets.token_urlsafe(24),
}


def render(text: str, host: str = "localhost") -> tuple[str, dict[str, str]]:
    """Fill the generatable placeholders. Returns the new text and the named values used."""
    named: dict[str, str] = {}
    for pattern, make in NAMED.items():
        for token in sorted(set(re.findall(pattern, text))):
            named[token] = make()
    for token, value in named.items():
        text = text.replace(token, value)
    text = re.sub(
        re.escape(RANDOM_HEX), lambda _m: secrets.token_hex(32), text
    )  # distinct each time
    if host != "localhost":
        text = re.sub(r"@localhost:(6432|5432)/", rf"@{host}:\1/", text)
        text = text.replace("redis://localhost:6379", "redis://valkey:6379")
        text = text.replace(
            "http://localhost:8200", "http://openbao:8200"
        )  # the local-keys compose profile
    return text, named


def _value(text: str, name: str) -> str:
    match = re.search(rf"^{name}=(\S+)", text, re.MULTILINE)
    return match.group(1) if match else ""


def main(argv: list[str]) -> int:
    host = "pgbouncer" if "--hosts" in argv and "compose" in argv else "localhost"
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else ROOT / ".env"
    if out.exists() and "--force" not in argv:
        print(f"{out} exists; refusing to overwrite (use --force).")
        return 1
    text, named = render((ROOT / ".env.example").read_text(encoding="utf-8"), host)
    out.write_text(text, encoding="utf-8")
    out.chmod(0o600)
    if out == ROOT / ".env":  # the object store container reads its identities from a rendered file
        creds = {
            "name": "ingestion",
            "actions": ["Admin", "Read", "Write", "List", "Tagging"],
            "credentials": [
                {
                    "accessKey": _value(text, "OBJECT_STORE_CREDS_INGESTION_ACCESS_KEY"),
                    "secretKey": _value(text, "OBJECT_STORE_CREDS_INGESTION_SECRET_KEY"),
                }
            ],
        }
        s3 = ROOT / "infra" / "compose" / "seaweedfs" / "s3.json"
        s3.write_text(json.dumps({"identities": [creds]}, indent=2) + "\n", encoding="utf-8")
        s3.chmod(0o600)
    left = sorted(set(re.findall(r"<[A-Z0-9_]+>", text)))
    print(f"wrote {out}: {len(named)} named secrets and every per-service random secret generated")
    print(
        "still placeholders (third-party values and optional Valkey ACL users, yours to fill in):"
    )
    print("  " + ", ".join(left))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
