#!/usr/bin/env bash
# Pack every file git ignores (settings and secrets, Terraform state, Kiro reports, agent_work, local data, the
# fetched corpus) into one zip, keeping each file's path relative to the repo root. Restore it on another machine,
# after `git clone`, with tools/unpack-ignored.sh (docs/deploy.md, step 1).
#
#   tools/pack-ignored.sh [--all] [output.zip]
#
# By default, things that are rebuilt or downloaded again are left out: .venv, node_modules, build output (.next,
# .open-next, .wrangler), caches, Terraform provider binaries (.terraform), downloaded models (data/models) and the
# rendered infrastructure credentials (data/infra, rewritten by `make up`). --all packs those too.
#
# The zip holds secrets: it is created with mode 600, outside git (lmqa-ignored-*.zip is ignored). Copy it over SSH
# (scp), never through chat, email or a public link, and delete it once it is unpacked.
set -euo pipefail

all=0
out=""
for arg in "$@"; do
  case "$arg" in
    --all) all=1 ;;
    -h | --help) sed -n '2,13p' "$0"; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) out="$arg" ;;
  esac
done

command -v zip >/dev/null || { echo "zip is not installed (sudo apt install zip)" >&2; exit 1; }
root="$(git rev-parse --show-toplevel)"
cd "$root"
out="${out:-lmqa-ignored-$(date +%Y%m%d-%H%M%S).zip}"
case "$out" in /*) ;; *) out="$root/$out" ;; esac

# Path components or paths that are never worth carrying (unless --all).
skip='(^|/)(\.venv|node_modules|\.next|\.next-[^/]*|\.open-next|\.wrangler|__pycache__|\.pytest_cache|\.hypothesis|\.ruff_cache|\.import_linter_cache|\.mypy_cache|\.terraform)(/|$)'
skip+='|\.pyc$|\.tsbuildinfo$|(^|/)next-env\.d\.ts$|^data/models/|^data/infra/|^lmqa-ignored-[^/]*\.zip$'

list="$(mktemp)"
trap 'rm -f "$list"' EXIT
# -z: names with spaces are safe. A name containing a newline cannot go through `zip -@` and is reported instead.
git ls-files --others --ignored --exclude-standard -z \
  | { if [ "$all" = 1 ]; then cat; else grep -z -v -E "$skip" || true; fi; } \
  | while IFS= read -r -d '' f; do
      if [[ "$f" == *$'\n'* ]]; then echo "skipped (newline in name): ${f//$'\n'/?}" >&2; continue; fi
      [ -e "$f" ] || [ -L "$f" ] && printf '%s\n' "$f"
    done > "$list"

count="$(wc -l < "$list")"
if [ "$count" -eq 0 ]; then echo "no ignored files to pack" >&2; exit 1; fi

rm -f "$out"
(umask 077 && zip -q -y -X "$out" -@ < "$list")
chmod 600 "$out"

echo "packed $count files into $out ($(du -h "$out" | cut -f1))"
echo "top-level entries:"
cut -d/ -f1 "$list" | sort | uniq -c | sort -rn | awk '{printf "  %6d  %s\n", $1, $2}'
echo "copy it to the server:  scp \"$out\" root@<server-address>:/root/"
