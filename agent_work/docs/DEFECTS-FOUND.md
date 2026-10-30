# Defects found during the build

Real servers and real documents found these. A mocked test suite would have hidden most of them. Each was fixed and
now has a regression test, except where noted. (The authoritative, time-stamped record is `agent_work/logs/worklog.md`.)

## Security-relevant (the ones that matter most)

| # | Defect | Found by | Fix |
| --- | --- | --- | --- |
| 1 | `svc_identity` could read wrapped audit **private keys** (table-wide SELECT), breaking "only the audit service unwraps" | audit sealing test | INSERT plus column-level SELECT of public fields only |
| 2 | Per-organization KMS keys are created **at runtime** with AWS's default key policy, so the KeyGuard deny (no schedule/disable/policy change) only protected two Terraform keys | writing the AWS IaC | `kms_key_policy()` is applied to every new key; production start-up refuses to run without the KeyGuard role ARNs |
| 3 | A user could WRITE their own membership row (a pending tenant could activate themselves if service code allowed it) | identity escalation test | own row is read-only; writes need an approver role; explicit role guards |
| 4 | `ON` in the authorization matrix is the YAML boolean `true`, so every onboarding route had roles `[True]`: **nobody could onboard** | gateway e2e test | role codes quoted; a contract test rejects non-string roles |
| 5 | A lint autofix moved `UUID`/`datetime` imports under `TYPE_CHECKING` in every FastAPI app, which breaks request models and path parameters at runtime | exporting OpenAPI | runtime imports restored; ruff configured for Pydantic; HTTP-level regression test |
| 6 | A code pasted without dashes was **not scrubbed** from log text | redaction test | contiguous Crockford runs are redacted |
| 7 | Crypto-shred `UPDATE` silently matched 0 rows (the policy did not admit the system context) | audit client test | policy and column grant added |
| 8 | `object_key()` accepted arbitrary strings (path-traversal shaped input) | object store test | only typed UUIDs are accepted |
| 9 | A cascade-disabled join code could not move to `rotated`, contradicting "stays dead until rotated" | identity cascade test | transition added to `state-machines.yaml` |
| 10 | The authorization matrix and the service disagreed (one generic `/{action}` route vs four explicit routes) | OpenAPI-vs-matrix drift test | four explicit routes; the test also catches unreachable or allow-listed-but-missing routes |

## Correctness and robustness

| # | Defect | Found by |
| --- | --- | --- |
| 11 | OpenBao key `DELETE` returns an empty 204; the adapter parsed JSON unconditionally | real OpenBao |
| 12 | AWS aliases must start with `alias/`; the adapter would have failed on first real use | writing the IaC |
| 13 | `CreateKey` was allowed by IAM only with a `project=lmqa` tag the adapter never set | reviewing the IAM policy |
| 14 | `decrypt` was not imported in the ingestion pipeline (document listing would crash) | ruff `F821` |
| 15 | HTML/JATS magic-byte detection missed the SEC EDGAR SGML wrapper and `<!DOCTYPE article>` | real corpus |
| 16 | A run-on block above the token maximum; heading-only chunks; overlap rarely applied | real documents |
| 17 | `gen_env.py` gave every `<RANDOM_64_HEX_CHARS>` the **same** value | its own test |
| 18 | `release.yml` used a non-existent GitHub Actions `replace()` function | review |
| 19 | The first SCP exempted the identity role from the whole destructive-action deny | review (now two statements) |
| 20 | Network policy gave every service egress to all of `10.0.0.0/8`, defeating "only retrieval and ingestion reach Qdrant" | review (now a data-subnet CIDR plus a pod selector) |
| 21 | The memory-hungry embedder was loaded before configuration was validated | entrypoint test (settings first, models last) |
| 22 | `typescript-eslint` does not support TypeScript 7; I had picked the newest | `pnpm lint` (pinned to 6.0.3, recorded) |
| 23 | `enableAccessTokenEndpoint` defaults to **true** in the Auth0 SDK and would expose the access token to the browser | reading the SDK types (set to false) |

## Mistakes in my own process (recorded, not hidden)

* A multi-line `str.replace` silently matched nothing after `ruff format` reflowed a file, leaving the verifier
  referencing an undefined attribute. Since then every bulk edit asserts exactly one match.
* A greedy regex edit corrupted `identity/domain.py` across statements; the file was restored and the rule
  "no regex edits across statements" was added to `CONTRIBUTING.md`.
* `pkill -f` matched my own shell's command line. Processes are now stopped by exact name.
* A helper script split a docstring as if it were a string literal; caught by ruff, fixed by hand.
* The sandbox was paused and resumed many times; several writes were lost. After each resume the files were checked
  and re-written rather than assumed.
