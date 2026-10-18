# Runbook: Citation validation failing (low pass rate / unexpected regenerations)

## Symptoms

- `make eval` reports a citation-validation pass rate below the configured
  threshold for `prompts/eval_sets/`.
- Users are seeing more "unverified" flags or more regenerations than
  usual (per-tenant `CITATION_VALIDATION_POLICY`).
- The `citation-validation-failing.yml` CI workflow is red on a PR that
  touches `prompts/` or `services/generation/`.

## First: confirm this is real, not a Citation Validator bug

Citation Validator is deterministic and should never itself be the source
of a *correct* citation failing — if it is, that's a Citation Validator
bug, not a generation/prompt regression. Distinguish the two:

```bash
# Re-run validation directly against a known-good answer + chunk set
docker compose exec citation-validator python -m app.parser.replay \
  --fixture tests/fixtures/known_good_answer.json
```

If a known-good fixture now fails, the bug is in
`services/citation_validator` (parser or entailment_check), not in
generation or the prompt. Check recent changes to
`services/citation_validator/app/parser` or `app/entailment_check` first.

## If Citation Validator itself is fine, check in this order

1. **Recent prompt template change.**
   - `prompts/templates/` is versioned; check which version is currently
     promoted for the affected tenant(s) and diff it against the last
     known-good version.
   - Look specifically for: changes to the `[chunk_N]` tag format, removal
     of the few-shot refusal example, or changes to how chunk metadata is
     injected (`<chunk id=... doc=... page=... section=...>`). The
     validator's parser depends on this format being exact.

2. **Chunk ID collision or chunk set mismatch.**
   - `ValidateRequest.retrieved_chunks` must be the *exact* set that was
     in context for that request. If Retrieval's re-rank order or
     trimming changed (e.g. `RERANK_TOP_K` lowered), the model may cite a
     chunk_id that's no longer in the set it's being checked against —
     this shows up as `chunk_not_in_retrieved_set`, not a real regression
     in the model's citation behavior.
   - Check `services/generation` logs for `dropped_chunk_ids` on affected
     requests — a chunk the model cited may have been trimmed by the
     token-budget step after generation saw it in a stale context.

3. **Entailment threshold miscalibration.**
   - `ENTAILMENT_SUPPORT_THRESHOLD` (default `0.55`) is global; a recent
     bump can turn previously-passing, genuinely-supported citations into
     `entailment_below_threshold` findings.
   - Check `.env` / tenant policy overrides for recent changes to this
     value before assuming the model regressed.

4. **Model/provider change (Generation).**
   - A swapped `LLM_MODEL` or provider can change citation-tag discipline
     even with an unchanged prompt. Check `services/generation/app/llm_client`
     config history.

## Diagnostic steps

```bash
# Run the eval set with verbose per-question findings
docker compose exec generation python /app/scripts/run_citation_eval.py --verbose

# Inspect findings for one failing eval question
docker compose exec citation-validator python -m app.parser.debug \
  --answer-id <answer_id>
```

Findings come back as a list of `CitationFinding` per
`docs/api-contracts/citation-validator.yaml`:
`chunk_not_in_retrieved_set`, `entailment_below_threshold`, or `ok`. Group
failures by `check` before digging further — the two failure modes have
unrelated root causes.

## Resolution

- If it's a prompt regression: roll back to the last promoted template
  version in the prompt registry; re-run `make eval` to confirm pass rate
  recovers before re-promoting a fixed version.
- If it's a retrieval/trim mismatch: fix the chunk-set consistency bug
  between Retrieval → Generation → Citation Validator before touching the
  prompt at all.
- If it's genuinely a model regression: this blocks the canary rollout for
  `generation` by design (§ Infrastructure & Deployment in
  `docs/architecture.md`) — do not override the gate manually.

## Escalation

A sustained drop in pass rate for a *specific* tenant only (not global)
should be escalated as a possible privilege/confidentiality-tier leak
investigation, not just a quality issue — confirm `retrieved_chunks`
never included a chunk outside that tenant's/matter's access grant before
closing this out as "just a prompt problem."
