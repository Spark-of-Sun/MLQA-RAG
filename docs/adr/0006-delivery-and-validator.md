# ADR 0006: Delivery and validator

**Status:** Accepted

## Decision
Sentence-gated release: the Validator segments the stream, checks each sentence (V1-V8) and signs a verdict; the Gateway releases a sentence only with a valid verdict for exactly that sentence, after a write-ahead audit record. No provisional (unverified) mode exists.

## Why
'Every citation is machine-validated before it reaches the user' cannot hold if raw tokens stream out first.
