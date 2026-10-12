#!/usr/bin/env bash
# Block commits and pushes that contain private terms: employer, client and colleague
# names, personal paths, account IDs. The terms live in .git/info/private-terms (one
# extended regex per line, case-insensitive, # for comments), which git never pushes.
#
#   scripts/check-private-terms.sh           check the working tree
#   scripts/check-private-terms.sh --staged  check the index (pre-commit hook)
#   scripts/check-private-terms.sh --push    read pre-push stdin; check each pushed tree and message
set -euo pipefail
terms="$(git rev-parse --git-dir)/info/private-terms"
[ -s "$terms" ] || { echo "check-private-terms: no $terms, nothing checked" >&2; exit 0; }
patterns=$(grep -v -E '^[[:space:]]*(#|$)' "$terms")
skip=(':(exclude)plugins/peers/web/vendor/*' ':(exclude)scripts/check-private-terms.sh')
found=0
scan() {  # git grep args...
  if git grep -n -I -i -E -e "$patterns" "$@" -- . "${skip[@]}"; then found=1; fi
}
case "${1:-}" in
  --staged) scan --cached ;;
  --push)
    while read -r _ local_sha _ remote_sha; do
      [[ $local_sha =~ ^0+$ ]] && continue
      scan "$local_sha"
      range=$local_sha; [[ $remote_sha =~ ^0+$ ]] || range="$remote_sha..$local_sha"
      if git log --format='%H %B' "$range" | grep -n -i -E -e "$patterns"; then found=1; fi
    done ;;
  *) scan --untracked ;;
esac
if (( found )); then
  echo >&2; echo "check-private-terms: the lines above match .git/info/private-terms; remove them or edit the list." >&2
  exit 1
fi
