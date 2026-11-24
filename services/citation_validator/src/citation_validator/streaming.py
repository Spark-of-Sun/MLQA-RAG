"""Sentence-gated validation of a streamed draft (blueprint 4.4 rules 2 and 3, 11.6, G7.2, G7.6, G7.7).

The validator, not the gateway, owns segmentation, so the unit validated is exactly the unit released. The
generation stream is text with inline citation tags (`... within 30 days [S2][S5].`); `SentenceSegmenter` cuts it
into sentences incrementally and is aware of legal and medical text: abbreviations (U.S.C., Inc., No., e.g., i.e.,
mg., approx.), decimals and amounts (1.5 mg, $1,250.00), section references (§ 2.3(b), Section 4.1), list numbers
and initials, so a period inside those never ends a sentence.

Each completed sentence is validated against the ledger (V1 to V5, V7, V8 from validator.validate, V3 re-checked
against current chunk hashes, V6 with the pinned NLI model when configured) and answered with a **signed verdict**:
an ES256 JWS by the validator's KMS-certified key over {request_id, seq, text, sha256, ok, checks, citations}. The
gateway releases a sentence only with a verdict whose signature verifies for this request and whose text hash
matches; it cannot alter a verdict without breaking the signature (G7.6).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import jwt

from citation_validator.validator import Verdict, sha256_text, validate
from lmqa_auth.context import ContextTokenError, Signer, SignerCertificate
from lmqa_models.rag import Source

_TAG = re.compile(r"\[(S\d{1,2})\]")
_ABBREVIATIONS = frozenset(
    {
        "inc",
        "ltd",
        "llc",
        "co",
        "corp",
        "no",
        "nos",
        "art",
        "arts",
        "sec",
        "secs",
        "ch",
        "para",
        "paras",
        "cl",
        "cls",
        "fig",
        "figs",
        "vol",
        "vols",
        "ed",
        "eds",
        "approx",
        "est",
        "e.g",
        "i.e",
        "etc",
        "vs",
        "v",
        "cf",
        "al",
        "et",
        "u.s",
        "u.s.c",
        "c.f.r",
        "fed",
        "reg",
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "st",
        "jr",
        "sr",
        "dept",
        "govt",
        "mg",
        "mcg",
        "kg",
        "ml",
        "dl",
        "min",
        "max",
        "hr",
        "hrs",
        "wk",
        "wks",
        "mo",
        "yr",
        "yrs",
        "pt",
        "pts",
        "dx",
        "tx",
        "rx",
        "hx",
        "sx",
        "b.i.d",
        "t.i.d",
        "q.i.d",
        "p.o",
        "i.v",
        "i.m",
        "s.c",
        "q.d",
        "prn",
    }
)
_TERMINAL = re.compile(r"[.!?](?:[\"')\]]*)(?:\s*(?:\[S\d{1,2}\])+)?(?=\s+[A-Z(\"'\[]|\s*$)")


def _is_abbreviation(text_before: str) -> bool:
    word = re.findall(r"([A-Za-z][A-Za-z.]*)$", text_before)
    if not word:
        return False
    w = word[0].lower().rstrip(".")
    if w in _ABBREVIATIONS:
        return True
    return len(w) == 1  # initials: "J. Smith", list letters "a."


def _is_number_period(text: str, i: int) -> bool:
    return (
        i + 1 < len(text)
        and text[i] == "."
        and text[i - 1 : i].isdigit()
        and text[i + 1 : i + 2].isdigit()
    )


class SentenceSegmenter:
    """Feed text deltas; get complete sentences (with their trailing tags) as soon as they end."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        start = 0
        for m in _TERMINAL.finditer(self._buf):
            end = m.end()
            dot = m.start()
            if self._buf[dot] == "." and (
                _is_abbreviation(self._buf[start:dot]) or _is_number_period(self._buf, dot)
            ):
                continue
            if end == len(self._buf):
                break  # the next delta may still extend this sentence (more tags, a closing quote)
            sentence = self._buf[start:end].strip()
            if sentence:
                out.append(sentence)
            start = end
        self._buf = self._buf[start:]
        return out

    def flush(self) -> list[str]:
        rest, self._buf = self._buf.strip(), ""
        return [rest] if rest else []


def split_tags(sentence: str) -> tuple[str, list[str]]:
    aliases = _TAG.findall(sentence)
    return _TAG.sub("", sentence).strip(), list(dict.fromkeys(aliases))


@dataclass
class SignedVerdict:
    seq: int
    text: str
    sha256: str
    ok: bool
    refusal: bool
    citations: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    token: str = ""


