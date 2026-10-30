#!/usr/bin/env bash
# Usage: log.sh <STEP> <STATUS> "<message>"   STATUS: START|DONE|FAIL|NOTE|DECISION|DEVIATION
set -euo pipefail
LOGDIR="$(cd "$(dirname "$0")/../logs" && pwd)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STEP="${1:?step}"; STATUS="${2:?status}"; MSG="${3:?message}"
printf '| %s | %s | %s | %s |\n' "$TS" "$STEP" "$STATUS" "$MSG" >> "$LOGDIR/worklog.md"
python3 - "$TS" "$STEP" "$STATUS" "$MSG" >> "$LOGDIR/worklog.jsonl" <<'PY'
import json,sys
ts,step,status,msg=sys.argv[1:5]
print(json.dumps({"ts":ts,"step":step,"status":status,"message":msg}))
PY
