"""Export each internal service's OpenAPI document to contracts/openapi/ (doc 15.1, 18).

    uv run python tools/export_openapi.py

The apps are built with no collaborators: OpenAPI generation only reads the route table, so no database,
key provider or model is touched. The drift test (tests/contract/test_openapi_matrix.py) cross-checks
these documents against contracts/authz-matrix.yaml.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "contracts" / "openapi"


def apps() -> dict[str, Any]:
    """Every internal service app, built without collaborators (routes only)."""
    from audit.app import create_app as audit  # noqa: PLC0415
    from citation_validator.app import create_app as validator  # noqa: PLC0415
    from generation.app import create_app as generation  # noqa: PLC0415
    from identity.app import create_app as identity  # noqa: PLC0415
    from ingestion.app import create_app as ingestion  # noqa: PLC0415
    from retrieval.app import create_app as retrieval  # noqa: PLC0415

    return {
        "identity": identity(None, None),  # type: ignore[arg-type]
        "ingestion": ingestion(None, None),  # type: ignore[arg-type]
        "retrieval": retrieval(None, None),  # type: ignore[arg-type]
        "generation": generation(None, None),  # type: ignore[arg-type]
        "citation-validator": validator(None, None),  # type: ignore[arg-type]
        "audit": audit(None, None, None),  # type: ignore[arg-type]
    }


def export() -> dict[str, dict[str, Any]]:
    """Write the documents and return them."""
    OUT.mkdir(parents=True, exist_ok=True)
    docs: dict[str, dict[str, Any]] = {}
    for name, app in apps().items():
        app.docs_url = app.redoc_url = None
        doc = app.openapi()
        docs[name] = doc
        (OUT / f"{name}.json").write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return docs


if __name__ == "__main__":
    written = export()
    print(f"wrote {len(written)} OpenAPI documents to {OUT}")
