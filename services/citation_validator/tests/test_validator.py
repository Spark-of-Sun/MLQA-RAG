"""Unit and property tests for deterministic citation validation engine.

Master System Design §11.6 & Gate G7.1.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from citation_validator import CANONICAL_REFUSAL, SentenceValidator
from lmqa_models import RetrievalAlias, RetrievalRecord


def _build_test_record(aliases: list[RetrievalAlias]) -> RetrievalRecord:
    return RetrievalRecord(
        request_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_id="auth0|test_user",
        scope_hash="scope-1234-5678",
        query="What is the royalty rate and effective date?",
        aliases=aliases,
    )


@pytest.mark.stage7
@pytest.mark.unit
def test_validator_v1_tag_grammar() -> None:
    """Verify check V1 enforces strict tag grammar [chunk_N]."""
    validator = SentenceValidator()
    chunk1_id = uuid.uuid4()
    text = "The royalty fee shall be 5% of net revenues."
    chash = hashlib.sha256(text.encode()).hexdigest()

    alias1 = RetrievalAlias(
        alias="chunk_1",
        chunk_id=chunk1_id,
        doc_name="License Agreement",
        page="4",
        section="Section 4.1",
        text=text,
        content_hash=chash,
    )
    record = _build_test_record([alias1])

    # Valid tag
    v_valid = validator.validate_sentence(
        "The royalty fee is set at 5% of net revenues [chunk_1].", record
    )
    assert v_valid.passed is True
    assert v_valid.cited_aliases == ["chunk_1"]
    assert len(v_valid.failed_checks) == 0

    # Malformed tags: [chunk], [1], [doc_1]
    v_malformed_1 = validator.validate_sentence(
        "The royalty fee is set at 5% of net revenues [chunk].", record
    )
    assert v_malformed_1.passed is False
    assert "V1" in v_malformed_1.failed_checks

    v_malformed_2 = validator.validate_sentence(
        "The royalty fee is set at 5% of net revenues [1].", record
    )
    assert v_malformed_2.passed is False
    assert "V1" in v_malformed_2.failed_checks


@pytest.mark.stage7
@pytest.mark.unit
def test_validator_v2_alias_membership() -> None:
    """Verify check V2 rejects citation of aliases outside the request retrieval ledger."""
    validator = SentenceValidator()
    alias1 = RetrievalAlias(
        alias="chunk_1",
        chunk_id=uuid.uuid4(),
        doc_name="Agreement",
        page="1",
        section="Recitals",
        text="The agreement begins January 1, 2026.",
        content_hash=hashlib.sha256(b"content").hexdigest(),
    )
    record = _build_test_record([alias1])

    # Citing non-existent chunk_99
    verdict = validator.validate_sentence(
        "The agreement begins January 1, 2026 [chunk_99].", record
    )
    assert verdict.passed is False
    assert "V2" in verdict.failed_checks


@pytest.mark.stage7
@pytest.mark.unit
def test_validator_v4_citation_required() -> None:
    """Verify check V4 requires citations on all factual statements."""
    validator = SentenceValidator()
    record = _build_test_record([])

    verdict = validator.validate_sentence("The distributor must pay within 30 days.", record)
    assert verdict.passed is False
    assert "V4" in verdict.failed_checks


@pytest.mark.stage7
@pytest.mark.unit
def test_validator_v5_critical_token_matching() -> None:
    """Verify check V5 detects fabricated numbers, amounts, and dates."""
    validator = SentenceValidator()
    source_text = "The initial payment of $5,000,000 is due on 2026-12-01 under Section 12."
    chash = hashlib.sha256(source_text.encode()).hexdigest()

    alias1 = RetrievalAlias(
        alias="chunk_1",
        chunk_id=uuid.uuid4(),
        doc_name="Supply Agreement",
        page="7",
        section="Section 12",
        text=source_text,
        content_hash=chash,
    )
    record = _build_test_record([alias1])

    # True critical tokens match
    v_good = validator.validate_sentence(
        "Under Section 12, the initial payment is $5,000,000 due 2026-12-01 [chunk_1].",
        record,
    )
    assert v_good.passed is True

    # Fabricated number: $9,999,999
    v_bad = validator.validate_sentence(
        "Under Section 12, the initial payment is $9,999,999 due 2026-12-01 [chunk_1].",
        record,
    )
    assert v_bad.passed is False
    assert "V5" in v_bad.failed_checks


@pytest.mark.stage7
@pytest.mark.unit
def test_validator_v7_refusal_consistency() -> None:
    """Verify check V7 canonical refusal semantics."""
    validator = SentenceValidator()
    record = _build_test_record([])

    # Valid refusal
    v_refusal = validator.validate_sentence(CANONICAL_REFUSAL, record)
    assert v_refusal.passed is True
    assert v_refusal.cited_aliases == []

    # Refusal with tags is invalid per V7
    v_bad_refusal = validator.validate_sentence(f"{CANONICAL_REFUSAL} [chunk_1]", record)
    assert v_bad_refusal.passed is False
    assert "V7" in v_bad_refusal.failed_checks


@pytest.mark.stage7
@pytest.mark.unit
def test_validator_answer_strip_and_citations_resolution() -> None:
    """Verify full answer validation with strip policy and citation resolution (V8)."""
    validator = SentenceValidator()
    text1 = "Alpha Corp is registered in Delaware."
    text2 = "Beta Inc owns 100% of gamma."
    alias1 = RetrievalAlias(
        alias="chunk_1",
        chunk_id=uuid.uuid4(),
        doc_name="Charter.pdf",
        page="1",
        section="Article 1",
        text=text1,
        content_hash=hashlib.sha256(text1.encode()).hexdigest(),
    )
    alias2 = RetrievalAlias(
        alias="chunk_2",
        chunk_id=uuid.uuid4(),
        doc_name="Bylaws.pdf",
        page="2",
        section="Article 2",
        text=text2,
        content_hash=hashlib.sha256(text2.encode()).hexdigest(),
    )
    record = _build_test_record([alias1, alias2])

    raw_answer = (
        "Alpha Corp is registered in Delaware [chunk_1]. "
        "Beta Inc owns 999% of gamma [chunk_2]. "  # Fabricated 999%
        "The parties executed on Monday [chunk_1]."
    )

    response = validator.validate_answer(raw_answer, record, on_fail="strip")

    assert len(response.verdicts) == 3
    assert response.verdicts[0].passed is True
    assert response.verdicts[1].passed is False  # V5 failed
    assert response.verdicts[2].passed is True

    # Sentence 2 was stripped
    assert "[chunk_1]" in response.answer
    assert "could not be verified and was removed: V5" in response.answer

    # Citations list only includes chunk_1 (chunk_2 failed)
    assert len(response.citations) == 1
    assert response.citations[0].alias == "chunk_1"
    assert response.citations[0].doc_name == "Charter.pdf"
    assert response.citations[0].page == "1"


@pytest.mark.stage7
@pytest.mark.unit
def test_validator_all_failing_falls_back_to_refusal() -> None:
    """Verify that when 0 sentences pass verification, canonical refusal is produced."""
    validator = SentenceValidator()
    record = _build_test_record([])

    raw_answer = "Completely ungrounded claim with no citations whatsoever."
    response = validator.validate_answer(raw_answer, record)

    assert response.refusal is True
    assert response.answer == CANONICAL_REFUSAL
    assert len(response.citations) == 0
