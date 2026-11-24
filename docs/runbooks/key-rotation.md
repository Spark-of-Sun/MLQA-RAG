# Key rotation (R-53, blueprint 12.4)

Column values are sealed by `lmqa_keys.FieldCipher` (AES-256-GCM). Every value carries the version of the key that
sealed it in its header, so rotating a key never makes older values unreadable and never rewrites content.

## Routine: rotate a workspace content key

1. In a transaction as a role that may write `workspace_keys` (identity, or the local superuser for a drill):
   `KeyRing.rotate_workspace_key(conn, org_id, workspace_id)` adds the next version. New questions, answers and
   chat titles, and new document keys, use it from the next statement on; older versions stay `active` and readable.
2. Re-wrap document keys lazily, in batches, until it returns 0:
   `KeyRing.rewrap_document_keys(conn, org_id, workspace_id, limit=500)`. Document keys do not change, so titles and
   chunk text are not re-encrypted.
3. Processes pick the new version up immediately for new values; cached older keys expire within 15 minutes
   (`DekCache`).

The organization CMK rotates its own material in the provider (AWS KMS automatic rotation; OpenBao Transit
`transit/keys/<name>/rotate`), with no data rewrite (R-53.1).

## Emergency: a workspace content key is suspected exposed

1. Rotate as above, then run `rewrap_document_keys` to completion so no document key remains under the exposed
   version.
2. Values sealed directly with the exposed version (questions, answers, chat titles) are still readable with it.
   To retire it, re-seal those rows under the new version; only then may the old version be destroyed (KeyGuard).
3. If the organization CMK itself is suspected, create a new CMK (new `org_keys` version) and re-wrap every
   `workspace_keys` and `audit_keys` row of the organization under it before disabling the old CMK through KeyGuard.

Steps 2 and 3 have no tool yet; they are listed so the order is fixed before one is written.

## Local key mode

Locally the CMKs live in OpenBao (`compose.yaml`, `infra/compose/openbao/lmqa.hcl`): Transit keys persist in the
`openbao` volume and the server unseals itself with `OPENBAO_UNSEAL_KEY`. Losing that key or the volume makes every
encrypted column unreadable; `make db-reset` removes both together with the data.
