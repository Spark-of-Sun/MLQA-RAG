"""Line-level structure detection for legal and clinical text (doc 11.1 step 6).

Legal: ARTICLE, Section and numbered clauses, schedules and exhibits, defined-term sections,
opinion headings. Medical: SOAP headers (Subjective, Objective, Assessment, Plan), HPI and
medication lists. A document in which nothing matches is chunked as paragraphs and flagged
``structure = fallback``; it is never silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

MAX_HEADING_CHARS: Final = 120
MAX_CAPS_WORDS: Final = 8
_ROMAN: Final = r"[IVXLC]+"


@dataclass(frozen=True, slots=True)
class HeadingClass:
    """How one line was classified."""

    level: int
    number: str | None
    title: str
    label: str
    soap: str | None = None


_ARTICLE = re.compile(rf"^(ARTICLE)\s+({_ROMAN}|\d+)\b[\s.:\-\u2013\u2014]*(.*)$", re.IGNORECASE)
_ANNEX = re.compile(
    r"^(SCHEDULE|EXHIBIT|ANNEX|APPENDIX)\s+([A-Z0-9][A-Za-z0-9\-]*)\b[\s.:\-\u2013\u2014]*(.*)$"
)
_SECTION = re.compile(
    r"^(Section|SECTION|§)\s*(\d+(?:\.\d+)*[A-Za-z]?)\.?[\s:\-\u2013\u2014]*(.*)$"
)
_NUMERIC = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+([A-Z][A-Za-z0-9 ,;&'()\-/]{2,80}?)\.?$")
_NUMBERED = re.compile(r"^(\d{1,2})\.\s+([A-Z][A-Za-z ,;&'()\-/]{2,60})$")
_OPINION_ROMAN = re.compile(r"^([IVX]{1,5})$")
_OPINION_LETTER = re.compile(r"^([A-Z])$")
_CAPS = re.compile(r"^[A-Z][A-Z0-9 ,;&'()\-/]{3,70}$")
_SOAP = {
    "subjective": "soap_subjective",
    "history of present illness": "soap_subjective",
    "hpi": "soap_subjective",
    "chief complaint": "soap_subjective",
    "objective": "soap_objective",
    "physical examination": "soap_objective",
    "vital signs": "soap_objective",
    "assessment": "soap_assessment",
    "impression": "soap_assessment",
    "diagnosis": "soap_assessment",
    "plan": "soap_plan",
    "medications": "paragraph",
}
_SOAP_LINE = re.compile(
    r"^(" + "|".join(re.escape(k) for k in _SOAP) + r")\s*:?\s*$", re.IGNORECASE
)
_NOT_HEADINGS = {"PAGE", "TABLE OF CONTENTS", "CONFIDENTIAL"}


def _article(m: re.Match[str], text: str) -> HeadingClass | None:
    if len(text) > MAX_HEADING_CHARS:
        return None
    return HeadingClass(0, f"ARTICLE {m[2].upper()}", m[3].strip().rstrip(".") or m[1], text)


def _annex(m: re.Match[str], text: str) -> HeadingClass | None:
    return HeadingClass(
        0, f"{m[1].upper()} {m[2]}", m[3].strip().rstrip(".") or m[1], text[:MAX_HEADING_CHARS]
    )


def _section(m: re.Match[str], _text: str) -> HeadingClass | None:
    title = m[3].split(".")[0].strip() if m[3] else ""
    return HeadingClass(1, m[2], title, f"Section {m[2]}" + (f" {title}" if title else ""))


def _numeric(m: re.Match[str], text: str) -> HeadingClass | None:
    if len(text) > MAX_HEADING_CHARS:
        return None
    return HeadingClass(min(m[1].count(".") + 1, 4), m[1], m[2], f"{m[1]} {m[2]}")


def _numbered(m: re.Match[str], text: str) -> HeadingClass | None:
    return None if text.endswith(".") else HeadingClass(0, m[1], m[2], f"{m[1]}. {m[2]}")


def _soap(m: re.Match[str], _text: str) -> HeadingClass | None:
    return HeadingClass(0, None, m[1].title(), m[1].title(), soap=_SOAP[m[1].lower()])


def _roman(m: re.Match[str], _text: str) -> HeadingClass | None:  # opinion headings: I, II, III, IV
    return HeadingClass(0, m[1], m[1], m[1])


def _letter(m: re.Match[str], _text: str) -> HeadingClass | None:  # opinion subheading: A, B
    return HeadingClass(1, m[1], m[1], m[1])


def _caps(_m: re.Match[str], text: str) -> HeadingClass | None:
    if text in _NOT_HEADINGS or len(text.split()) > MAX_CAPS_WORDS or text.endswith((".", ",")):
        return None
    return HeadingClass(0, None, text.title(), text.title())


_RULES: Final = (
    (_ARTICLE, _article),
    (_ANNEX, _annex),
    (_SECTION, _section),
    (_NUMERIC, _numeric),
    (_NUMBERED, _numbered),
    (_SOAP_LINE, _soap),
    (_OPINION_ROMAN, _roman),
    (_OPINION_LETTER, _letter),
    (_CAPS, _caps),
)


def classify_line(line: str) -> HeadingClass | None:
    """Return the heading class of ``line`` or None for body text. The first matching rule wins."""
    text = " ".join(line.split())
    if not text or len(text) > MAX_HEADING_CHARS * 3:
        return None
    for pattern, build in _RULES:
        if (match := pattern.match(text)) and (result := build(match, text)) is not None:
            return result
    return None
