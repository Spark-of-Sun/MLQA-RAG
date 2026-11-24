"""Load settings for every service and tool.

Layers, lowest to highest precedence:
  .env                 the only settings file: your values (Auth0, Gemini) and the local-only secrets that
                       `make setup` adds when missing (database passwords, code pepper, session secret).
                       LMQA_ENV_FILE names another file in the repo root instead, for example `.env.deployed`
                       on the onekami.site server (docs/deploy.md); `make setup` then writes its secrets there.
  process environment  the shell; overrides .env
A value that is empty or still a template placeholder such as `<AUTH0_BFF_CLIENT_ID>` counts as unset, so a
half-filled file never leaks placeholder text into a running service. Values are never printed.
"""

from __future__ import annotations

import os
import re
import tempfile
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
ENV_FILE = ROOT / (os.environ.get("LMQA_ENV_FILE") or ".env").strip()
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
            value = re.split(r"(?:^|\s+)#", value, maxsplit=1)[0].strip()  # `KEY=  # note` is empty
        out[key] = value
    return out


def merged_env() -> dict[str, str]:
    merged: dict[str, str] = {}
    for layer in (parse_env_file(ENV_FILE), dict(os.environ)):
        for key, value in layer.items():
            if not is_placeholder(value):
                merged[key] = value
    return merged


def _format_value(value: str) -> str:
    if re.fullmatch(r"[^\s#'\"]*", value):
        return value
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    raise ValueError("a value with both quote characters cannot be written to an env file")


def fill_missing(path: Path, values: dict[str, str]) -> list[str]:
    """Write each value whose key is missing or a placeholder in `path`; never overwrite a set value.

    A placeholder line (`KEY=<generated>  # note`) is filled in place and keeps its comment; other keys are
    appended. The file is replaced atomically and stays mode 600. Returns the key names written, never values.
    """
    current = parse_env_file(path)
    todo = {k: v for k, v in values.items() if is_placeholder(current.get(k))}
    if not todo:
        return []
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    placed: set[str] = set()
    for i, raw in enumerate(lines):
        m = re.match(r"^(\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=)(.*)$", raw)
        if not m or m.group(2) not in todo:
            continue
        rest = m.group(3)
        tail = None if rest.strip()[:1] in {'"', "'"} else re.search(r"\s+#.*$", rest)
        lines[i] = m.group(1) + _format_value(todo[m.group(2)]) + (tail.group(0) if tail else "")
        placed.add(m.group(2))
    appended = [k for k in todo if k not in placed]
    if appended:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(
            "# Added by `make setup` (tools/gen_env.py): local-only secrets. Never commit."
        )
        lines.extend(f"{k}={_format_value(todo[k])}" for k in appended)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)
    return list(todo)


def apply_to_process() -> None:
    """Export the merged settings into os.environ (for child processes such as the frontend)."""
    for key, value in merged_env().items():
        os.environ[key] = value
