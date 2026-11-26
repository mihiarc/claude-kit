#!/usr/bin/env bash
# Block commits and pushes that contain private terms: employer, client and colleague
# names, personal paths, account IDs. The terms live in info/private-terms in the repo's
# common git dir (one extended regex per line, case-insensitive, # for comments), which git
# never pushes. The hooks in scripts/hooks run it once core.hooksPath points there, and
# refuse every commit and push while the list holds no terms.
#
#   scripts/check-private-terms.sh           check the working tree
#   scripts/check-private-terms.sh --staged  check the index (pre-commit hook)
#   scripts/check-private-terms.sh --push [remote [url]]
#                                            read pre-push stdin; check every commit the remote
#                                            at url doesn't hold (files, file names, message,
#                                            author and committer) and each pushed tag.
# File contents (binary ones too) and file names are both checked. One regex engine, this
# grep, checks the list and does every match: git grep's engine differs (Homebrew's ignores
# \b, for one), so a term it accepted could silently never match.
set -euo pipefail
# The common dir, so linked worktrees read the same list as the main checkout.
terms="$(git rev-parse --path-format=absolute --git-common-dir)/info/private-terms"
# Carriage returns and blanks around each term are dropped, so a CRLF list or a stray
# trailing space can't make a term unmatchable. A list with no terms counts as missing.
# Byte by byte (LC_ALL=C), so a byte that isn't valid UTF-8 can't stop the read and drop
# every term after it.
patterns=$( { LC_ALL=C tr -d '\r' <"$terms" 2>/dev/null || true; } \
  | LC_ALL=C sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | LC_ALL=C grep -v -E '^(#|$)' || true)
if [ -z "$patterns" ]; then
  case "${1:-}" in
    # A hook with no list guards nothing, so the commit or push it runs for is refused.
    --staged|--push)
      what=commit; [ "$1" = --push ] && what=push
      echo "check-private-terms: no terms in $terms, so this $what is refused. Write your list there (CLAUDE.md says how), or turn the hooks off with: git config --unset core.hooksPath" >&2
      exit 1 ;;
    *) echo "check-private-terms: no terms in $terms, nothing checked" >&2; exit 0 ;;
  esac
fi
rc=0; rc8=0
LC_ALL=C grep -i -E -e "$patterns" </dev/null >/dev/null 2>&1 || rc=$?
grep -i -E -e "$patterns" </dev/null >/dev/null 2>&1 || rc8=$?
if (( rc > 1 || rc8 > 1 )); then
  echo "check-private-terms: a line in $terms is not a valid extended regex; fix it before anything is committed or pushed." >&2
  exit 1
fi

