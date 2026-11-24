# ADR 0006: Delivery modes and the citation validator

- Status: Accepted, MVP deviation in force (date 2026-11-22)
- Blueprint: sections 4.4, 11.6, 17.3; decision D15; principle 12; defects DEF-05, DEF-36, DEF-62;
  gates G7.1 to G7.12, G8.4

## Context

The product promise is that every claim a user sees carries a machine-verified citation. Earlier documents
streamed raw tokens to the browser and marked them "unverified" until the validator caught up (DEF-05). That
shows unverified text, contradicts the promise and cannot support regeneration, because text already shown
cannot be taken back. Users still expect answers to appear quickly, and an LLM cannot judge its own citations.

## Decision

- D15 delivery modes (11.6), set per organization:
  - `sentence_gated` (default, `on_fail = strip`): the Gateway forwards the generation stream to the
    Validator, which segments it with one pinned segmenter and returns a signed verdict carrying each sentence's
    text. The Gateway releases only sentences with a passing verdict.
  - `buffered` (required for `on_fail = regenerate`): the whole answer is generated and validated first; at most
    2 regeneration attempts, then a clear failure.
  - No provisional mode. There is no mode in which unverified text is shown.
- The Validator owns segmentation, so the validated unit is the released unit.
- Checks V1 to V8, all deterministic, no generative LLM: tag grammar `[chunk_N]`, alias membership in the
  ledger, chunk hash integrity, citation required, critical-token match (numbers, dates, amounts, dosages,
  statute references), V6 entailment by a pinned NLI cross-encoder (weights hash pinned, CPU, fixed thresholds
  calibrated to precision at least 0.99 on human-labeled data), refusal consistency, resolution to page, section
  and span.
- Signed verdicts over (`request_id`, sentence SHA-256, verdict, check results) with a KMS-certified ephemeral
  key. Write-ahead audit: `segment.released` (hashes only) before each sentence, `query.completed` with the sealed
  payload at the end. If any audit write fails the stream stops.
- SSE events `status`, `sentence`, `citations`, `warning`, `done`, `error`; a 10-minute encrypted resume buffer
  serves `Last-Event-ID` reconnects with released sentences only (DEF-62).
- Frontend: a thin SSE client on `eventsource-parser` (DEF-36); the Vercel AI SDK is not used (17.3).

## Alternatives considered

- Provisional streaming with later marking: rejected (DEF-05).
- An LLM judge for citations: rejected as the authority; not deterministic and shares the generator's failure modes.
- Buffered only: rejected as the default; time to first verified sentence would be the whole generation time.
- Vercel AI SDK: rejected; the protocol has custom events and the SDK adds little.

## Consequences

- Positive: "what was released equals what was validated" is checkable from the audit record.
- Negative: first visible text waits for the first validated sentence (budget p95 6 s; validator p95 150 ms per
  sentence on CPU); entailment needs human-labeled calibration data.
- Negative: the validator cannot catch a wrong source chunk or subtle negation beyond the calibrated rate.
- Proven by G7.3 (calibration), G7.4 (determinism across restarts), G7.6 (tamper and integrity), G7.7 (zero
  unverified sentences across 1,000 live queries), G7.8 (policies), G7.9 (write-ahead audit), G8.4 (stream torture).

## Current state

Two deviations in [docs/mvp.md](../mvp.md) are in force. Deviation 5: the MVP uses `buffered` delivery; the
whole answer is validated, then returned, with no sentence-by-sentence SSE. Deviation 4: V6 is a strict
Gemini entailment pass that can only remove sentences, never approve what the deterministic checks rejected,
and fails closed; it is not deterministic like a pinned model. V1 to V5, V7 and V8 are deterministic, plus quote
matching and lexical support; V3 is re-checked at release; query, ledger and audit event commit in one
transaction before anything is returned. Verdicts are not signed (no KMS-certified keys, deviations 6 and 9).

Stage 7 closes the gap: sentence-gated SSE, the pinned NLI model calibrated under G7.3, and signed verdicts.
