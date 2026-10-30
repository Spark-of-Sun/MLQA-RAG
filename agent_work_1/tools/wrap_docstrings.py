"""Split over-long single-line docstrings into a summary line plus a body (agent tooling).

``\"\"\"Summary. Detail.\"\"\"`` becomes a two-part docstring split at the last sentence boundary (else
clause boundary) that fits the line limit. Verified: after stripping docstrings the AST must equal
the original, so only documentation text can have changed. A file that fails stays untouched.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

LIMIT = 100
_LINE = re.compile(r'^(\s*)"""(.+)"""\s*$')


def _split(text: str, room: int) -> tuple[str, str] | None:
    for pattern in (r"\. ", r"; ", r": ", r", "):
        cut = -1
        for m in re.finditer(pattern, text):
            if m.start() + 1 <= room:
                cut = m.start()
        if cut >= 20:  # noqa: PLR2004
            head, tail = text[: cut + (1 if pattern == r"\. " else 0)], text[cut + len(pattern.replace("\\", "")) :]
            head = head if head.endswith((".", "?", "!")) else head + "."
            tail = tail[0].upper() + tail[1:] if tail else tail
            return head, tail
    return None


def _strip_docstrings(tree: ast.AST) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body[0].value.value = ""
    return ast.dump(tree)


def process(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    out: list[str] = []
    for line in original.split("\n"):
        m = _LINE.match(line)
        if m and len(line) > LIMIT:
            indent, text = m.groups()
            parts = _split(text, LIMIT - len(indent) - 3)
            if parts:
                head, tail = parts
                if not tail.rstrip().endswith((".", "?", "!")):
                    tail = tail.rstrip() + "."
                out += [f'{indent}"""{head}', "", f"{indent}{tail}", f'{indent}"""']
                continue
        out.append(line)
    updated = "\n".join(out)
    if updated == original:
        return False
    if _strip_docstrings(ast.parse(original)) != _strip_docstrings(ast.parse(updated)):
        print(f"SKIPPED (code changed): {path}")  # noqa: T201
        return False
    path.write_text(updated, encoding="utf-8")
    return True


if __name__ == "__main__":
    changed = [str(p) for p in map(Path, sys.argv[1:]) if process(p)]
    print("rewrote:", ", ".join(changed) or "nothing")  # noqa: T201
