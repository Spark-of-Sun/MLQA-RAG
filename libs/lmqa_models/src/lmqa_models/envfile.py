"""Load settings for every service and tool.

Layers, lowest to highest precedence:
  .secrets.generated   local-only secrets made by `make setup` (database passwords, code pepper, session secret)
  .env                 your values (Auth0, Gemini); `make doctor` names any setting that is missing
  .secrets             your values, if you prefer this name (same format)
  process environment
A value that is empty or still a template placeholder such as `<AUTH0_BFF_CLIENT_ID>` counts as unset, so a
half-filled file never leaks placeholder text into a running service. Values are never printed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def _find_root() -> Path:
    if env_root := os.environ.get("LMQA_ROOT"):
        return Path(env_root).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "contracts").is_dir() and (parent / "Makefile").is_file():
            return parent
    return Path.cwd()


ROOT = _find_root()
GENERATED = ROOT / ".secrets.generated"
USER_FILES = (ROOT / ".env", ROOT / ".secrets")
_PLACEHOLDER = re.compile(r"^<[^<>]*>$")


def is_placeholder(value: str | None) -> bool:
    return value is None or value.strip() == "" or bool(_PLACEHOLDER.match(value.strip()))


def parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; supports quotes, `export`, and trailing ` # comments` on unquoted values."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if value[:1] in {'"', "'"} and value[:1] in value[1:]:
            value = value[1 : value.index(value[0], 1)]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        out[key] = value
    return out


def merged_env() -> dict[str, str]:
    merged: dict[str, str] = {}
    layers = [parse_env_file(GENERATED), *(parse_env_file(p) for p in USER_FILES), dict(os.environ)]
    for layer in layers:
        for key, value in layer.items():
            if not is_placeholder(value):
                merged[key] = value
    return merged


def apply_to_process() -> None:
    """Export the merged settings into os.environ (for child processes such as the frontend)."""
    for key, value in merged_env().items():
        os.environ[key] = value
