"""Citation validator (blueprint 11.6). Deterministic; imports no LLM client, vector store or object store."""

from citation_validator.validator import (
    Verdict,
    apply_entailment,
    build_result,
    entailment_claims,
    recheck_integrity,
    validate,
)

__all__ = ["Verdict", "apply_entailment", "build_result", "entailment_claims", "recheck_integrity", "validate"]
