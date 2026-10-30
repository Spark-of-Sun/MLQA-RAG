"""Citation validator entrypoint: ``uvicorn citation_validator.main:app``.

Needs: PG_DSN_VALIDATOR (read-only ledger and chunks), VALKEY_URL, a KMS and the trust root
(it signs verdicts with a certified key), and the pinned NLI model: NLI_MODEL and NLI_MODEL_HASH
(the weights SHA-256; a mismatch refuses to start). Install the model runtime with
``uv sync --extra nli``.

NLI_THRESHOLD is a CALIBRATION RESULT (gate G7.3: precision of "supported" >= 0.99 on human-labelled
pairs). Until that is done the default below is an uncalibrated placeholder and the service says so.
"""

from __future__ import annotations

import logging
import os
from typing import Final

from citation_validator.app import create_app
from citation_validator.nli import DEFAULT_MODEL, TransformersNliScorer
from citation_validator.service import ValidatorService
from citation_validator.store import ValidatorStore
from lmqa_auth import ContextSigner
from lmqa_auth.runtime import (
    context_verifier,
    database,
    env,
    key_provider,
    optional_env,
    trust_root,
    valkey_client,
)
from lmqa_keys import KeyService

LOG: Final = logging.getLogger("citation_validator")
UNCALIBRATED_THRESHOLD: Final = "0.9"


def build() -> ValidatorService:
    """Construct the validator. Settings are validated first; the model loads last."""
    store = ValidatorStore(database("VALIDATOR"), KeyService(key_provider()))
    signer = ContextSigner(trust_root(), env("HOSTNAME", "validator"))
    if "NLI_THRESHOLD" not in os.environ:
        LOG.warning(
            "NLI_THRESHOLD is not set: using the UNCALIBRATED placeholder %s (gate G7.3 not met)",
            UNCALIBRATED_THRESHOLD,
        )
    threshold = float(env("NLI_THRESHOLD", UNCALIBRATED_THRESHOLD))
    scorer = TransformersNliScorer(env("NLI_MODEL", DEFAULT_MODEL), optional_env("NLI_MODEL_HASH"))
    return ValidatorService(store, signer, scorer, threshold)


app = create_app(build(), context_verifier("citation_validator", valkey_client("VALIDATOR")))
