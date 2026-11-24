"""Run docker or pnpm with the merged settings exported: `python tools/withenv.py -- docker compose up -d`.

Only an allow-listed program may be started, so this wrapper cannot be used to print secrets
(for example `env` or `printenv`).
"""

from __future__ import annotations

import os
import sys

from lmqa_models.envfile import apply_to_process

ALLOWED = {"docker", "pnpm"}


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args or os.path.basename(args[0]) not in ALLOWED:
        print(
            f"usage: python tools/withenv.py -- <{'|'.join(sorted(ALLOWED))}> [args...]",
            file=sys.stderr,
        )
        return 2
    apply_to_process()
    os.execvp(args[0], args)  # noqa: S606 - replaces this process with an allow-listed command


if __name__ == "__main__":
    sys.exit(main())
