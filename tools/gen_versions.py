"""Write docs/versions.md from the lockfiles (doc 4.5, G0.1): the lockfile is the authority, this is its report.

uv run python tools/gen_versions.py
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_PY = (
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "valkey",
    "qdrant-client",
    "pyjwt",
    "cryptography",
    "pyhpke",
    "boto3",
    "httpx",
    "uvicorn",
    "fastembed",
    "tokenizers",
    "onnxruntime",
    "pypdfium2",
    "lxml",
    "python-docx",
    "anthropic",
    "openai",
    "pytest",
    "hypothesis",
    "ruff",
    "pyright",
    "import-linter",
    "websockets",
)
KEY_JS = (
    "next",
    "react",
    "react-dom",
    "@auth0/nextjs-auth0",
    "ioredis",
    "eventsource-parser",
    "tailwindcss",
    "typescript",
    "eslint",
    "vitest",
)


def run(cmd: list[str]) -> str:
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603
    out = (done.stdout or done.stderr).strip()
    return out.splitlines()[0] if out else "unknown"


def main() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    py = {p["name"]: p["version"] for p in lock["package"]}
    js_lock = (ROOT / "frontend" / "pnpm-lock.yaml").read_text(encoding="utf-8")
    js = {}
    for name in KEY_JS:
        m = re.search(
            rf"^\s+'?{re.escape(name)}'?:\s*\n\s+specifier: [^\n]+\n\s+version: ([^\n(]+)",
            js_lock,
            re.MULTILINE,
        )
        js[name] = m.group(1).strip() if m else "see pnpm-lock.yaml"
    lines = [
        "# Version ledger",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d')} by `tools/gen_versions.py` from `uv.lock` and `frontend/pnpm-lock.yaml`.",
        "The lockfiles and the container image digests are the authority; this file is their report.",
        "",
        "## Runtime and tools",
        "",
        "| Tool | Version |",
        "| --- | --- |",
        f"| Python | {run(['python3', '--version']).split()[-1]} (pinned 3.14 in `.python-version`) |",
        f"| uv | {run(['uv', '--version'])} |",
        f"| Node.js (frontend build) | {run(['node', '--version'])} (Docker image uses 24 LTS) |",
        f"| pnpm | {run(['pnpm', '--version'])} |",
        "| OpenTofu | 1.13.2 (used to validate infra/) |",
        "",
        "## Python packages (selected)",
        "",
        "| Package | Locked version |",
        "| --- | --- |",
        *[f"| {n} | {py.get(n, 'not locked')} |" for n in KEY_PY],
        "",
        "## Frontend packages (selected)",
        "",
        "| Package | Locked version |",
        "| --- | --- |",
        *[f"| {n} | {v} |" for n, v in js.items()],
        "",
        "## Infrastructure servers used by the tests (real, not mocked)",
        "",
        "| Server | Version |",
        "| --- | --- |",
        "| PostgreSQL | 18.6 |",
        "| PgBouncer | 1.26.1 (built from source) |",
        "| Valkey | 9.1.3 (built from source) |",
        "| Qdrant | 1.20.0 |",
        "| OpenBao | 2.7.2 |",
        "| SeaweedFS | 4.51 |",
        "",
        "## OpenTofu providers",
        "",
        "| Provider | Version constraint |",
        "| --- | --- |",
        "| hashicorp/aws | ~> 6.71 |",
        "| cloudflare/cloudflare | ~> 5.28 |",
        "| auth0/auth0 | ~> 1.59 |",
        "",
        "## Deliberate deviations from 'newest'",
        "",
        "* **TypeScript is 6.0.x, not 7.x.** `typescript-eslint` 8.72 refuses TypeScript 7 (peer range `<6.1.0`) and `next build` uses the",
        "  TypeScript JS API. Revisit when `typescript-eslint` supports TypeScript 7.1 or later.",
        "* Qdrant, PostgreSQL, Valkey and the other servers above are the versions the tests ran against here; pin container images by digest before production.",
    ]
    (ROOT / "docs" / "versions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "python_packages": len(py),
                "js_found": sum(v != "see pnpm-lock.yaml" for v in js.values()),
            }
        )
    )


if __name__ == "__main__":
    main()
