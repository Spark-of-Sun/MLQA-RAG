"""Wrap over-long standalone string-literal lines into adjacent literals (agent tooling)."""
import pathlib
import re
import sys

LIMIT = 100
pattern = re.compile(r'^(\s*)(f?)"(.*)"(,?\)*)$')
for name in sys.argv[1:]:
    path = pathlib.Path(name)
    out = []
    for line in path.read_text().split("\n"):
        m = None if line.lstrip().startswith(('"""', 'f"""')) else pattern.match(line)
        if len(line) > LIMIT and m:
            indent, prefix, body, tail = m.groups()
            budget = LIMIT - len(indent) - len(prefix) - 4
            cut = body.rfind(" ", 0, budget)
            if cut > 20:
                out.append(f'{indent}{prefix}"{body[: cut + 1]}"')
                out.append(f'{indent}{prefix}"{body[cut + 1 :]}"{tail}')
                continue
        out.append(line)
    path.write_text("\n".join(out))
