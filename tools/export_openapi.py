"""Export the gateway's OpenAPI document to contracts/openapi/gateway.json (blueprint 15, 18, G0.10).

The document is generated from the running code, so it cannot drift from the routes; the contract test compares the
committed copy with a fresh export and validates it with openapi-spec-validator. `--check` exits 1 on drift. The
frontend's typed client (`frontend/src/lib/api-schema.d.ts`) is generated from this file by `make contracts`.
"""

from __future__ import annotations

import argparse
import json
import sys

from gateway.app import create_app
from lmqa_models.envfile import ROOT

OUT = ROOT / "contracts" / "openapi" / "gateway.json"


def export() -> str:
    spec = create_app(resume_jobs=False).openapi()
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    body = export()
    if args.check:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == body
        print("openapi: up to date" if same else "openapi: OUT OF DATE (run make contracts)")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
