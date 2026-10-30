"""Scaffold uv workspace member packages (agent tooling, not part of the project)."""

import textwrap
from pathlib import Path

ROOT = Path("/home/user/workspace/legal-medical-qa")

LIBS: dict[str, tuple[list[str], list[str]]] = {
    "lmqa_models": (["pydantic>=2.14", "pyyaml>=6", "tokenizers>=0.22"], []),
    "lmqa_security": (["cryptography>=50", "pyhpke>=0.6"], []),
    "lmqa_keys": (["boto3>=1.43", "cryptography>=50", "httpx>=0.28"], ["lmqa_models"]),
    "lmqa_db": (["sqlalchemy[asyncio]>=2.1", "psycopg[binary]>=3.3"], ["lmqa_models"]),
    "lmqa_auth": (
        ["pyjwt[crypto]>=2.15", "cryptography>=50", "httpx>=0.28", "valkey>=6.2", "fastapi>=0.162"],
        ["lmqa_models", "lmqa_db", "lmqa_keys"],
    ),
    "lmqa_vectorstore": (["qdrant-client>=1.20"], ["lmqa_models"]),
    "lmqa_objectstore": (["boto3>=1.43"], ["lmqa_keys"]),
    "lmqa_audit": ([], ["lmqa_db", "lmqa_security", "lmqa_keys"]),
    "lmqa_logging": (["structlog>=26"], []),
    "lmqa_telemetry": (["opentelemetry-api>=1.45"], []),
    "lmqa_testing": (
        [
            "pytest>=9.2",
            "pytest-asyncio>=1.4",
            "httpx>=0.28",
            "alembic>=1.20",
            "psycopg[binary]>=3.3",
        ],
        ["lmqa_models", "lmqa_db"],
    ),
}
EXTRAS: dict[str, dict[str, list[str]]] = {
    "citation_validator": {
        "nli": ["torch>=2.15", "transformers>=5.22"],
    },
}
SVC_BASE = ["fastapi>=0.162", "uvicorn>=0.54", "httpx>=0.28", "pydantic-settings>=2.16", "websockets>=15"]
SERVICES: dict[str, list[str]] = {
    "gateway": ["sse-starlette>=3.6", "valkey>=6.2", "pyyaml>=6"],
    "identity": ["valkey>=6.2"],
    "ingestion": [
        "pypdf>=6.2", "pypdfium2>=5", "python-docx>=1.2", "lxml>=6", "fastembed>=0.7", "tokenizers>=0.22",
    ],
    "retrieval": ["valkey>=6.2", "fastembed>=0.7"],
    "generation": ["valkey>=6.2", "anthropic>=2.3", "openai>=3", "tokenizers>=0.22"],
    "citation_validator": [],
    "audit": [],
    "ops": [],
}
SVC_LIBS = [
    "lmqa_models",
    "lmqa_auth",
    "lmqa_db",
    "lmqa_keys",
    "lmqa_security",
    "lmqa_audit",
    "lmqa_logging",
]
# Libraries a service must never hold (doc 4.2 / 4.7): the gateway never decrypts.
SVC_FORBID: dict[str, set[str]] = {}  # the gateway keeps lmqa_keys for signing only (see import contract)
SVC_EXTRA_LIBS = {
    "ingestion": ["lmqa_vectorstore", "lmqa_objectstore"],
    "retrieval": ["lmqa_vectorstore"],
}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _extras_block(extras: dict[str, list[str]] | None) -> list[str]:
    if not extras:
        return []
    out = ["[project.optional-dependencies]"]
    for name, pkgs in extras.items():
        out.append(f"{name} = [" + ", ".join(f'"{p}"' for p in pkgs) + "]")
    return [*out, ""]


def pyproject(name: str, deps: list[str], wlibs: list[str], extras: dict[str, list[str]] | None = None) -> str:
    dep_lines = ",\n".join(f'  "{d}"' for d in [*deps, *wlibs])
    lines = [
        "[project]",
        f'name = "{name.replace("_", "-")}"',
        'version = "0.1.0"',
        'requires-python = ">=3.14"',
        "dependencies = [",
        dep_lines,
        "]",
        "",
        *_extras_block(extras),
        "[build-system]",
        'requires = ["hatchling"]',
        'build-backend = "hatchling.build"',
        "",
        "[tool.hatch.build.targets.wheel]",
        f'packages = ["src/{name}"]',
        "",
    ]
    if wlibs:
        lines += ["[tool.uv.sources]", *(f"{w} = {{ workspace = true }}" for w in wlibs), ""]
    return "\n".join(lines)


def main() -> None:
    for name, (deps, wl) in LIBS.items():
        base = ROOT / "libs" / name
        write(base / "pyproject.toml", pyproject(name, deps, wl))
        init = base / "src" / name / "__init__.py"
        if not init.exists():
            write(init, f'"""{name} package."""\n')
        write(base / "src" / name / "py.typed", "")
        write(base / "tests" / "__init__.py", "")
    for name, extra in SERVICES.items():
        base = ROOT / "services" / name
        libs = [x for x in SVC_LIBS if x not in SVC_FORBID.get(name, set())]
        libs += SVC_EXTRA_LIBS.get(name, [])
        write(base / "pyproject.toml", pyproject(name, SVC_BASE + extra, libs, EXTRAS.get(name)))
        init = base / "src" / name / "__init__.py"
        if not init.exists():
            write(init, f'"""{name} service."""\n')
        write(base / "src" / name / "py.typed", "")
        write(base / "tests" / "__init__.py", "")
    print("scaffolded", len(LIBS), "libs and", len(SERVICES), "services")  # noqa: T201


if __name__ == "__main__":
    main()
