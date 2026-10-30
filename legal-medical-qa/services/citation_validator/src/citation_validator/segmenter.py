"""The one pinned sentence segmenter (doc 11.6, DEF-50).

The Validator owns segmentation, so the unit that is validated is exactly the unit that is
released. It is deterministic and *partition independent*: feeding the same text in any split of
deltas yields the same sentences, because a boundary is only decided once the next non-space
character is known (or the stream has ended).

A sentence ends at ``.``, ``?`` or ``!`` followed by whitespace and a sentence start, except after
a known abbreviation or a single capital initial. Citation tags ``[chunk_N]`` that follow the
terminator stay with the sentence they cite. A line break before a list marker, a heading or a
blank line also ends a sentence, so bulleted answers segment per item.
"""

from __future__ import annotations

import re
from typing import Final

SEGMENTER_VERSION: Final = "lmqa-seg-1"
ABBREVIATIONS: Final = frozenset(
    {
        "inc",
        "ltd",
        "llc",
        "corp",
        "co",
        "no",
        "nos",
        "v",
        "vs",
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sec",
        "secs",
        "art",
        "arts",
        "fig",
        "figs",
        "eq",
        "cf",
        "e.g",
        "i.e",
        "u.s",
        "u.s.c",
        "c.f.r",
        "cfr",
        "usc",
        "approx",
        "dept",
        "st",
        "jr",
        "sr",
        "et",
        "al",
        "ex",
        "cl",
        "para",
        "pp",
        "p",
        "vol",
        "ch",
        "etc",
        "viz",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
        "mt",
        "ft",
        "lbs",
        "oz",
    }
)
_TAG: Final = re.compile(r"\[chunk_\d+\]")
_LIST: Final = re.compile(r"(?:[-*\u2022#]|\d{1,2}[.)])\s")
_LAST_WORD: Final = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")
_CLOSERS: Final = "\"')]}\u201d\u2019"
_STARTERS: Final = "\"'([{\u201c\u2018#-*\u2022"
_BLANKS: Final = " \t"
_PARTIAL_TAG_MAX: Final = 16


def is_abbreviation(sentence_so_far: str) -> bool:
    """True if the text, which ends with a period, ends in an abbreviation or a capital initial."""
    match = _LAST_WORD.search(sentence_so_far)
    if match is None:
        return False
    token = match.group(1)
    return token.lower().rstrip(".") in ABBREVIATIONS or (len(token) == 1 and token.isupper())


def _starts_sentence(ch: str) -> bool:
    return ch.isupper() or ch.isdigit() or ch in _STARTERS


def _skip_blanks(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in _BLANKS:
        pos += 1
    return pos


def _consume_tags(text: str, pos: int, *, final: bool) -> tuple[int, int, bool]:
    """Consume tags after a terminator. Returns ``(end_of_sentence, next_pos, undecided)``."""
    end = pos
    k = _skip_blanks(text, pos)
    while k < len(text):
        match = _TAG.match(text, k)
        if match is None:
            rest = text[k:]
            if (
                not final
                and rest.startswith("[")
                and "]" not in rest
                and len(rest) <= _PARTIAL_TAG_MAX
            ):
                return end, k, True  # a tag may still be arriving
            break
        end = k = match.end()
        if k < len(text) and text[k] in ".?!" and (k + 1 >= len(text) or text[k + 1] in " \t\n"):
            end = k = k + 1  # a period written after the tag belongs to this sentence too
        k = _skip_blanks(text, k)
    return end, k, False


def split(text: str, *, final: bool) -> tuple[list[str], str]:  # noqa: C901 - one scanning loop
    """Split ``text`` into ``(complete sentences, undecided remainder)``.

    With ``final=True`` everything is complete and the remainder is empty. With ``final=False`` a
    boundary is reported only when the character after it is known, so any partition of the same
    stream produces the same sentences.
    """
    sentences: list[str] = []
    n, start, i = len(text), 0, 0

    def emit(end: int) -> None:
        piece = text[start:end].strip()
        if piece:
            sentences.append(piece)

    while i < n:
        ch = text[i]
        if ch == "\n":
            j = _skip_blanks(text, i + 1)
            if j >= n:
                if not final:
                    return sentences, text[start:]
                break
            heading_line = (
                text[start:i].lstrip().startswith("#")
            )  # a heading ends at its line break
            if heading_line or text[j] == "\n" or _LIST.match(text, j):
                emit(i)
                start = i = j
                continue
        elif ch in ".?!":
            j = i + 1
            while j < n and text[j] in _CLOSERS:
                j += 1
            end, k, undecided = _consume_tags(text, j, final=final)
            if undecided or (k >= n and not final):
                return sentences, text[start:]
            if k >= n:
                break
            if text[k] == "\n":
                emit(end)
                start = i = k
                continue
            if (
                k > end
                and _starts_sentence(text[k])
                and not (ch == "." and is_abbreviation(text[start : i + 1]))
            ):
                emit(end)
                start = i = k
                continue
            i = max(j, end)
            continue
        i += 1
    if final:
        emit(n)
        return sentences, ""
    return sentences, text[start:]


class StreamSegmenter:
    """Feed token deltas, receive completed sentences. ``finish`` flushes the last one."""

    def __init__(self) -> None:
        """Start with an empty buffer."""
        self._buffer = ""

    def feed(self, delta: str) -> list[str]:
        """Add text; return the sentences that are now certainly complete."""
        self._buffer += delta
        done, self._buffer = split(self._buffer, final=False)
        return done

    def finish(self) -> list[str]:
        """End of stream: return everything still pending as sentences."""
        done, self._buffer = split(self._buffer, final=True)
        return done
