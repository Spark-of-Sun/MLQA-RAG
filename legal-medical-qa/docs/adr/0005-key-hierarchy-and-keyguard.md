# ADR 0005: Key hierarchy and KeyGuard

**Status:** Accepted

## Decision
Organization CMK wraps a random workspace key, which wraps random per-document keys (never derived, so each can be shredded alone). Destruction needs two people and a 30 day window; every organization key is born with a key policy that denies schedule/disable/policy-change to everyone but two KeyGuard roles.

## Why
One accidental or malicious key deletion is permanent, so destroying is made hard and restoring easy. Found and fixed during the build: runtime-created keys initially lacked the deny policy.
