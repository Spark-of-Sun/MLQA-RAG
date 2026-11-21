"""Segmentation (G7.2) and critical tokens (G7.5): pure, deterministic, model-free."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from citation_validator.critical import critical_tokens, missing_tokens
from citation_validator.segmenter import StreamSegmenter, split

pytestmark = [pytest.mark.unit, pytest.mark.stage7]


def sentences(text: str) -> list[str]:
    return split(text, final=True)[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Notice is thirty days. Payment is due monthly.",
            ["Notice is thirty days.", "Payment is due monthly."],
        ),
        (
            "Acme Inc. shall pay Beta Corp. a fee [chunk_1]. It is due.",
            ["Acme Inc. shall pay Beta Corp. a fee [chunk_1].", "It is due."],
        ),
        (
            "The cap is 3.5 times fees [chunk_2]. See Section 4.2 for details [chunk_1].",
            ["The cap is 3.5 times fees [chunk_2].", "See Section 4.2 for details [chunk_1]."],
        ),
        (
            "Smith v. Jones held otherwise [chunk_3]. The court agreed.",
            ["Smith v. Jones held otherwise [chunk_3].", "The court agreed."],
        ),
        (
            "Dr. A. Brown prescribed 5 mg daily [chunk_1]. Dose may rise.",
            ["Dr. A. Brown prescribed 5 mg daily [chunk_1].", "Dose may rise."],
        ),
        (
            "It applies under 45 C.F.R. 164.312 [chunk_1]. Nothing else does.",
            ["It applies under 45 C.F.R. 164.312 [chunk_1].", "Nothing else does."],
        ),
        (
            "Cited later. [chunk_1] The next one. [chunk_2]",
            ["Cited later. [chunk_1]", "The next one. [chunk_2]"],
        ),
        ("Is it valid? Yes [chunk_1]! Done.", ["Is it valid?", "Yes [chunk_1]!", "Done."]),
        (
            "- first item [chunk_1]\n- second item [chunk_2]",
            ["- first item [chunk_1]", "- second item [chunk_2]"],
        ),
        ("# Heading\nBody text follows [chunk_1].", ["# Heading", "Body text follows [chunk_1]."]),
        ("One sentence without a final period", ["One sentence without a final period"]),
        ("", []),
    ],
)
def test_segmentation_cases(text: str, expected: list[str]) -> None:
    assert sentences(text) == expected


def test_a_boundary_is_not_decided_until_the_next_character_is_known() -> None:
    seg = StreamSegmenter()
    assert seg.feed("The term is two years.") == []  # could be an abbreviation or a decimal: wait
    assert seg.feed(" ") == []
    assert seg.feed("It renews.") == ["The term is two years."]
    assert seg.finish() == ["It renews."]


def test_a_tag_arriving_after_the_period_stays_with_its_sentence() -> None:
    seg = StreamSegmenter()
    out = []
    for piece in ["Fees are fixed.", " [chu", "nk_1] ", "Next one follows [chunk_2]."]:
        out += seg.feed(piece)
    out += seg.finish()
    assert out == ["Fees are fixed. [chunk_1]", "Next one follows [chunk_2]."]


ANSWER = (
    "The notice period is 30 days [chunk_1]. Acme Inc. may terminate under Section 4.2 [chunk_2]. "
    "Fees are $1,500,000 per year, i.e. high [chunk_1].\n- Item A [chunk_3]\n- Item B [chunk_3]\n\n"
    "# Summary\nDone. The provided documents do not address this."
)


@settings(max_examples=300, deadline=None)
@given(st.lists(st.integers(1, len(ANSWER) // 2), min_size=1, max_size=12))
def test_any_partition_of_the_stream_gives_the_same_sentences(cuts: list[int]) -> None:
    whole = sentences(ANSWER)
    points = sorted({c % len(ANSWER) for c in cuts})
    pieces, prev = [], 0
    for p in [*points, len(ANSWER)]:
        pieces.append(ANSWER[prev:p])
        prev = p
    seg, got = StreamSegmenter(), []
    for piece in pieces:
        got += seg.feed(piece)
    got += seg.finish()
    assert got == whole


def test_byte_at_a_time_streaming_matches_batch() -> None:
    seg, got = StreamSegmenter(), []
    for ch in ANSWER:
        got += seg.feed(ch)
    assert got + seg.finish() == sentences(ANSWER)


def test_segmentation_is_deterministic_and_never_loses_text() -> None:
    assert sentences(ANSWER) == sentences(ANSWER)
    assert "".join("".join(s.split()) for s in sentences(ANSWER)) == "".join(ANSWER.split())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pay $1,500,000 within 30 days.", {"amount:1500000", "num:30"}),
        ("Pay 1.5 million dollars.", {"num:1500000"}),
        (
            "Signed on March 3, 2024 and 4 April 2024 and 2024-05-06 and 7/8/2024.",
            {"date:2024-03-03", "date:2024-04-04", "date:2024-05-06", "date:2024-07-08"},
        ),
        (
            "Take 5 mg or 0.5 mL, never 10mg/kg; 20 units, 3 tablets.",
            {"dose:5mg", "dose:0.5ml", "dose:10mg/kg", "dose:20units", "dose:3tablets"},
        ),
        (
            "See § 164.312(a)(2)(ii) and Section 4.2 and 45 CFR 164.312.",
            {"ref:§164.312(a)(2)(ii)", "ref:section4.2", "ref:45cfr164.312"},
        ),
        ("A 5% fee and 12 percent interest.", {"dose:5%", "dose:12%"}),
        ("No numbers here at all.", set()),
        ("Feb 30, 2024 is not a real date.", {"num:30", "num:2024"}),
    ],
)
def test_critical_token_extraction(text: str, expected: set[str]) -> None:
    assert critical_tokens(text) == expected


def test_formats_normalize_to_the_same_token() -> None:
    assert (
        critical_tokens("on March 3, 2024")
        == critical_tokens("on 3 March 2024")
        == critical_tokens("on 2024-03-03")
    )
    assert critical_tokens("$1,500,000") == critical_tokens("$1500000")
    assert critical_tokens("5mg") == critical_tokens("5 MG")
    assert critical_tokens("Section 4.2") == critical_tokens("Sec. 4.2")


def test_an_invented_figure_is_missing_but_a_supported_one_is_not() -> None:
    chunk = "The Company shall pay a fee of $2,000,000 on March 1, 2025 under Section 7.1 at 10 mg daily."
    assert missing_tokens("The fee is $2,000,000 [chunk_1].", [chunk]) == set()
    assert missing_tokens("The fee is $3,000,000.", [chunk]) == {"amount:3000000"}
    assert missing_tokens("Due 1 March 2025.", [chunk]) == set()
    assert missing_tokens("Due 2 March 2025.", [chunk]) == {"date:2025-03-02"}
    assert missing_tokens("See Section 7.2.", [chunk]) == {"ref:section7.2"}
    assert missing_tokens("Take 20 mg.", [chunk]) == {"dose:20mg"}
    assert missing_tokens("It is 45 days.", [chunk]) == {"num:45"}


def test_tokens_may_be_supported_by_any_cited_chunk() -> None:
    assert missing_tokens("Fee $5 and 10 days.", ["Fee is $5.", "Notice is 10 days."]) == set()
    assert missing_tokens("Fee $5 and 10 days.", ["Fee is $5."]) == {"num:10"}
