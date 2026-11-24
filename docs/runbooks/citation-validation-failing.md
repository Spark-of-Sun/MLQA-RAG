# Runbook: Citation validation pass rate dropped

1. Look at `query.completed` events: outcome distribution and stripped counts per model.
2. A model or prompt change is the usual cause: compare `prompt_sha256` and `model` before and after. Roll back the prompt version in `prompts/registry.toml` or the model in `LLM_MODEL`.
3. If V3 (hash) failures rise, chunks are changing after retrieval: check re-indexing jobs.
4. If V6 (entailment) failures rise, check `NLI_MODEL_HASH` and the threshold in `eval/floors.toml`. Never lower the threshold without an ADR.