self=scripts/check-private-terms.sh  # its own text isn't checked
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
found=0
hit() {  # exit status of a search, what was searched: 0 is a match, 1 none, anything else an error
  case $1 in
    0) found=1 ;;
    1) ;;
    *) echo "check-private-terms: searching $2 failed (exit $1)" >&2; found=1 ;;
  esac
}
grep_file() {  # file, label: print the file's matching lines under the label
  # Byte by byte first (LC_ALL=C): in a UTF-8 locale grep silently skips a line holding bytes
  # that aren't valid UTF-8. Then, only if that found nothing, in the person's locale, so a
  # non-ASCII term still matches its other case.
  local rc=0
  LC_ALL=C grep -a -n -i -E -e "$patterns" -- "$1" >"$tmp/out" 2>"$tmp/err" || rc=$?
  if (( rc == 1 )); then
    rc=0; grep -a -n -i -E -e "$patterns" -- "$1" >"$tmp/out" 2>"$tmp/err" || rc=$?
  fi
  if (( rc == 0 )); then LC_ALL=C tr -d '\000' <"$tmp/out" | L="$2" LC_ALL=C awk '{ print ENVIRON["L"] ": " $0 }'; fi
  if (( rc > 1 )); then cat "$tmp/err" >&2; fi
  hit $rc "$2"
}
grep_blob() {  # sha, label
  if git cat-file blob "$1" >"$tmp/blob"; then grep_file "$tmp/blob" "$2"; else hit 2 "$2"; fi
}
grep_names() {  # NUL-separated list of file names, label. NULs, not git's quoting, so a
  # non-ASCII name is matched as itself.
  tr '\0' '\n' <"$1" >"$tmp/names"
  grep_file "$tmp/names" "file names of $2"
}
grep_entries() {  # `git ls-tree -r -z` or `git ls-files -s -z` output, label: each distinct
  # blob once, under the first name it was seen at; and every file name
  local rec meta path mode type sha
  : >"$tmp/recs"; : >"$tmp/allnames"
  while IFS= read -r -d '' rec; do
    meta=${rec%%$'\t'*}; path=${rec#*$'\t'}
    printf '%s\0' "$path" >>"$tmp/allnames"
    if [ "$2" = index ]; then
      read -r mode sha _ <<<"$meta"; type=blob
      if [ "$mode" = 160000 ]; then type=commit; fi
    else read -r mode type sha <<<"$meta"; fi
    if [ "$type" = blob ] && [ "$path" != "$self" ]; then printf '%s\t%s\0' "$sha" "$path" >>"$tmp/recs"; fi
  done <"$1"
  sort -z -u -t "$(printf '\t')" -k1,1 "$tmp/recs" >"$tmp/blobs"
  while IFS= read -r -d '' rec; do
    grep_blob "${rec%%$'\t'*}" "${rec#*$'\t'} ($2)"
  done <"$tmp/blobs"
  sort -z -u "$tmp/allnames" >"$tmp/names0"
  grep_names "$tmp/names0" "$2"
}

case "${1:-}" in
  --staged)
    if git ls-files -s -z >"$tmp/index"; then grep_entries "$tmp/index" index; else hit 2 "the index"; fi ;;
  --push)
    remote=${2:-origin}; url=${3:-$remote}
    # What the remote really holds, asked of the remote itself. Local refs/remotes/<name>/*
    # can be stale, or belong to another repo after `git remote set-url`, so they don't count.
    held=$(git ls-remote "$url" | awk '{print $1}' | sort -u) || {
      echo "check-private-terms: can't list what $url holds, so this push is refused." >&2; exit 1; }
    have=()
    for s in $held; do
      if git cat-file -e "$s^{commit}" 2>/dev/null; then have+=("$s"); fi  # not one this clone lacks
    done
    : >"$tmp/trees"
    while read -r local_ref local_sha _ _; do
      [[ $local_sha =~ ^0+$ ]] && continue
      obj=$local_sha
      # A tag's message, and each tag it points through, then what it finally names.
      while [ "$(git cat-file -t "$obj")" = tag ]; do
        git cat-file tag "$obj" >"$tmp/tag"; grep_file "$tmp/tag" "tag $local_ref"
        obj=$(git cat-file tag "$obj" | sed -n '1s/^object //p')
      done
      case $(git cat-file -t "$obj") in
        blob) grep_blob "$obj" "the blob $local_ref names" ;;
        tree) git ls-tree -r -z "$obj" >>"$tmp/trees" || hit 2 "the tree $local_ref names" ;;
        commit)
          # The commits the remote lacks; on an empty remote, the whole history.
          commits=$(git rev-list "$obj" --not ${have[@]+"${have[@]}"}) || {
            hit 2 "the commits of $local_ref"; continue; }
          for c in $commits; do git ls-tree -r -z "$c" >>"$tmp/trees" || hit 2 "the tree of $c"; done
          if git log --format='%H author %an <%ae> committer %cn <%ce>%n%B' "$obj" --not ${have[@]+"${have[@]}"} >"$tmp/log"; then
            grep_file "$tmp/log" "commits of $local_ref"
          else hit 2 "the messages of $local_ref"; fi ;;
      esac
    done
    grep_entries "$tmp/trees" "commits the remote lacks" ;;
  *)
    cd "$(git rev-parse --show-toplevel)"
    git ls-files -co --exclude-standard -z >"$tmp/wt" || hit 2 "the working tree's file list"
    while IFS= read -r -d '' path; do
      if [ "$path" = "$self" ]; then continue; fi
      if [ -L "$path" ]; then readlink "$path" >"$tmp/link"; grep_file "$tmp/link" "$path"
      elif [ -f "$path" ]; then grep_file "$path" "$path"; fi
    done <"$tmp/wt"
    grep_names "$tmp/wt" "the working tree" ;;
esac
if (( found )); then
  echo >&2; echo "check-private-terms: the lines above match $terms, or a search failed; remove the matches or edit the list." >&2
  exit 1
fi
