from __future__ import annotations

from app.entailment_check.fake_backend import WordOverlapEntailmentChecker
from app.schemas.requests import ChunkForValidation
from app.validator import validate_answer


def _chunk(chunk_id, text, document_id="doc1", page=4, section="4.2"):
    return ChunkForValidation(chunk_id=chunk_id, document_id=document_id, text=text, page=page, section=section)


def test_passes_when_citation_is_supported():
    result = validate_answer(
        answer_text="The term is 12 months [c1].",
        retrieved_chunks=[_chunk("c1", "The term of this agreement is 12 months.")],
        tenant_policy="strip_unverified",
        entailment_support_threshold=0.3,
        entailment_checker=WordOverlapEntailmentChecker(),
    )
    assert result.validation_outcome.value == "pass"
    assert "[1]" in result.verified_answer_text
    assert result.resolved_citations[0].chunk_id == "c1"
    assert all(f.check.value == "ok" for f in result.findings)


def test_flags_chunk_not_in_retrieved_set():
    result = validate_answer(
        answer_text="The term is 12 months [c1].",
        retrieved_chunks=[],  # c1 was never actually retrieved for this request
        tenant_policy="strip_unverified",
        entailment_support_threshold=0.3,
        entailment_checker=WordOverlapEntailmentChecker(),
    )
    assert result.validation_outcome.value == "stripped_unverified"
    assert result.findings[0].check.value == "chunk_not_in_retrieved_set"
    assert "[unverified]" in result.verified_answer_text
    assert result.resolved_citations == []


def test_flags_entailment_below_threshold():
    result = validate_answer(
        answer_text="The patient has stage 4 cancer [c1].",
        retrieved_chunks=[_chunk("c1", "Patient reports occasional mild headaches.")],
        tenant_policy="strip_unverified",
        entailment_support_threshold=0.5,
        entailment_checker=WordOverlapEntailmentChecker(),
    )
    assert result.validation_outcome.value == "stripped_unverified"
    assert result.findings[0].check.value == "entailment_below_threshold"
    assert "[unverified]" in result.verified_answer_text


def test_regenerate_policy_sets_regenerate_outcome():
    result = validate_answer(
        answer_text="The term is 12 months [c1].",
        retrieved_chunks=[],
        tenant_policy="regenerate",
        entailment_support_threshold=0.3,
        entailment_checker=WordOverlapEntailmentChecker(),
    )
    assert result.validation_outcome.value == "regenerate_required"


def test_passes_trivially_with_no_citations():
    result = validate_answer(
        answer_text="the provided documents do not address this",
        retrieved_chunks=[],
        tenant_policy="strip_unverified",
        entailment_support_threshold=0.3,
        entailment_checker=WordOverlapEntailmentChecker(),
    )
    assert result.validation_outcome.value == "pass"
    assert result.findings == []



def test_numbers_multiple_citations_by_order_of_appearance():
    result = validate_answer(
        answer_text="First claim [c2]. Second claim [c1].",
        retrieved_chunks=[
            _chunk("c1", "second claim text content here"),
            _chunk("c2", "first claim text content here"),
        ],
        tenant_policy="strip_unverified",
        entailment_support_threshold=0.1,
        entailment_checker=WordOverlapEntailmentChecker(),
    )
    assert "[1]" in result.verified_answer_text
    assert "[2]" in result.verified_answer_text


def test_trailing_citations_list_does_not_downgrade_a_supported_inline_citation():
    # Regression test for the bug found via live Gemini integration testing:
    # the structured "Citations:" list the prompt template asks for must
    # not be treated as a second, unsupported claim that overwrites a
    # well-supported inline citation's OK result.
    result = validate_answer(
        answer_text=(
            "Either party may terminate with 30 days notice [c1].\n\n"
            "Citations:\n[c1] Smith_Contract.pdf, page 12, section 4.2"
        ),
        retrieved_chunks=[_chunk("c1", "Either party may terminate this agreement with 30 days written notice.")],
        tenant_policy="strip_unverified",
        entailment_support_threshold=0.5,
        entailment_checker=WordOverlapEntailmentChecker(),
    )
    assert result.validation_outcome.value == "pass"
    assert "[unverified]" not in result.verified_answer_text
    assert "[1]" in result.verified_answer_text