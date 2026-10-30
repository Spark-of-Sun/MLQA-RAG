"""Wrap over-long plain string literals into adjacent literals (agent tooling, not part of the project).

Safe by construction: only single-line, non-f, non-triple-quoted strings that sit inside brackets
(so implicit concatenation is legal) are split, at a space. After rewriting, the module's AST must
be identical to the original; Python folds adjacent literals into one constant, so any behaviour
change would show up. A file whose AST differs is left untouched.
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

LIMIT = 100


def _one_pass(source: str) -> str:
    lines = source.split("\n")
    depth = 0
    edits: list[tuple[int, int, int, str, str]] = []  # line, start col, end col, prefix, body+quote
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.OP:
            if tok.string in "([{":
                depth += 1
            elif tok.string in ")]}":
                depth -= 1
        if tok.type != tokenize.STRING or depth <= 0 or tok.start[0] != tok.end[0]:
            continue
        text = tok.string
        prefix = text[: len(text) - len(text.lstrip("rRbBuU"))]
        rest = text[len(prefix) :]
        if "f" in prefix.lower() or rest.startswith(('"""', "'''")) or len(rest) < 2 or rest[0] not in "\"'":
            continue
        line = lines[tok.start[0] - 1]
        if len(line) <= LIMIT:
            continue
        quote = rest[0]
        body = rest[1:-1]
        budget = LIMIT - tok.start[1] - len(prefix) - 2
        cut = body.rfind(" ", 0, budget)
        if cut < 12 or "\\" in body[max(0, cut - 1) : cut + 2]:
            continue
        edits.append((tok.start[0], tok.start[1], tok.end[1], prefix + quote, body[: cut + 1] + quote + "\x00" + prefix + quote + body[cut + 1 :] + quote))
    for lineno, start, end, head, payload in reversed(edits):
        first, second = payload.split("\x00")
        line = lines[lineno - 1]
        indent = line[: start]
        indent = " " * (len(indent) - len(indent.lstrip()))
        lines[lineno - 1 : lineno] = [line[:start] + head + first, indent + second + line[end:]]
        # `head + first` already starts with the quote opener; rebuild precisely:
        lines[lineno - 1] = line[:start] + head + first
    return "\n".join(lines)


def wrap_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    current = original
    for _ in range(6):
        updated = _one_pass(current)
        if updated == current:
            break
        current = updated
    if current == original:
        return False
    if ast.dump(ast.parse(original)) != ast.dump(ast.parse(current)):
        print(f"SKIPPED (AST changed): {path}")  # noqa: T201
        return False
    path.write_text(current, encoding="utf-8")
    return True


if __name__ == "__main__":
    changed = [str(p) for p in map(Path, sys.argv[1:]) if wrap_file(p)]
    print("rewrote:", ", ".join(changed) or "nothing")  # noqa: T201
