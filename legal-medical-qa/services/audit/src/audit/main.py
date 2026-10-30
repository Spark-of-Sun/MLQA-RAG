"""Audit service entrypoint: ``uvicorn audit.main:app``.

Needs: PG_DSN_AUDIT (the audit reader role), VALKEY_URL, a KMS and the trust root. This is the only
service allowed to unwrap audit private keys.
"""

from __future__ import annotations

from audit.app import create_app
from lmqa_auth.runtime import context_verifier, database, key_provider, valkey_client

_valkey = valkey_client("AUDIT")
app = create_app(database("AUDIT"), key_provider(), context_verifier("audit", _valkey))
