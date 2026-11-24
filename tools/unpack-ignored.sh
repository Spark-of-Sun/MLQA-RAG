#!/usr/bin/env bash
# Put the files packed by tools/pack-ignored.sh back where they were, inside a fresh clone (docs/deploy.md, step 1).
#
#   tools/unpack-ignored.sh [--force] path/to/lmqa-ignored-YYYYMMDD-HHMMSS.zip
#
# Run it from anywhere inside the clone. Every entry lands at the same path relative to the repo root.
#   - An entry whose path is tracked by git is never written (the branch's version wins); it is listed instead.
#   - An existing untracked file is kept unless --force is given.
#   - Entries that try to leave the repo (absolute paths, ..) are refused.
# Afterwards settings and key files are set to mode 600, and the script checks that no tracked file changed.
set -euo pipefail

force=0
zipfile=""
for arg in "$@"; do
  case "$arg" in
    --force) force=1 ;;
    -h | --help) sed -n '2,11p' "$0"; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) zipfile="$arg" ;;
  esac
done
[ -n "$zipfile" ] || { echo "usage: tools/unpack-ignored.sh [--force] <file.zip>" >&2; exit 2; }
[ -f "$zipfile" ] || { echo "not found: $zipfile" >&2; exit 1; }
command -v unzip >/dev/null || { echo "unzip is not installed (sudo apt install unzip)" >&2; exit 1; }
zipfile="$(cd "$(dirname "$zipfile")" && pwd)/$(basename "$zipfile")"

root="$(git rev-parse --show-toplevel)"
cd "$root"

entries="$(mktemp)"
tracked="$(mktemp)"
before="$(mktemp)"
trap 'rm -f "$entries" "$tracked" "$before"' EXIT

# `zipinfo -1` lists one name per line, directories end with /.
zipinfo -1 "$zipfile" > "$entries"
if grep -q -E '(^/|(^|/)\.\.(/|$))' "$entries"; then
  echo "refused: the zip contains absolute paths or '..' entries" >&2
  exit 1
fi

# Tracked paths in the zip are excluded from extraction.
git ls-files -z | tr '\0' '\n' | LC_ALL=C sort > "$before.all"
LC_ALL=C sort "$entries" | LC_ALL=C comm -12 - "$before.all" > "$tracked"
rm -f "$before.all"
git status --porcelain=v1 > "$before"

excludes=()
if [ -s "$tracked" ]; then
  echo "kept the branch's version of these tracked files (not written from the zip):"
  sed 's/^/  /' "$tracked"
  while IFS= read -r f; do excludes+=("$f"); done < "$tracked"
fi

mode=(-n)
[ "$force" = 1 ] && mode=(-o)
# unzip exit codes: 0 ok, 1 warnings, 11 nothing left to extract (every entry was excluded).
rc=0
if [ "${#excludes[@]}" -gt 0 ]; then
  unzip -q "${mode[@]}" "$zipfile" -d "$root" -x "${excludes[@]}" || rc=$?
else
  unzip -q "${mode[@]}" "$zipfile" -d "$root" || rc=$?
fi
case "$rc" in 0 | 1 | 11) ;; *) echo "unzip failed (exit $rc)" >&2; exit "$rc" ;; esac

# Settings, secrets and state files: owner only, whatever the zip recorded.
while IFS= read -r f; do
  case "$f" in
    */) continue ;;
    .env | .env.* | */.env | */.env.* | .secrets* | *.pem | *.key | *.tfstate | *.tfstate.* | *.tfplan | example-env.txt)
      [ -f "$f" ] && chmod 600 "$f" ;;
  esac
done < "$entries"

if ! git status --porcelain=v1 | diff -q - "$before" >/dev/null; then
  echo "warning: git status changed; check \`git status\` (a packed file may no longer be ignored on this branch)" >&2
fi

total="$(grep -c -v '/$' "$entries" || true)"
echo "restored up to $total files into $root ($([ "$force" = 1 ] && echo 'existing files overwritten' || echo 'existing files kept'))"
echo "delete the zip when done:  shred -u \"$zipfile\""