@dataclass
class StreamValidator:
    """One per request. `entail(sentence, premises)` is V6 (pinned NLI) or None to skip V6 (buffered MVP mode)."""

    request_id: str
    ledger: dict[str, Source]
    current_hashes: Callable[[list[str]], dict[str, str]]  # chunk_id -> sha256 now, under RLS
    signer: Signer
    entail: Callable[[str, list[str]], tuple[bool, float]] | None = None
    seq: int = 0
    segmenter: SentenceSegmenter = field(default_factory=SentenceSegmenter)

    def feed(self, delta: str) -> Iterator[SignedVerdict]:
        for sentence in self.segmenter.feed(delta):
            yield self._judge(sentence)

    def finish(self) -> Iterator[SignedVerdict]:
        for sentence in self.segmenter.flush():
            yield self._judge(sentence)

    def _judge(self, raw: str) -> SignedVerdict:
        text, aliases = split_tags(raw)
        draft = {
            "answerable": True,
            "sentences": [{"text": text, "citations": [{"source": a} for a in aliases]}],
        }
        _, verdicts = validate(draft, self.ledger, entailment=self.entail is not None)
        v: Verdict = verdicts[0] if verdicts else Verdict(index=0, text=text)
        if not verdicts:
            v.fail("V1", "empty sentence")
        # V3 at validation time: every cited chunk must still hash to what retrieval recorded.
        cited = [self.ledger[a] for a in v.aliases if a in self.ledger]
        now = self.current_hashes([s.chunk_id for s in cited]) if cited else {}
        for s in cited:
            if now.get(s.chunk_id) != s.sha256:
                v.fail("V3", "a cited passage changed after retrieval")
        if self.entail is not None and v.ok and not v.refusal and cited:
            ok, p = self.entail(v.text, [s.text for s in cited])
            if ok:
                v.passed("V6", f"entailment {p:.3f}")
            else:
                v.fail("V6", f"not entailed by the cited passages ({p:.3f})")
        self.seq += 1
        verdict = SignedVerdict(
            seq=self.seq,
            text=v.text,
            sha256=sha256_text(v.text),
            ok=v.ok,
            refusal=v.refusal,
            citations=[
                {
                    "alias": a,
                    "chunk_id": self.ledger[a].chunk_id,
                    "chunk_sha256": self.ledger[a].sha256,
                    "spans": v.spans.get(a, []),
                }
                for a in v.aliases
                if a in self.ledger
            ],
            checks=[c.as_dict() for c in v.checks],
        )
        verdict.token = sign_verdict(self.signer, self.request_id, verdict)
        return verdict


def _verdict_claims(request_id: str, v: SignedVerdict) -> dict[str, Any]:
    return {
        "rid": request_id,
        "seq": v.seq,
        "sha256": v.sha256,
        "ok": v.ok,
        "refusal": v.refusal,
        "cites": [[c["alias"], c["chunk_id"], c["chunk_sha256"]] for c in v.citations],
    }


def sign_verdict(signer: Signer, request_id: str, v: SignedVerdict) -> str:
    key, cert = signer.current()
    return jwt.encode(
        _verdict_claims(request_id, v),
        key,
        algorithm="ES256",
        headers={"kid": cert.kid, "x5c_lmqa": cert.encode()},
    )


def verify_verdict(
    token: str, *, request_id: str, text: str, roots: dict[str, Any]
) -> dict[str, Any]:
    """Gateway side: the verdict must be signed by a certificate the trust root issued to `citation_validator`,
    for this request, over exactly this text."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        header = jwt.get_unverified_header(token)
        cert = SignerCertificate.decode(str(header["x5c_lmqa"]))
        roots[cert.root_kid].verify(cert.signature, cert.body(), ec.ECDSA(hashes.SHA256()))
        if cert.identity != "citation_validator":
            raise ContextTokenError("verdict signer identity")
        claims = jwt.decode(
            token, serialization.load_pem_public_key(cert.public_pem), algorithms=["ES256"]
        )
    except (KeyError, ValueError, jwt.PyJWTError) as exc:
        raise ContextTokenError("verdict signature") from exc
    except Exception as exc:  # cryptography.exceptions.InvalidSignature
        raise ContextTokenError("verdict signature") from exc
    if (
        claims.get("rid") != request_id
        or claims.get("sha256") != hashlib.sha256(text.encode()).hexdigest()
    ):
        raise ContextTokenError("verdict does not match the sentence")
    return claims
