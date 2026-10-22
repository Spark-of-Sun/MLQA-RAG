#!/usr/bin/env python3
"""
launcher.py — single entry point for running every legal-medical-qa backend
service directly on the host, bypassing docker-compose, so each service can
be started in its own terminal for local testing.

Why this exists
----------------
Each service (gateway, ingestion, retrieval, generation, citation_validator)
has its OWN virtualenv, isolated from the others. This script resolves the
correct python/arq executable from that service's own venv and runs it with
cwd set to that service's folder (so `app.main:app` resolves to that
service's own app/ package — every service names its package "app", but
since each venv + cwd pair is isolated per service, there's no collision).

Venv location, per service, in priority order:
    1. --venv <path>                   (this invocation only)
    2. <SERVICE>_VENV_DIR env var      (e.g. GATEWAY_VENV_DIR=/path/to/venv)
    3. .venv-<name>/ at the repo root, OR services/<name>/.venv/
       (both conventions are checked, since .gitignore covers both
       ".venv-*/" and ".venv/" — see setup_venvs.sh for which one it creates)

Usage
-----
    python launcher.py gateway
    python launcher.py ingestion
    python launcher.py ingestion-worker
    python launcher.py retrieval
    python launcher.py generation
    python launcher.py citation-validator

    python launcher.py check   # sanity-check Postgres/Redis/Qdrant/MinIO reachability
    python launcher.py list    # print the exact command + venv found for every service

    python launcher.py gateway --venv /custom/path/to/venv

Config is read from --env-file (default: .env.local if present, else .env).
See .env.local.example — docker-compose's service hostnames ("postgres",
"redis", "qdrant", "minio") don't resolve outside the compose network, so
that file points everything at localhost + the ports docker-compose
publishes.

NOTE: this script itself can be run with any interpreter (system python,
whatever) — it never imports or runs service code directly, it only shells
out to each service's OWN venv's python/arq. launcher.py's own
sys.executable is irrelevant to what actually runs your services.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent

# Env vars whose value is a path that service code resolves relative to ITS
# OWN cwd, but which actually lives relative to the REPO ROOT per
# docs/architecture.md's repo layout (prompts/, db/, etc. are top-level
# siblings of services/). Rewritten to an absolute path before each
# subprocess launches, so bare-metal behavior matches the documented
# layout instead of silently falling back to an in-code default.
_REPO_ROOT_RELATIVE_PATH_VARS = ("PROMPT_TEMPLATES_DIR",)


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    dir: str
    kind: str
    app: str | None = None
    worker_settings: str | None = None
    port_env: str | None = None
    default_port: int | None = None
    venv_env: str = ""
    venv_name: str = ""   # the venv's own identity, e.g. for root-layout
                           # ".venv-<venv_name>" — distinct from `name`
                           # only where a CLI name shares another
                           # service's venv (ingestion-worker -> ingestion)

SERVICES: dict[str, ServiceSpec] = {
    "gateway": ServiceSpec(
        name="gateway", dir="services/gateway", kind="http",
        app="app.main:app", port_env="GATEWAY_PORT", default_port=8000,
        venv_env="GATEWAY_VENV_DIR", venv_name="gateway",
    ),
    "ingestion": ServiceSpec(
        name="ingestion", dir="services/ingestion", kind="http",
        app="app.main:app", port_env="INGESTION_PORT", default_port=8001,
        venv_env="INGESTION_VENV_DIR", venv_name="ingestion",
    ),
    "ingestion-worker": ServiceSpec(
        name="ingestion-worker", dir="services/ingestion", kind="worker",
        worker_settings="app.workers.settings.WorkerSettings",
        venv_env="INGESTION_VENV_DIR",
        venv_name="ingestion",  # FIX: shares ingestion's venv/package —
                                 # setup_venvs.sh only ever creates
                                 # ".venv-ingestion", never
                                 # ".venv-ingestion-worker"
    ),
    "retrieval": ServiceSpec(
        name="retrieval", dir="services/retrieval", kind="http",
        app="app.main:app", port_env="RETRIEVAL_PORT", default_port=8002,
        venv_env="RETRIEVAL_VENV_DIR", venv_name="retrieval",
    ),
    "generation": ServiceSpec(
        name="generation", dir="services/generation", kind="http",
        app="app.main:app", port_env="GENERATION_PORT", default_port=8003,
        venv_env="GENERATION_VENV_DIR", venv_name="generation",
    ),
    "citation-validator": ServiceSpec(
        name="citation-validator", dir="services/citation_validator", kind="http",
        app="app.main:app", port_env="CITATION_VALIDATOR_PORT", default_port=8004,
        venv_env="CITATION_VALIDATOR_VENV_DIR", venv_name="citation-validator",
    ),
}


# Per-service Redis key, read by that service's own code (rate_limit.py /
# ingestion's state.py + workers/settings.py / semantic_cache.py). Falls
# back to the shared REDIS_URL, so docker-compose keeps working unchanged.
SERVICE_REDIS_ENV = {
    "gateway": "GATEWAY_REDIS_URL",
    "ingestion": "INGESTION_REDIS_URL",
    "retrieval": "RETRIEVAL_REDIS_URL",                    # reserved, not used by code today
    "generation": "GENERATION_REDIS_URL",
    "citation-validator": "CITATION_VALIDATOR_REDIS_URL",  # reserved, not used by code today
}


# --------------------------------------------------------------------------
# venv resolution
# --------------------------------------------------------------------------
def _candidate_venv_dirs(spec: ServiceSpec) -> list[Path]:
    """Checked in order. Both patterns are covered by .gitignore
    (`.venv-*/` and `.venv/`). The root-layout candidate uses
    spec.venv_name, not spec.name — ingestion-worker shares ingestion's
    venv (setup_venvs.sh never creates a separate one for it), while the
    nested-layout candidate already matches naturally since both share
    the same `dir`.
    """
    return [
        REPO_ROOT / f".venv-{spec.venv_name}",
        REPO_ROOT / spec.dir / ".venv",
    ]


def resolve_venv_dir(spec: ServiceSpec, env: dict[str, str], cli_override: str | None) -> tuple[Path, list[Path]]:
    """Priority: --venv flag > <SERVICE>_VENV_DIR env var > auto-detected
    convention. Returns (resolved_dir, candidates_checked) — the caller
    uses candidates_checked to print a clear error if nothing was found.
    """
    if cli_override:
        return Path(cli_override).expanduser().resolve(), []

    env_override = env.get(spec.venv_env) if spec.venv_env else None
    if env_override:
        return Path(env_override).expanduser().resolve(), []

    candidates = _candidate_venv_dirs(spec)
    for candidate in candidates:
        if candidate.exists():
            return candidate, candidates

    return candidates[0], candidates


def _venv_bin_dir(venv_dir: Path) -> Path:
    windows_bin = venv_dir / "Scripts"
    return windows_bin if windows_bin.exists() else venv_dir / "bin"


def venv_python(venv_dir: Path) -> Path | None:
    bin_dir = _venv_bin_dir(venv_dir)
    for candidate_name in ("python", "python3", "python.exe"):
        candidate = bin_dir / candidate_name
        if candidate.exists():
            return candidate
    return None


def venv_executable(venv_dir: Path, name: str) -> Path | None:
    bin_dir = _venv_bin_dir(venv_dir)
    for candidate in (bin_dir / name, bin_dir / f"{name}.exe"):
        if candidate.exists():
            return candidate
    return None


# --------------------------------------------------------------------------
# .env loading
# --------------------------------------------------------------------------
def _expand(value: str, scope: dict[str, str]) -> str:
    def _sub(match: "re.Match") -> str:
        name, _, default = match.group(1).partition(":-")
        return scope.get(name, os.environ.get(name, default))

    return re.sub(r"\$\{([^}]+)\}", _sub, value)


def _strip_inline_comment(value: str) -> str:
    """Only used by the no-python-dotenv fallback parser. Strips a
    trailing ' # comment' unless the value is quoted."""
    stripped = value.strip()
    if stripped[:1] in ("'", '"'):
        quote = stripped[0]
        end = stripped.find(quote, 1)
        return stripped[1:end] if end != -1 else stripped.strip(quote)
    if " #" in stripped:
        stripped = stripped.split(" #", 1)[0].rstrip()
    return stripped


def _parse_env_file(path: Path) -> dict[str, str]:
    """Fallback parser used only if python-dotenv isn't installed in
    whatever interpreter is running launcher.py itself."""
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = _strip_inline_comment(value)
    for key, value in list(values.items()):
        if "${" in value:
            values[key] = _expand(value, values)
    return values


def load_env(env_file: str | None) -> dict[str, str]:
    """OS environment wins first (so an ad-hoc `export X=` always wins),
    then the .env file fills in anything not already set."""
    candidates = [env_file] if env_file else [".env.local", ".env"]
    chosen: Path | None = None
    for candidate in candidates:
        if candidate and (REPO_ROOT / candidate).exists():
            chosen = REPO_ROOT / candidate
            break

    merged = dict(os.environ)
    if chosen is None:
        print(f"[launcher] no env file found (tried: {', '.join(c for c in candidates if c)}) — using shell env only")
        return merged

    try:
        from dotenv import dotenv_values  # type: ignore

        file_values = {k: v for k, v in dotenv_values(chosen).items() if v is not None}
    except ImportError:
        file_values = _parse_env_file(chosen)

    for key, value in file_values.items():
        merged.setdefault(key, value)

    print(f"[launcher] env file: {chosen.relative_to(REPO_ROOT)}")
    return merged


def _absolutize_known_paths(env: dict[str, str]) -> dict[str, str]:
    """Rewrites paths like PROMPT_TEMPLATES_DIR to be absolute, anchored
    at REPO_ROOT, before any subprocess launches. Service code resolves
    these relative to ITS OWN cwd (services/<name>/), but per
    docs/architecture.md's repo layout they actually live at the repo
    root (prompts/templates/, a sibling of services/). Without this,
    `generation` silently falls back to DEFAULT_TEMPLATE — see
    libs/prompt_registry_client/client.py's swallowed LookupError.
    """
    for key in _REPO_ROOT_RELATIVE_PATH_VARS:
        value = env.get(key)
        if value and not Path(value).is_absolute():
            resolved = (REPO_ROOT / value).resolve()
            env[key] = str(resolved)
            print(f"[launcher] {key} relative path '{value}' -> '{resolved}'")
    return env


# --------------------------------------------------------------------------
# banner
# --------------------------------------------------------------------------
def _mask(value: str | None) -> str:
    if not value:
        return "(not set)"
    return "*" * max(0, len(value) - 4) + value[-4:] if len(value) > 4 else "*" * len(value)


def print_banner(spec: ServiceSpec, env: dict[str, str], venv_dir: Path, host: str, port: int | None) -> None:
    redis_env_name = SERVICE_REDIS_ENV.get(spec.name)
    redis_url = (env.get(redis_env_name) if redis_env_name else None) or env.get("REDIS_URL")
    print("=" * 72)
    print(f"service            : {spec.name}")
    print(f"working directory  : {spec.dir}")
    print(f"venv               : {venv_dir}")
    if spec.kind == "http":
        print(f"command            : <venv python> -m uvicorn {spec.app} --host {host} --port {port}")
    else:
        print(f"command            : <venv>/bin/arq {spec.worker_settings}")
    print(f"ENVIRONMENT        : {env.get('ENVIRONMENT', '(not set)')}")
    print(f"DATABASE_URL       : {env.get('DATABASE_URL', '(not set)')}")
    print(f"redis url used     : {redis_url or '(not set — falls back to in-memory/no-op)'}")
    print(f"INTERNAL_SERVICE_API_KEY : {_mask(env.get('INTERNAL_SERVICE_API_KEY'))}")
    print(f"APP_SECRET_KEY     : {_mask(env.get('APP_SECRET_KEY'))}")
    if spec.name == "generation":
        print(f"LLM_PROVIDER       : {env.get('LLM_PROVIDER', '(not set)')}")
        print(f"PROMPT_TEMPLATES_DIR : {env.get('PROMPT_TEMPLATES_DIR', '(not set)')}")
    print("=" * 72)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def run_service(spec: ServiceSpec, env: dict[str, str], args: argparse.Namespace) -> int:
    service_dir = REPO_ROOT / spec.dir
    if not service_dir.exists():
        print(f"[launcher] ERROR: {service_dir} does not exist", file=sys.stderr)
        return 1

    venv_dir, checked = resolve_venv_dir(spec, env, args.venv)
    if not venv_dir.exists():
        checked_str = "\n".join(f"    - {c}" for c in checked) if checked else f"    - {venv_dir}"
        print(
            f"[launcher] ERROR: no venv found for '{spec.name}'. Checked:\n{checked_str}\n"
            f"  Fix by either:\n"
            f"    --venv <path>\n"
            f"    setting {spec.venv_env}=<path> in your env file\n"
            f"    running setup_venvs.sh to create it",
            file=sys.stderr,
        )
        return 1

    if spec.kind == "http":
        py = venv_python(venv_dir)
        if py is None:
            print(f"[launcher] ERROR: no python executable found under {venv_dir}", file=sys.stderr)
            return 1
        port = args.port or int(env.get(spec.port_env, spec.default_port) or spec.default_port)
        print_banner(spec, env, venv_dir, args.host, port)
        cmd = [str(py), "-m", "uvicorn", spec.app, "--host", args.host, "--port", str(port)]
        if args.reload:
            cmd.append("--reload")
        elif args.workers and args.workers > 1:
            cmd += ["--workers", str(args.workers)]
    else:
        arq_exe = venv_executable(venv_dir, "arq")
        if arq_exe is None:
            print(
                f"[launcher] ERROR: 'arq' executable not found under {venv_dir} — "
                f"is it installed in this service's venv? (pip install arq)",
                file=sys.stderr,
            )
            return 1
        print_banner(spec, env, venv_dir, args.host, None)
        cmd = [str(arq_exe), spec.worker_settings]
        if args.reload:
            cmd += ["--watch", "app"]

    cmd += args.extra_args
    print(f"[launcher] $ {' '.join(cmd)}  (cwd={spec.dir})\n")

    try:
        result = subprocess.run(cmd, cwd=str(service_dir), env=env)
        return result.returncode
    except KeyboardInterrupt:
        return 130


# --------------------------------------------------------------------------
# check — reachability of the infra each service depends on
# --------------------------------------------------------------------------
def _tcp_check(host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "reachable"
    except OSError as exc:
        return False, str(exc)


def _http_check(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500, f"HTTP {resp.status}"
    except Exception as exc:
        return False, str(exc)


def run_check(env: dict[str, str]) -> int:
    print("[launcher] checking local infra reachability\n")
    rows: list[tuple[str, bool, str]] = []

    pg_host = env.get("POSTGRES_HOST", "localhost")
    pg_port = int(env.get("POSTGRES_PORT", "5432"))
    ok, detail = _tcp_check(pg_host, pg_port)
    rows.append((f"Postgres ({pg_host}:{pg_port})", ok, detail))

    seen = {env.get(v) or env.get("REDIS_URL") for v in SERVICE_REDIS_ENV.values()}
    for url in sorted(u for u in seen if u):
        parsed = urlparse(url)
        ok, detail = _tcp_check(parsed.hostname or "localhost", parsed.port or 6379)
        rows.append((f"Redis ({url})", ok, detail))

    q_host = env.get("QDRANT_HOST", "localhost")
    q_port = int(env.get("QDRANT_PORT", "6333"))
    ok, detail = _http_check(f"http://{q_host}:{q_port}/readyz")
    rows.append((f"Qdrant ({q_host}:{q_port})", ok, detail))

    s3_url = env.get("S3_ENDPOINT_URL", "http://localhost:9000")
    ok, detail = _http_check(f"{s3_url}/minio/health/live")
    rows.append((f"MinIO ({s3_url})", ok, detail))

    prompt_dir = env.get("PROMPT_TEMPLATES_DIR")
    if prompt_dir:
        exists = Path(prompt_dir).exists()
        rows.append((f"PROMPT_TEMPLATES_DIR ({prompt_dir})", exists, "exists" if exists else "missing"))

    width = max(len(r[0]) for r in rows)
    all_ok = True
    for label, ok, detail in rows:
        all_ok &= ok
        print(f"[{'OK  ' if ok else 'FAIL'}] {label.ljust(width)}  {detail}")

    if not all_ok:
        print("\n[launcher] start missing infra, e.g.:")
        print("  docker compose up -d postgres redis qdrant minio minio-init")
    return 0 if all_ok else 1


def run_list(env: dict[str, str]) -> int:
    print("[launcher] one terminal per line:\n")
    print("  docker compose up -d postgres redis qdrant minio minio-init   # infra only")
    for name, spec in SERVICES.items():
        venv_dir, _ = resolve_venv_dir(spec, env, None)
        found = "found" if venv_dir.exists() else "NOT FOUND"
        if spec.kind == "http":
            port = int(env.get(spec.port_env, spec.default_port) or spec.default_port)
            print(f"  python launcher.py {name:<18} # http://localhost:{port}  venv={venv_dir} [{found}]")
        else:
            print(f"  python launcher.py {name:<18} # arq worker, no port      venv={venv_dir} [{found}]")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one legal-medical-qa service directly, bypassing docker-compose.")
    parser.add_argument("service", choices=[*SERVICES.keys(), "check", "list"])
    parser.add_argument("--env-file", default=None, help="defaults to .env.local if present, else .env")
    parser.add_argument("--venv", default=None, help="override this service's venv directory for this run")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=None, help="override this service's port")
    parser.add_argument("--workers", type=int, default=None, help="uvicorn --workers (ignored when --reload is on)")
    rg = parser.add_mutually_exclusive_group()
    rg.add_argument("--reload", dest="reload", action="store_true", default=True)
    rg.add_argument("--no-reload", dest="reload", action="store_false")
    parser.add_argument("extra_args", nargs=argparse.REMAINDER, help="passed through after --")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.extra_args[:1] == ["--"]:
        args.extra_args = args.extra_args[1:]

    env = load_env(args.env_file)
    env = _absolutize_known_paths(env)

    if args.service == "check":
        return run_check(env)
    if args.service == "list":
        return run_list(env)

    return run_service(SERVICES[args.service], env, args)


if __name__ == "__main__":
    raise SystemExit(main())