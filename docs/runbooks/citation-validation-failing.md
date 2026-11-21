# Runbook: answers are being refused or sentences removed

The validator never lets an unverified sentence out, so a spike in `A claim ... could not be verified` is the safety
net working, not a bug in itself. Find which check fails (the reason code is in every `segment.stripped` audit event):

| Check | Meaning | Usual cause |
| --- | --- | --- |
| V1 / V4 | tag grammar / no citation | the model stopped citing: check the prompt hash and model id |
| V2 | alias not in the ledger | a model hallucinated a tag: expected occasionally |
| V3 | chunk changed or unreadable | a wall, suspension or deletion landed mid-answer (correct) |
| V5 | a number, date or dosage is not in the cited text | the model invented or rounded a figure (correct) |
| V6 | entailment below threshold | wrong threshold, or the NLI model changed: `NLI_MODEL_HASH` must match |

If **everything** fails: confirm `NLI_THRESHOLD` is a calibrated value (gate G7.3) and the NLI weights hash is the pinned one.
An uncalibrated placeholder threshold is logged at start-up.
