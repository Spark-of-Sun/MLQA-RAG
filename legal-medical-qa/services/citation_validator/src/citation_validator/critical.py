"""Critical-token extraction and matching (doc 11.6 check V5, 11.4).

A sentence may only be released if every *critical token* in it appears in the chunk(s) it cites,
after normalization: numbers and amounts (thousands separators, currency, scale words), dates (any
common format, compared as ISO), dosages with units, and statute or section references. This is
the cheap deterministic net under the entailment model: an invented "$2,000,000" or "45 days" can
never pass, however plausible the sentence reads.

Extraction masks matches in this order so nothing is counted twice: references, dates, dosages,
then plain numbers and amounts.

Known limit: numbers written as words ("thirty days") are not critical tokens; the entailment
check (V6) is what covers them.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Final

MONTHS: Final = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
_MONTH_RE: Final = "|".join(
    [*MONTHS, "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sept?", "oct", "nov", "dec"]
)
_ABBREV_MONTH: Final = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_REF: Final = re.compile(
    r"(?:§§?\s*\d[\d.]*(?:\([A-Za-z0-9]{1,4}\))*"
    r"|\b(?:Section|Sec\.|Article|Clause|Rule)\s+\d[\d.]*(?:\([A-Za-z0-9]{1,4}\))*"
    r"|\b\d+\s*(?:C\.?F\.?R\.?|U\.?S\.?C\.?)\s*(?:§\s*)?\d[\d.]*(?:\([A-Za-z0-9]{1,4}\))*)",
    re.IGNORECASE,
)
_DATE_TEXT: Final = re.compile(
    rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE
)
_DATE_TEXT_DMY: Final = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})\b", re.IGNORECASE
)
_DATE_ISO: Final = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_US: Final = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_UNITS: Final = (
    r"(?:mg/kg|mg/dl|mcg/kg|mg|mcg|\u00b5g|ug|kg|g|ml|l|iu|meq|mmol"
    r"|units?|tablets?|capsules?|%|percent)"
)
_DOSE: Final = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*({_UNITS})(?![A-Za-z])", re.IGNORECASE)
_NUMBER: Final = re.compile(
    r"(?<![\w.])(\$?)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(thousand|million|billion))?(?![\w])",
    re.IGNORECASE,
)
_SCALE: Final = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_UNIT_ALIAS: Final = {
    "ug": "mcg",
    "\u00b5g": "mcg",
    "percent": "%",
    "unit": "units",
    "tablet": "tablets",
    "capsule": "capsules",
}


def _month(name: str) -> int:
    key = name.lower().rstrip(".")
    return MONTHS.get(key) or _ABBREV_MONTH[key]


def _iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _canon_number(raw: str, scale: str | None = None) -> str:
    value = float(raw.replace(",", ""))
    if scale:
        value *= _SCALE[scale.lower()]
    return f"{value:.10f}".rstrip("0").rstrip(".") or "0"


def _canon_ref(raw: str) -> str:
    """Lower-case, drop spaces and the dots of abbreviations (C.F.R.), keep dots inside numbers."""
    text = raw.lower().replace("sec.", "section")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"(?<=[a-z])\.", "", text)
    return text.rstrip(".")


def _mask(text: str, pattern: re.Pattern[str], found: set[str], build) -> str:  # noqa: ANN001
    def repl(m: re.Match[str]) -> str:
        token = build(m)
        if not token:
            return m.group(
                0
            )  # not a valid date or reference: keep it so its numbers are still checked
        found.add(token)
        return " " * len(m.group(0))

    return pattern.sub(repl, text)


def critical_tokens(text: str) -> set[str]:
    """Normalized critical tokens in ``text``, each prefixed with its kind."""
    found: set[str] = set()
    work = text
    work = _mask(work, _REF, found, lambda m: "ref:" + _canon_ref(m.group(0)))
    work = _mask(
        work,
        _DATE_TEXT,
        found,
        lambda m: (d := _iso(int(m.group(3)), _month(m.group(1)), int(m.group(2)))) and f"date:{d}",
    )
    work = _mask(
        work,
        _DATE_TEXT_DMY,
        found,
        lambda m: (d := _iso(int(m.group(3)), _month(m.group(2)), int(m.group(1)))) and f"date:{d}",
    )
    work = _mask(
        work,
        _DATE_ISO,
        found,
        lambda m: (d := _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))) and f"date:{d}",
    )
    work = _mask(
        work,
        _DATE_US,
        found,
        lambda m: (d := _iso(int(m.group(3)), int(m.group(1)), int(m.group(2)))) and f"date:{d}",
    )

    def dose(m: re.Match[str]) -> str:
        unit = m.group(2).lower()
        return f"dose:{_canon_number(m.group(1))}{_UNIT_ALIAS.get(unit, unit)}"

    work = _mask(work, _DOSE, found, dose)
    for m in _NUMBER.finditer(work):
        kind = "amount" if m.group(1) else "num"
        found.add(f"{kind}:{_canon_number(m.group(2), m.group(3))}")
    return found


def missing_tokens(sentence: str, sources: list[str]) -> set[str]:
    """Critical tokens of ``sentence`` that appear in none of the cited ``sources``."""
    needed = critical_tokens(sentence)
    available: set[str] = set()
    for source in sources:
        available |= critical_tokens(source)
    # An amount ("$5") and the same number without a currency sign satisfy each other.
    relaxed = {t.split(":", 1)[1] for t in available if t.startswith(("num:", "amount:"))}
    return {
        t
        for t in needed
        if t not in available
        and not (t.startswith(("num:", "amount:")) and t.split(":", 1)[1] in relaxed)
    }
