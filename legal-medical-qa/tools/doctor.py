"""Check every real dependency before any test runs and print what is missing (doc 4.6, G0.9).

    uv run python tools/doctor.py

It never prints a secret value. A check that needs something you have not configured is reported as
MISSING (with the variable to set) rather than failing, so you can see the whole list in one run.
Exit status is 1 if anything required is missing or unreachable.
"""

from __future__ import annotations

import os
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_TO_RUN = (
    "PG_DSN_GATEWAY",
    "PG_DSN_IDENTITY",
    "PG_DSN_INGESTION",
    "PG_DSN_RETRIEVAL",
    "PG_DSN_GENERATION",
    "PG_DSN_VALIDATOR",
    "PG_DSN_AUDIT",
    "PG_MIGRATION_DSN",
    "VALKEY_URL",
    "QDRANT_URL",
    "QDRANT_KEY_RO",
    "QDRANT_KEY_RW",
    "CODE_PEPPER_V1",
    "GATEWAY_RESUME_KEY",
    "AUTH0_DOMAIN",
    "AUTH0_CLIENT_ID_BFF",
    "AUTH0_AUDIENCE_MAIN",
    "AUTH0_AUDIENCE_ONBOARDING",
    "AUTH0_CLAIMS_NAMESPACE",
)
THIRD_PARTY = (
    ("Auth0 BFF client secret", "AUTH0_CLIENT_SECRET_BFF"),
    ("Auth0 M2M client secret", "AUTH0_M2M_CLIENT_SECRET"),
    ("LLM key (Anthropic)", "ANTHROPIC_API_KEY"),
    ("LLM key (OpenAI)", "OPENAI_API_KEY"),
    ("AWS credentials", "AWS_ACCESS_KEY_ID"),
    ("Cloudflare token", "CLOUDFLARE_API_TOKEN"),
    ("SMTP password", "SMTP_PASSWORD"),
)


def load_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if "=" in text:
            key, _, value = text.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def configured(name: str) -> bool:
    value = os.environ.get(name, "")
    return bool(value) and not re.fullmatch(r"<[^>]+>", value) and "<" not in value.split("@")[0]


def reachable(url: str, default_port: int) -> bool:
    parts = urlsplit(url if "//" in url else f"//{url}")
    try:
        with socket.create_connection(
            (parts.hostname or "localhost", parts.port or default_port), timeout=2
        ):
            return True
    except OSError:
        return False


def main() -> int:
    load_env()
    problems = 0
    print("Required to run the platform:")
    for name in REQUIRED_TO_RUN:
        ok = configured(name)
        problems += not ok
        print(f"  {'ok     ' if ok else 'MISSING'} {name}")
    print(
        "Third-party credentials (yours to provide; none are needed to run the model-free tests):"
    )
    for label, name in THIRD_PARTY:
        print(f"  {'ok     ' if configured(name) else 'MISSING'} {label} ({name})")
    print("Services reachable from this machine:")
    for label, name, port in (
        ("PostgreSQL", "PG_MIGRATION_DSN", 5432),
        ("Valkey", "VALKEY_URL", 6379),
        ("Qdrant", "QDRANT_URL", 6333),
    ):
        if configured(name):
            up = reachable(os.environ[name], port)
            problems += not up
            print(f"  {'up     ' if up else 'DOWN   '} {label}")
    print("Knobs that are calibration results, not guesses:")
    for name, gate in (("NLI_THRESHOLD", "G7.3"), ("RERANK_THRESHOLD", "G5.11")):
        print(
            f"  {'set    ' if configured(name) else 'UNSET  '} {name}  (gate {gate}); unset runs an UNCALIBRATED placeholder"
        )
    print(
        "\nAll required items present."
        if not problems
        else f"\n{problems} required item(s) missing or unreachable."
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
